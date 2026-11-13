"""换码迁移核心口径：对齐校验 / 行改写幂等 / 身份合并 / 规则对照 / 核对不变量。

纯函数测试（不碰数据库），与 test_invariants 同一约定。
"""
from __future__ import annotations

import pytest

from src.services.recode_core import (
    project_rules,
    reconciliation_checks,
    remap_lines,
    remap_transactions,
    rule_key_of,
    rule_metrics,
    sku_supports,
    translate_items,
    translate_rule_key,
    validate_mappings,
)

SKU_STATUS = {
    "N01": "active",
    "N02": "active",
    "N09": "active",
    "N12": "active",
    "OLD1": "deprecated",
    "OLD2": "deprecated",
}

MAPPING = {"N02": "N12", "N09": "N13"}


# ---------------------------------------------------------------- 对齐校验 ----


def test_validate_accepts_aligned_plan() -> None:
    errors = validate_mappings(
        [
            {"old_code": "N02", "new_code": "N12", "create_sku": False},
            {"old_code": "N09", "new_code": "N13", "create_sku": True},
        ],
        SKU_STATUS,
    )
    assert errors == []


def test_validate_rejects_misaligned_identities() -> None:
    errors = validate_mappings(
        [
            {"old_code": "NOPE", "new_code": "N12", "create_sku": False},   # 旧码不存在
            {"old_code": "OLD1", "new_code": "N12", "create_sku": False},   # 旧码已停用
            {"old_code": "N02", "new_code": "OLD2", "create_sku": False},   # 新码已停用
            {"old_code": "N09", "new_code": "N09", "create_sku": False},    # 自映射
            {"old_code": "N01", "new_code": "ZZZ", "create_sku": False},    # 新码缺失且未声明创建
        ],
        SKU_STATUS,
    )
    assert len(errors) == 5
    assert any("不存在" in e for e in errors)
    assert any("已停用，不能重复换码" in e for e in errors)
    assert any("不能作为并入目标" in e for e in errors)
    assert any("相同" in e for e in errors)
    assert any("未声明创建" in e for e in errors)


def test_validate_rejects_duplicates_and_chains() -> None:
    errors = validate_mappings(
        [
            {"old_code": "N02", "new_code": "N09", "create_sku": False},
            {"old_code": "N09", "new_code": "N12", "create_sku": False},   # 链式 N02→N09→N12
            {"old_code": "N02", "new_code": "N12", "create_sku": False},   # 旧码重复
        ],
        SKU_STATUS,
    )
    assert any("重复" in e for e in errors)
    assert any("链式换码" in e for e in errors)


def test_validate_allows_many_old_codes_into_one_new() -> None:
    """并入：多个旧码可以并入同一个新码（不是链式）。"""
    errors = validate_mappings(
        [
            {"old_code": "N02", "new_code": "N12", "create_sku": False},
            {"old_code": "N09", "new_code": "N12", "create_sku": False},
        ],
        SKU_STATUS,
    )
    assert errors == []


# ---------------------------------------------------------------- 行改写 ----


def test_remap_lines_rewrites_and_preserves_original_code() -> None:
    lines = [
        {"sku": "N01", "qty": 1, "amount": "15.72"},
        {"sku": "N02", "qty": 2, "amount": "14.28"},
        {"sku": "N09", "qty": 1, "amount": "11.91"},
    ]
    new_lines, changed = remap_lines(lines, MAPPING)

    assert changed == 2
    assert new_lines[0] is lines[0]  # 未触及的行原样保留（同一对象）
    assert new_lines[1]["sku"] == "N12" and new_lines[1]["orig_sku"] == "N02"
    assert new_lines[2]["sku"] == "N13" and new_lines[2]["orig_sku"] == "N09"
    assert lines[1]["sku"] == "N02"  # 入参不被修改


def test_remap_lines_is_idempotent() -> None:
    lines = [{"sku": "N12", "qty": 1, "amount": "7.94", "orig_sku": "N02"}]
    new_lines, changed = remap_lines(lines, MAPPING)
    assert changed == 0
    assert new_lines[0] is lines[0]


def test_remap_lines_keeps_earliest_original_code_on_chained_recode() -> None:
    """链式换码（跨方案 N02→N12→N15）：行上保留最早的原商品编号 N02。"""
    lines = [{"sku": "N12", "qty": 1, "amount": "7.94", "orig_sku": "N02"}]
    new_lines, changed = remap_lines(lines, {"N12": "N15"})
    assert changed == 1
    assert new_lines[0]["sku"] == "N15"
    assert new_lines[0]["orig_sku"] == "N02"


# ---------------------------------------------------------------- 身份合并 ----


def _tx(*baskets: set[str]) -> list[tuple[frozenset[str], str]]:
    return [(frozenset(b), "high") for b in baskets]


def test_remap_transactions_merges_identities_with_union_semantics() -> None:
    transactions = _tx(
        {"N01", "N02"},          # 只含旧码
        {"N01", "N12"},          # 只含新码
        {"N02", "N12", "N01"},   # 新旧同票 → 合并后只计一次
        {"N09"},                 # 另一条映射
    )
    remapped = remap_transactions(transactions, MAPPING)

    assert remapped[0][0] == frozenset({"N01", "N12"})
    assert remapped[2][0] == frozenset({"N01", "N12"})  # 新旧合并为一个身份
    supports = sku_supports(remapped, ["N12", "N13", "N02", "N09"])
    assert supports["N12"] == 3      # 并集：1 + 1 + 1（同票不双计）
    assert supports["N13"] == 1
    assert supports["N02"] == 0      # 旧码归零
    assert supports["N09"] == 0
    assert len(remapped) == len(transactions)  # 小票数守恒


def test_translate_items_and_rule_key() -> None:
    assert translate_items(["N02", "N01"], MAPPING) == ["N01", "N12"]
    assert translate_items(["N02", "N09"], MAPPING) == ["N12", "N13"]
    assert translate_rule_key("N01>N02", MAPPING) == "N01>N12"
    assert translate_rule_key("RUN-1@N01>N02", MAPPING) == "RUN-1@N01>N12"
    assert translate_rule_key("N02+N09>N01", MAPPING) == "N12+N13>N01"
    assert rule_key_of(["B", "A"], ["C"]) == "A+B>C"


# ---------------------------------------------------------------- 规则对照 ----


def test_project_rules_rename_keeps_metrics() -> None:
    """纯换名（1:1 无重叠）：迁移前后 lift / support 完全一致。"""
    transactions = _tx(
        {"N01", "N02"}, {"N01", "N02"}, {"N01"}, {"N02"}, {"N01"}, {"N09"},
    )
    rules = [{"antecedent": ["N01"], "consequent": ["N02"]}]
    projection = project_rules(rules, transactions, {"N02": "N12"})

    assert projection[0]["rule_key_before"] == "N01>N02"
    assert projection[0]["rule_key_after"] == "N01>N12"
    assert projection[0]["before"] == projection[0]["after"]
    assert projection[0]["before"]["cooccur_count"] == 2


def test_project_rules_merge_changes_support_by_union() -> None:
    transactions = _tx({"A", "X"}, {"B", "X"}, {"A", "B", "X"}, {"X"})
    # A→M、B→M 并入同一新码：合并后 support(M) = |A∪B| = 3
    projection = project_rules(
        [{"antecedent": ["A"], "consequent": ["X"]}],
        transactions,
        {"A": "M", "B": "M"},
    )
    before = projection[0]["before"]
    after = projection[0]["after"]
    assert before["cooccur_count"] == 2          # A∩X
    assert after["cooccur_count"] == 3           # (A∪B)∩X
    assert after["support"] == pytest.approx(3 / 4, abs=1e-6)
    assert projection[0]["rule_key_after"] == "M>X"


def test_rule_metrics_matches_apriori_convention() -> None:
    transactions = _tx({"A", "B"}, {"A", "B"}, {"A"}, {"B"}, {"A"}, {"C"})
    metrics = rule_metrics(transactions, ["A"], ["B"])
    assert metrics["cooccur_count"] == 2
    assert metrics["support"] == pytest.approx(2 / 6, abs=1e-6)
    assert metrics["confidence"] == pytest.approx(2 / 4, abs=1e-6)
    assert metrics["lift"] == pytest.approx((2 / 4) / (3 / 6), abs=1e-4)


# ---------------------------------------------------------------- 核对 ----


def _snapshot(**overrides) -> dict:
    base = {
        "baskets_before": 3000,
        "baskets_after": 3000,
        "lines_before": 9600,
        "lines_after": 9600,
        "skus_active_before": 40,
        "skus_active_after": 40,
        "skus_deprecated": 2,
        "skus_created": 2,
        "mappings": [
            {"old_code": "N02", "new_code": "N12", "old_support_before": 407, "old_support_after": 0},
            {"old_code": "N09", "new_code": "N13", "old_support_before": 208, "old_support_after": 0},
        ],
        "groups": [
            {"new_code": "N12", "old_codes": ["N02"], "merged_support_before": 407, "new_support_after": 407},
            {"new_code": "N13", "old_codes": ["N09"], "merged_support_before": 208, "new_support_after": 208},
        ],
    }
    base.update(overrides)
    return base


def test_reconciliation_checks_pass_on_conserved_snapshot() -> None:
    checks = reconciliation_checks(_snapshot())
    assert checks and all(check["ok"] for check in checks)


def test_reconciliation_checks_catch_half_applied_state() -> None:
    """半套结果必须被卡住：旧码未归零 / 新码并集不符 / 小票数漂移。"""
    bad = _snapshot(
        baskets_after=2999,
        skus_active_after=39,
        mappings=[
            {"old_code": "N02", "new_code": "N12", "old_support_before": 407, "old_support_after": 12},
            {"old_code": "N09", "new_code": "N13", "old_support_before": 208, "old_support_after": 0},
        ],
        groups=[
            {"new_code": "N12", "old_codes": ["N02"], "merged_support_before": 407, "new_support_after": 395},
            {"new_code": "N13", "old_codes": ["N09"], "merged_support_before": 208, "new_support_after": 208},
        ],
    )
    checks = reconciliation_checks(bad)
    failed = {check["name"] for check in checks if not check["ok"]}
    assert "baskets_conserved" in failed
    assert "sku_active_aligned" in failed
    assert "old_code_retired:N02" in failed
    assert "new_code_merged:N12" in failed
    assert "old_code_retired:N09" not in failed  # 已完成的部分不误报
