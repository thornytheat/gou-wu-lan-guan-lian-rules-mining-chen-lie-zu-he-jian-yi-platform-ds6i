"""换码迁移纯函数：对齐校验 / 小票行改写 / 身份合并投影 / 规则指标 / 核对不变量。

不 import Session、不碰数据库，全部可单测（与 mining_core / planogram_core 同一约定）。
recode_service 只做 DB 编排，口径全部落在这里：

  对齐校验：新旧身份未对齐（旧码不存在/已停用、新码缺失且未声明创建、链式换码、
            旧码重复、自映射、新码已停用）→ 全部错误一次返回，调用方不得写库。
  行改写：  line.sku 旧→新，原商品编号保留在 line.orig_sku；幂等（再跑无变化）。
  合并投影：同一张小票同时含新旧码时，合并后只计一次（frozenset 天然去重）。
  核对：    小票总数 / 明细行数守恒；旧码支持度归零；新码支持度 = 旧+新-交集；
            在售商品数 = 迁移前 - 停用数 + 新建数。
"""
from __future__ import annotations

from typing import Iterable, Sequence

# ---------------------------------------------------------------- 对齐校验 ----


def validate_mappings(mappings: Sequence[dict], sku_status: dict[str, str]) -> list[str]:
    """新旧身份对齐校验。mappings: [{old_code, new_code, create_sku: bool}]；
    sku_status: {code: status}（主数据全量）。返回错误列表，空 = 对齐。"""
    errors: list[str] = []
    if not mappings:
        return ["方案至少需要一条换码映射"]

    old_to_new: dict[str, str] = {}
    for item in mappings:
        old = str(item.get("old_code") or "").strip()
        new = str(item.get("new_code") or "").strip()
        creates = bool(item.get("create_sku"))
        if not old or not new:
            errors.append(f"映射缺少旧码或新码：{item!r}")
            continue
        if old == new:
            errors.append(f"{old}: 新旧编码相同，无需换码")
        if old in old_to_new:
            errors.append(f"{old}: 旧码在方案中重复出现（→ {old_to_new[old]} 与 → {new}）")
        old_to_new[old] = new

        old_status = sku_status.get(old)
        if old_status is None:
            errors.append(f"{old}: 旧码在主数据中不存在")
        elif old_status != "active":
            errors.append(f"{old}: 旧码已停用，不能重复换码")

        new_status = sku_status.get(new)
        if new_status is None and not creates:
            errors.append(f"{new}: 新码不存在且方案未声明创建（{old} → {new}）")
        elif new_status == "deprecated":
            errors.append(f"{new}: 新码已停用，不能作为并入目标（{old} → {new}）")

    # 链式换码：A→B 且 B→C，必须拍平成 A→C，否则执行顺序会改变结果。
    # 基于原始列表（重复旧码也不能掩盖链）；自映射已单独报错，不重复算链。
    all_olds = set(old_to_new)
    for item in mappings:
        old = str(item.get("old_code") or "").strip()
        new = str(item.get("new_code") or "").strip()
        if old and new and old != new and new in all_olds:
            errors.append(f"{old} → {new} 与 {new} → … 形成链式换码，请先拍平")
    # 去重（同一问题可能被多个映射触发）
    seen: set[str] = set()
    unique: list[str] = []
    for error in errors:
        if error not in seen:
            seen.add(error)
            unique.append(error)
    return unique


# ---------------------------------------------------------------- 行改写 ----


def remap_lines(lines: Sequence[dict], mapping: dict[str, str]) -> tuple[list[dict], int]:
    """把明细行里的旧码改写成新码；原商品编号保留在 orig_sku。

    返回 (新行列表, 改写行数)。幂等：不含旧码的行原样保留，重复调用改写数为 0。
    行上已有 orig_sku（更早的换码）时保留最早原码，不覆盖。
    """
    new_lines: list[dict] = []
    changed = 0
    for line in lines:
        code = line.get("sku")
        target = mapping.get(code)
        if target is None:
            new_lines.append(line)
            continue
        rewritten = dict(line)
        rewritten["sku"] = target
        rewritten["orig_sku"] = line.get("orig_sku") or code  # 原商品编号随小票永久保留
        new_lines.append(rewritten)
        changed += 1
    return new_lines, changed


def remap_code(code: str, mapping: dict[str, str]) -> str:
    return mapping.get(code, code)


def remap_transactions(
    transactions: Sequence[tuple[frozenset[str], str]], mapping: dict[str, str]
) -> list[tuple[frozenset[str], str]]:
    """把小票集合投影到合并后身份（同票含新旧码时只计一次）。"""
    return [
        (frozenset(mapping.get(code, code) for code in basket), tier)
        for basket, tier in transactions
    ]


def translate_items(items: Iterable[str], mapping: dict[str, str]) -> list[str]:
    return sorted({mapping.get(code, code) for code in items})


def rule_key_of(antecedent: Iterable[str], consequent: Iterable[str]) -> str:
    return f"{'+'.join(sorted(antecedent))}>{'+'.join(sorted(consequent))}"


def translate_rule_key(rule_key: str, mapping: dict[str, str]) -> str:
    """'N01>N02' → 'N01>N12'；带 run 前缀时只翻译最后一段。"""
    prefix, sep, tail = rule_key.rpartition("@")
    ante, _, cons = tail.partition(">")
    ante_t = translate_items(ante.split("+"), mapping) if ante else []
    cons_t = translate_items(cons.split("+"), mapping) if cons else []
    translated = rule_key_of(ante_t, cons_t)
    return f"{prefix}{sep}{translated}" if sep else translated


# ---------------------------------------------------------------- 规则指标 ----


def rule_metrics(
    transactions: Sequence[tuple[frozenset[str], str]],
    antecedent: Iterable[str],
    consequent: Iterable[str],
) -> dict:
    """轻量规则指标（与 apriori 口径一致：support/confidence/lift + 共现小票数）。"""
    ante = frozenset(antecedent)
    cons = frozenset(consequent)
    total = len(transactions)
    cooccur = sum(1 for basket, _ in transactions if ante <= basket and cons <= basket)
    ante_n = sum(1 for basket, _ in transactions if ante <= basket)
    cons_n = sum(1 for basket, _ in transactions if cons <= basket)
    support = cooccur / total if total else 0.0
    support_b = cons_n / total if total else 0.0
    confidence = cooccur / ante_n if ante_n else 0.0
    lift = confidence / support_b if support_b else 0.0
    return {
        "support": round(support, 6),
        "confidence": round(confidence, 6),
        "lift": round(lift, 4),
        "cooccur_count": cooccur,
    }


def project_rules(
    rules: Sequence[dict],
    transactions: Sequence[tuple[frozenset[str], str]],
    mapping: dict[str, str],
) -> list[dict]:
    """受影响规则的迁移前后对照：同一批小票，旧身份 vs 合并后身份各算一次。"""
    remapped = remap_transactions(transactions, mapping)
    out: list[dict] = []
    for rule in rules:
        ante_t = translate_items(rule["antecedent"], mapping)
        cons_t = translate_items(rule["consequent"], mapping)
        out.append(
            {
                "rule_key_before": rule_key_of(rule["antecedent"], rule["consequent"]),
                "rule_key_after": rule_key_of(ante_t, cons_t),
                "before": rule_metrics(transactions, rule["antecedent"], rule["consequent"]),
                "after": rule_metrics(remapped, ante_t, cons_t),
            }
        )
    return out


def sku_supports(
    transactions: Sequence[tuple[frozenset[str], str]], codes: Iterable[str]
) -> dict[str, int]:
    """一组商品码各自的小票支持计数。"""
    wanted = set(codes)
    counts = {code: 0 for code in wanted}
    for basket, _ in transactions:
        for code in wanted & basket:
            counts[code] += 1
    return counts


# ---------------------------------------------------------------- 核对 ----


def reconciliation_checks(snapshot: dict) -> list[dict]:
    """迁移前后核对（snapshot 结构见 recode_service.build_reconciliation）。

    任何一条不通过都说明出现了「半套结果」，调用方必须把方案置为失败。
    多个旧码并入同一新码时按「并入组」校验并集支持度（不能逐对加减）。
    """
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add(
        "baskets_conserved",
        snapshot["baskets_before"] == snapshot["baskets_after"],
        f"小票数 {snapshot['baskets_before']} → {snapshot['baskets_after']}",
    )
    add(
        "lines_conserved",
        snapshot["lines_before"] == snapshot["lines_after"],
        f"明细行数 {snapshot['lines_before']} → {snapshot['lines_after']}",
    )
    expected_active = (
        snapshot["skus_active_before"] - snapshot["skus_deprecated"] + snapshot["skus_created"]
    )
    add(
        "sku_active_aligned",
        snapshot["skus_active_after"] == expected_active,
        f"在售商品 {snapshot['skus_active_before']} → {snapshot['skus_active_after']}"
        f"（停用 {snapshot['skus_deprecated']} / 新建 {snapshot['skus_created']}）",
    )
    for row in snapshot["mappings"]:
        old = row["old_code"]
        add(
            f"old_code_retired:{old}",
            row["old_support_after"] == 0,
            f"{old} 支持度 {row['old_support_before']} → {row['old_support_after']}",
        )
    for group in snapshot["groups"]:
        new = group["new_code"]
        olds = "、".join(group["old_codes"])
        add(
            f"new_code_merged:{new}",
            group["new_support_after"] == group["merged_support_before"],
            f"{new} 支持度：迁移前 {olds} ∪ {new} 并集 {group['merged_support_before']}"
            f"（实际 {group['new_support_after']}）",
        )
    return checks
