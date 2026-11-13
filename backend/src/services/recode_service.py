"""换码迁移编排：方案 → 对齐校验 → 预览（影响面）→ 执行（逐映射提交、断点续跑）→ 核对。

口径与设计：
  可预览   preview 只读计算影响面（商品/小票/规则/建议位 + 合并后指标投影），落快照；
           方案一旦开始执行，预览冻结（409），避免半迁移状态下给出误导数字。
  可执行   execute 要求先预览；执行前对当前主数据重跑对齐校验，未对齐直接 422、零写入。
  幂等     映射行在建方案时一次落库，执行不新增；已应用映射跳过；已完成的方案重跑
           直接返回原结果（不重复重算）。
  断点续跑 每条映射一个事务（小票改写 + 别名 + 停用 + 计数 + checkpoint 同提交）；
           失败只回滚当前映射，再次执行从第一条未完成映射继续；迁移前快照只取一次。
  核对     全部映射完成后做守恒核对（小票数/行数/在售商品数/旧码归零/新码并集），
           任一不过 → 方案置失败，绝不留「半套结果」还自称成功。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.constants import error_codes as codes
from src.constants.enums import RecodeMappingStatus, RecodeStatus, SkuStatus, SlotStatus
from src.constants.log_templates import (
    ACTION_RECODE_CREATE,
    ACTION_RECODE_EXECUTE,
    ACTION_RECODE_PREVIEW,
)
from src.models.order_basket import OrderBasket
from src.models.mining_run import MiningRun
from src.models.planogram_slot import PlanogramSlot
from src.models.rule_candidate import RuleCandidate
from src.models.rule_review import RuleReview
from src.models.sku import Sku
from src.models.sku_recode import SkuAlias, SkuRecodeMapping, SkuRecodePlan
from src.models.user import User
from src.services import audit_service, basket_service, mining_service, recode_core
from src.utils.errors import AppError
from src.utils.logger import get_logger

logger = get_logger("basketrule.recode")

SAMPLE_BASKETS_PER_MAPPING = 6


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- 查询 ----


def get_plan(db: Session, plan_id: str) -> SkuRecodePlan:
    plan = db.get(SkuRecodePlan, plan_id)
    if plan is None:
        raise AppError(codes.NOT_FOUND, "换码方案不存在", f"plan_id={plan_id}")
    return plan


def _mappings(db: Session, plan_id) -> list[SkuRecodeMapping]:
    return list(
        db.execute(
            select(SkuRecodeMapping)
            .where(SkuRecodeMapping.plan_id == plan_id)
            .order_by(SkuRecodeMapping.created_at, SkuRecodeMapping.old_code)
        ).scalars()
    )


def list_plans(db: Session) -> dict:
    plans = list(
        db.execute(select(SkuRecodePlan).order_by(SkuRecodePlan.created_at.desc())).scalars()
    )
    items = []
    for plan in plans:
        mappings = _mappings(db, plan.id)
        items.append(_serialize_plan(plan, mappings))
    return {"plans": items, "count": len(items)}


def _serialize_plan(plan: SkuRecodePlan, mappings: list[SkuRecodeMapping]) -> dict:
    applied = sum(1 for m in mappings if m.status == RecodeMappingStatus.APPLIED.value)
    return {
        "id": str(plan.id),
        "plan_code": plan.plan_code,
        "title": plan.title,
        "status": plan.status,
        "error": plan.error,
        "mapping_count": len(mappings),
        "applied_count": applied,
        "previewed_at": (plan.preview or {}).get("computed_at"),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "started_at": plan.started_at.isoformat() if plan.started_at else None,
        "finished_at": plan.finished_at.isoformat() if plan.finished_at else None,
    }


def _serialize_mapping(row: SkuRecodeMapping) -> dict:
    return {
        "id": str(row.id),
        "old_code": row.old_code,
        "new_code": row.new_code,
        "old_name": row.old_name,
        "new_name": row.new_name,
        "create_sku": row.create_sku,
        "status": row.status,
        "affected_baskets": row.affected_baskets,
        "affected_rules": row.affected_rules,
        "affected_slots": row.affected_slots,
        "applied_baskets": row.applied_baskets,
        "applied_lines": row.applied_lines,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def plan_detail(db: Session, plan: SkuRecodePlan) -> dict:
    mappings = _mappings(db, plan.id)
    aliases = list(
        db.execute(select(SkuAlias).where(SkuAlias.plan_id == plan.id)).scalars()
    )
    return {
        "plan": _serialize_plan(plan, mappings),
        "mappings": [_serialize_mapping(row) for row in mappings],
        "aliases": [
            {"old_code": row.old_code, "new_code": row.new_code, "created_at": row.created_at.isoformat()}
            for row in aliases
        ],
        "impact": plan.preview or None,
        "reconciliation": plan.result or None,
    }


# ---------------------------------------------------------------- 创建 ----


def _sku_status_map(db: Session) -> dict[str, str]:
    rows = db.execute(select(Sku.code, Sku.status)).all()
    return {code: status for code, status in rows}


def create_plan(db: Session, user: User, payload: dict, trace_id: str = "") -> dict:
    mappings_in = payload.get("mappings") or []
    sku_status = _sku_status_map(db)
    validation_input = [
        {"old_code": m["old_code"], "new_code": m["new_code"], "create_sku": bool(m.get("create_sku"))}
        for m in mappings_in
    ]
    errors = recode_core.validate_mappings(validation_input, sku_status)
    if errors:
        raise AppError(
            codes.VALIDATION_ERROR,
            "新旧身份未对齐，方案未落库",
            "; ".join(errors),
            extra={"errors": errors},
        )

    plan_code = (payload.get("plan_code") or "").strip()
    if not plan_code:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        plan_code = f"RECODE-{stamp}"
        seq = 1
        while db.execute(select(SkuRecodePlan.id).where(SkuRecodePlan.plan_code == plan_code)).first():
            seq += 1
            plan_code = f"RECODE-{stamp}-{seq}"
    elif db.execute(select(SkuRecodePlan.id).where(SkuRecodePlan.plan_code == plan_code)).first():
        raise AppError(codes.CONFLICT, "方案编号已存在", f"plan_code={plan_code}")

    names, _ = basket_service.sku_maps(db)
    plan = SkuRecodePlan(
        plan_code=plan_code,
        title=(payload.get("title") or "").strip(),
        status=RecodeStatus.DRAFT.value,
        mappings_input=validation_input,
        preview={},
        result={},
        checkpoint={},
        created_by=user.id,
    )
    db.add(plan)
    db.flush()
    for item in mappings_in:
        create_sku = item.get("create_sku")
        new_name = (
            create_sku["name"] if create_sku else names.get(item["new_code"], item["new_code"])
        )
        db.add(
            SkuRecodeMapping(
                plan_id=plan.id,
                old_code=item["old_code"],
                new_code=item["new_code"],
                create_sku=create_sku,
                old_name=names.get(item["old_code"], item["old_code"]),
                new_name=new_name,
                status=RecodeMappingStatus.PENDING.value,
            )
        )
    audit_service.record(
        db,
        action=ACTION_RECODE_CREATE,
        actor=user,
        entity_type="sku_recode_plan",
        entity_id=plan.plan_code,
        detail={"plan_code": plan.plan_code, "mappings": len(mappings_in)},
        trace_id=trace_id,
    )
    db.commit()
    logger.info("recode plan %s created with %s mappings", plan.plan_code, len(mappings_in))
    return plan_detail(db, plan)


# ---------------------------------------------------------------- 影响面 ----


def _affected_rules(db: Session, old_codes: set[str]) -> list[RuleCandidate]:
    rows = list(db.execute(select(RuleCandidate)).scalars().all())
    return [
        row
        for row in rows
        if old_codes & set(row.antecedent or []) or old_codes & set(row.consequent or [])
    ]


def _impact(db: Session, mappings: list[SkuRecodeMapping]) -> dict:
    """只读影响面：受影响的商品 / 小票 / 规则 / 建议位 + 合并后指标投影。"""
    full_mapping = {m.old_code: m.new_code for m in mappings}
    old_codes = set(full_mapping)
    names, _ = basket_service.sku_maps(db)
    for m in mappings:  # 新码可能尚未创建，名称取自方案声明
        names.setdefault(m.new_code, m.new_name or m.new_code)

    basket_rows = db.execute(select(OrderBasket.basket_no, OrderBasket.lines)).all()
    transactions = [
        (frozenset(line["sku"] for line in lines), "") for _, lines in basket_rows
    ]
    supports = recode_core.sku_supports(
        transactions, old_codes | {m.new_code for m in mappings}
    )

    rules = _affected_rules(db, old_codes)
    run_ids = {row.run_id for row in rules}
    runs = {
        row.id: row.run_label
        for row in db.execute(select(MiningRun.id, MiningRun.run_label).where(MiningRun.id.in_(run_ids))).all()
    } if run_ids else {}
    rule_ids = [row.id for row in rules]
    slots = []
    if rule_ids:
        slots = list(
            db.execute(select(PlanogramSlot).where(PlanogramSlot.rule_id.in_(rule_ids))).scalars()
        )
    slots_by_rule: dict = {}
    for slot in slots:
        slots_by_rule.setdefault(slot.rule_id, []).append(slot)
    review_counts: dict = {}
    if rule_ids:
        for rule_id, count in db.execute(
            select(RuleReview.rule_id, func.count()).where(RuleReview.rule_id.in_(rule_ids)).group_by(RuleReview.rule_id)
        ).all():
            review_counts[rule_id] = count

    latest = mining_service.latest_run(db)
    latest_rules = [row for row in rules if latest is not None and row.run_id == latest.id]
    projection = recode_core.project_rules(
        [{"antecedent": row.antecedent, "consequent": row.consequent} for row in latest_rules],
        transactions,
        full_mapping,
    )

    per_mapping: list[dict] = []
    all_baskets: set[str] = set()
    for m in mappings:
        old, new = m.old_code, m.new_code
        with_old = [no for no, lines in basket_rows if any(line["sku"] == old for line in lines)]
        both = [
            no
            for no, lines in basket_rows
            if any(line["sku"] == old for line in lines) and any(line["sku"] == new for line in lines)
        ]
        all_baskets.update(with_old)
        m_rules = [row for row in rules if old in (row.antecedent or []) or old in (row.consequent or [])]
        m_slots = [slot for row in m_rules for slot in slots_by_rule.get(row.id, [])]
        per_mapping.append(
            {
                "old_code": old,
                "new_code": new,
                "old_name": m.old_name,
                "new_name": m.new_name,
                "baskets": len(with_old),
                "both_baskets": len(both),
                "sample_baskets": sorted(with_old)[:SAMPLE_BASKETS_PER_MAPPING],
                "support": {
                    "old": supports[old],
                    "new": supports[new],
                    "merged": supports[old] + supports[new] - len(both),
                },
                "rules": [
                    {
                        "id": str(row.id),
                        "rule_key": row.rule_key,
                        "run_label": runs.get(row.run_id, ""),
                        "label": f"{' + '.join(names.get(c, c) for c in row.antecedent)} → "
                        f"{' + '.join(names.get(c, c) for c in row.consequent)}",
                        "status": row.status,
                        "lift": float(row.lift),
                        "cooccur_count": row.cooccur_count,
                    }
                    for row in m_rules
                ],
                "slots": [
                    {
                        "slot_key": slot.slot_key,
                        "plan_code": slot.plan_code,
                        "shelf_label": slot.shelf_label,
                        "status": slot.status,
                    }
                    for slot in m_slots
                ],
                "reviews": sum(review_counts.get(row.id, 0) for row in m_rules),
            }
        )

    return {
        "computed_at": _now().isoformat(),
        "mappings": per_mapping,
        "rule_projection": projection,
        "totals": {
            "skus": len(mappings),
            "baskets": len(all_baskets),
            "rules": len({row.id for row in rules}),
            "slots": len({slot.id for slot in slots}),
            "reviews": sum(review_counts.values()),
        },
    }


def preview_plan(db: Session, user: User, plan_id: str, trace_id: str = "") -> dict:
    plan = get_plan(db, plan_id)
    if plan.status not in (RecodeStatus.DRAFT.value, RecodeStatus.PREVIEWED.value):
        raise AppError(
            codes.CONFLICT,
            "方案已开始执行，预览已冻结",
            f"plan_code={plan.plan_code} status={plan.status}",
        )
    mappings = _mappings(db, plan.id)
    impact = _impact(db, mappings)
    plan.preview = impact
    if plan.status == RecodeStatus.DRAFT.value:
        plan.status = RecodeStatus.PREVIEWED.value
    by_code = {m.old_code: m for m in mappings}
    for item in impact["mappings"]:
        row = by_code[item["old_code"]]
        row.affected_baskets = item["baskets"]
        row.affected_rules = len(item["rules"])
        row.affected_slots = len(item["slots"])
    audit_service.record(
        db,
        action=ACTION_RECODE_PREVIEW,
        actor=user,
        entity_type="sku_recode_plan",
        entity_id=plan.plan_code,
        detail={"plan_code": plan.plan_code, "totals": impact["totals"]},
        trace_id=trace_id,
    )
    db.commit()
    return plan_detail(db, plan)


# ---------------------------------------------------------------- 执行 ----


def _snapshot_before(db: Session, mappings: list[SkuRecodeMapping]) -> dict:
    """迁移前快照（只取一次，存 checkpoint；续跑时复用，绝不重拍）。"""
    full_mapping = {m.old_code: m.new_code for m in mappings}
    transactions = basket_service.load_transactions(db)
    basket_count = db.execute(select(func.count()).select_from(OrderBasket)).scalar_one()
    lines_total = db.execute(select(func.coalesce(func.sum(OrderBasket.item_count), 0))).scalar_one()
    skus_active = db.execute(
        select(func.count()).select_from(Sku).where(Sku.status == SkuStatus.ACTIVE.value)
    ).scalar_one()
    sku_codes = set(_sku_status_map(db))

    supports: dict[str, dict] = {}
    for m in mappings:
        sup = recode_core.sku_supports(transactions, [m.old_code, m.new_code])
        both = sum(1 for basket, _ in transactions if m.old_code in basket and m.new_code in basket)
        supports[m.old_code] = {"old": sup[m.old_code], "new": sup[m.new_code], "both": both}

    # 并入组（同一新码可能并入多个旧码）：核对用并集，不能逐对加减
    groups: dict[str, list[str]] = {}
    for m in mappings:
        groups.setdefault(m.new_code, []).append(m.old_code)
    group_rows = []
    for new, olds in sorted(groups.items()):
        merged = sum(
            1 for basket, _ in transactions if ({new} | set(olds)) & basket
        )
        group_rows.append({"new_code": new, "old_codes": olds, "merged_support_before": merged})

    latest = mining_service.latest_run(db)
    latest_rules: list[dict] = []
    if latest is not None:
        old_codes = set(full_mapping)
        rows = list(
            db.execute(select(RuleCandidate).where(RuleCandidate.run_id == latest.id)).scalars()
        )
        latest_rules = [
            {"antecedent": row.antecedent, "consequent": row.consequent}
            for row in rows
            if old_codes & set(row.antecedent or []) or old_codes & set(row.consequent or [])
        ]
    return {
        "taken_at": _now().isoformat(),
        "baskets": basket_count,
        "lines": int(lines_total),
        "skus_active": skus_active,
        "supports": supports,
        "groups": group_rows,
        "creates_pending": [
            m.new_code for m in mappings if m.create_sku and m.new_code not in sku_codes
        ],
        "latest_rule_refs": latest_rules,
        "rules_projection": recode_core.project_rules(latest_rules, transactions, full_mapping),
    }


def _apply_mapping(db: Session, plan: SkuRecodePlan, mapping: SkuRecodeMapping) -> None:
    """单条映射的原子提交单元：新码落主数据 → 小票改写 → 别名 → 旧码停用 → 计数。

    调用方负责 commit；任何异常都会整体回滚本条映射（不会出现半条映射）。
    """
    old, new = mapping.old_code, mapping.new_code

    if mapping.create_sku:
        existing = db.execute(select(Sku).where(Sku.code == new)).scalar_one_or_none()
        if existing is None:
            spec = mapping.create_sku
            db.add(
                Sku(
                    code=new,
                    name=spec["name"],
                    category=spec["category"],
                    price=spec["price"],
                    unit=spec.get("unit") or "件",
                    shelf_hint=spec.get("shelf_hint") or "",
                    status=SkuStatus.ACTIVE.value,
                )
            )
            db.flush()

    # 小票改写：旧码行 → 新码（orig_sku 保留原商品编号）；只碰含旧码的小票
    rows = db.execute(select(OrderBasket.id, OrderBasket.lines)).all()
    affected_ids = [
        row_id for row_id, lines in rows if any(line.get("sku") == old for line in lines)
    ]
    lines_changed = 0
    if affected_ids:
        baskets = list(
            db.execute(select(OrderBasket).where(OrderBasket.id.in_(affected_ids))).scalars()
        )
        for basket in baskets:
            new_lines, changed = recode_core.remap_lines(basket.lines, {old: new})
            if changed:
                basket.lines = new_lines
                lines_changed += changed
        db.flush()

    alias = db.execute(select(SkuAlias).where(SkuAlias.old_code == old)).scalar_one_or_none()
    if alias is None:
        db.add(SkuAlias(old_code=old, new_code=new, plan_id=plan.id))
    elif alias.new_code != new:
        raise RuntimeError(f"{old} 已存在指向 {alias.new_code} 的别名，与方案目标 {new} 冲突")

    sku = db.execute(select(Sku).where(Sku.code == old)).scalar_one_or_none()
    if sku is None:
        raise RuntimeError(f"旧码 {old} 主数据缺失，无法停用")
    if sku.status == SkuStatus.ACTIVE.value:
        sku.status = SkuStatus.DEPRECATED.value
        sku.successor_code = new
    elif sku.successor_code != new:
        raise RuntimeError(f"旧码 {old} 已停用并指向 {sku.successor_code}，与方案目标 {new} 冲突")

    mapping.status = RecodeMappingStatus.APPLIED.value
    mapping.applied_baskets = len(affected_ids)
    mapping.applied_lines = lines_changed
    mapping.applied_at = _now()

    checkpoint = dict(plan.checkpoint or {})
    applied = list(checkpoint.get("applied", []))
    if old not in applied:
        applied.append(old)
    checkpoint["applied"] = applied
    plan.checkpoint = checkpoint
    db.flush()


def _reconcile(db: Session, plan: SkuRecodePlan) -> None:
    """迁移后核对：守恒校验全部通过才允许 succeeded，否则抛错置失败。"""
    mappings = _mappings(db, plan.id)
    pending = [m.old_code for m in mappings if m.status != RecodeMappingStatus.APPLIED.value]
    if pending:
        raise RuntimeError(f"存在未执行的映射：{'、'.join(pending)}")
    before = (plan.checkpoint or {}).get("before")
    if not before:
        raise RuntimeError("缺少迁移前快照，无法核对")

    full_mapping = {m.old_code: m.new_code for m in mappings}
    transactions = basket_service.load_transactions(db)
    baskets_after = db.execute(select(func.count()).select_from(OrderBasket)).scalar_one()
    lines_after = int(
        db.execute(select(func.coalesce(func.sum(OrderBasket.item_count), 0))).scalar_one()
    )
    skus_active_after = db.execute(
        select(func.count()).select_from(Sku).where(Sku.status == SkuStatus.ACTIVE.value)
    ).scalar_one()
    codes_after = {code for m in mappings for code in (m.old_code, m.new_code)}
    supports_after = recode_core.sku_supports(transactions, codes_after)

    mapping_rows = []
    for m in mappings:
        sup = before["supports"][m.old_code]
        mapping_rows.append(
            {
                "old_code": m.old_code,
                "new_code": m.new_code,
                "old_name": m.old_name,
                "new_name": m.new_name,
                "old_support_before": sup["old"],
                "old_support_after": supports_after[m.old_code],
                "new_support_before": sup["new"],
                "new_support_after": supports_after[m.new_code],
                "both_support_before": sup["both"],
                "baskets_rewritten": m.applied_baskets,
                "lines_rewritten": m.applied_lines,
            }
        )
    groups = [
        {**group, "new_support_after": supports_after[group["new_code"]]}
        for group in before["groups"]
    ]

    # 规则结果对照：before 取迁移前快照，after 在迁移后小票上按新身份重算
    fresh = recode_core.project_rules(before["latest_rule_refs"], transactions, full_mapping)
    rules_result = [
        {
            "rule_key_before": old_row["rule_key_before"],
            "rule_key_after": old_row["rule_key_after"],
            "before": old_row["before"],
            "after": fresh_row["after"],
        }
        for old_row, fresh_row in zip(before["rules_projection"], fresh)
    ]

    # 保留物核对：历史规则 / 已发布建议位 / 复核理由 / 原商品编号全部原样保留
    affected = _affected_rules(db, set(full_mapping))
    affected_ids = [row.id for row in affected]
    slots = []
    reviews_total = 0
    if affected_ids:
        slots = list(
            db.execute(select(PlanogramSlot).where(PlanogramSlot.rule_id.in_(affected_ids))).scalars()
        )
        reviews_total = db.execute(
            select(func.count()).select_from(RuleReview).where(RuleReview.rule_id.in_(affected_ids))
        ).scalar_one()
    aliases = list(db.execute(select(SkuAlias).where(SkuAlias.plan_id == plan.id)).scalars())

    snapshot = {
        "taken_at": _now().isoformat(),
        "baskets_before": before["baskets"],
        "baskets_after": baskets_after,
        "lines_before": before["lines"],
        "lines_after": lines_after,
        "skus_active_before": before["skus_active"],
        "skus_active_after": skus_active_after,
        "skus_deprecated": len(mappings),
        "skus_created": len(before["creates_pending"]),
        "mappings": mapping_rows,
        "groups": groups,
        "rules": rules_result,
        "preserved": {
            "rules": len(affected_ids),
            "slots": len(slots),
            "published_slots": sum(
                1 for slot in slots if slot.status == SlotStatus.PUBLISHED.value
            ),
            "reviews": reviews_total,
            "aliases": [
                {"old_code": row.old_code, "new_code": row.new_code} for row in aliases
            ],
        },
    }
    checks = recode_core.reconciliation_checks(snapshot)
    snapshot["checks"] = checks
    failed = [check for check in checks if not check["ok"]]
    if failed:
        detail = "; ".join(f"{check['name']}: {check['detail']}" for check in failed)
        raise RuntimeError(f"迁移核对未通过（{len(failed)} 项）：{detail}")

    plan.result = snapshot
    plan.status = RecodeStatus.SUCCEEDED.value
    plan.finished_at = _now()
    checkpoint = dict(plan.checkpoint or {})
    checkpoint["reconciled"] = True
    plan.checkpoint = checkpoint
    db.flush()


def execute_plan(db: Session, user: User, plan_id: str, trace_id: str = "") -> dict:
    plan = get_plan(db, plan_id)

    # 幂等：已完成的方案重跑直接返回原结果，不新增映射、不重复重算
    if plan.status == RecodeStatus.SUCCEEDED.value:
        return plan_detail(db, plan)
    if plan.status == RecodeStatus.RUNNING.value:
        raise AppError(codes.CONFLICT, "方案正在执行中，请稍后刷新", f"plan_code={plan.plan_code}")
    if plan.status == RecodeStatus.DRAFT.value:
        raise AppError(codes.CONFLICT, "请先生成预览再执行", f"plan_code={plan.plan_code}")

    mappings = _mappings(db, plan.id)
    applied = [m for m in mappings if m.status == RecodeMappingStatus.APPLIED.value]
    pending = [m for m in mappings if m.status != RecodeMappingStatus.APPLIED.value]

    # 执行前对当前主数据重跑对齐校验：未对齐 → 422 零写入（不出半套结果）。
    # pending 为空（全部映射已应用、仅核对未完成）时跳过校验，直接续跑核对。
    errors: list[str] = []
    if pending:
        sku_status = _sku_status_map(db)
        errors = recode_core.validate_mappings(
            [
                {"old_code": m.old_code, "new_code": m.new_code, "create_sku": bool(m.create_sku)}
                for m in pending
            ],
            sku_status,
        )
    aliases = {
        row.old_code: row.new_code
        for row in db.execute(select(SkuAlias.old_code, SkuAlias.new_code)).all()
    }
    for m in applied:
        if aliases.get(m.old_code) != m.new_code:
            errors.append(f"{m.old_code}: 已应用但别名缺失或指向他码（续跑不安全）")
    if errors:
        raise AppError(
            codes.VALIDATION_ERROR,
            "新旧身份未对齐，未执行任何写入",
            "; ".join(errors),
            extra={"errors": errors},
        )

    # 抢占执行权（预览态/失败态 → 执行中），并发重跑只有一路能进入
    claimed = db.execute(
        update(SkuRecodePlan)
        .where(
            SkuRecodePlan.id == plan.id,
            SkuRecodePlan.status.in_([RecodeStatus.PREVIEWED.value, RecodeStatus.FAILED.value]),
        )
        .values(status=RecodeStatus.RUNNING.value, started_at=_now(), error=None)
    )
    db.commit()
    if claimed.rowcount == 0:
        raise AppError(codes.CONFLICT, "方案状态已变化，请刷新后重试", f"plan_code={plan.plan_code}")
    db.refresh(plan)

    # 迁移前快照只取一次；续跑复用（否则基线已被部分迁移污染）
    if not (plan.checkpoint or {}).get("before"):
        checkpoint = dict(plan.checkpoint or {})
        checkpoint["before"] = _snapshot_before(db, mappings)
        checkpoint["applied"] = [m.old_code for m in applied]
        checkpoint["reconciled"] = False
        plan.checkpoint = checkpoint
        db.commit()

    try:
        for mapping in pending:
            _apply_mapping(db, plan, mapping)
            db.commit()  # 每条映射一个断点：提交后才推进 checkpoint
        if not (plan.checkpoint or {}).get("reconciled"):
            _reconcile(db, plan)
            audit_service.record(
                db,
                action=ACTION_RECODE_EXECUTE,
                actor=user,
                entity_type="sku_recode_plan",
                entity_id=plan.plan_code,
                detail={
                    "plan_code": plan.plan_code,
                    "mappings": len(mappings),
                    "baskets": plan.result.get("baskets_after"),
                    "outcome": "succeeded",
                },
                trace_id=trace_id,
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001 - 失败落方案状态，续跑从断点继续
        logger.error("recode plan %s failed: %s", plan.plan_code, exc, exc_info=True)
        db.rollback()
        db.refresh(plan)
        plan.status = RecodeStatus.FAILED.value
        plan.error = str(exc)[:800]
        audit_service.record(
            db,
            action=ACTION_RECODE_EXECUTE,
            actor=user,
            entity_type="sku_recode_plan",
            entity_id=plan.plan_code,
            detail={"plan_code": plan.plan_code, "outcome": "failed", "error": str(exc)[:200]},
            trace_id=trace_id,
        )
        db.commit()

    logger.info("recode plan %s execute done status=%s", plan.plan_code, plan.status)
    return plan_detail(db, plan)
