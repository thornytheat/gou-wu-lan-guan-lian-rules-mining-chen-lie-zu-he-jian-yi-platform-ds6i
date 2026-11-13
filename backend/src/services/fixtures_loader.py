"""把 scripts/fixtures.py 的规则元数据（分区 / 货架位 / 备注）暴露给服务层。

换码感知：商品只是换了码，货架分区跟着商品走 —— 传入 aliases（新码 → 旧码）时，
先按别名翻回旧身份再匹配 fixture，保证换码后的新批次仍命中同一套陈列元数据。
"""
from __future__ import annotations

from scripts import fixtures


def rule_meta(rule_key: str, aliases: dict[str, str] | None = None) -> dict:
    """rule_key 形如 'N01>N02' 或带 run 前缀，取最后一段匹配 fixture。"""
    tail = rule_key.split("@")[-1]
    for spec in fixtures.PAIR_BUNDLES:
        if spec["key"] == tail:
            return spec
    left, _, right = tail.partition(">")
    if aliases:
        left = aliases.get(left, left)
        right = aliases.get(right, right)
    for spec in fixtures.PAIR_BUNDLES:
        if {spec["left"], spec["right"]} == {left, right}:
            return spec
    return {}


def zone_payload(rule_key: str, aliases: dict[str, str] | None = None) -> dict:
    meta = rule_meta(rule_key, aliases)
    return {
        "zone": meta.get("zone", "未分配货架区"),
        "zone_code": meta.get("zone_code", ""),
        "shelf_label": meta.get("shelf_label", "待定货架位"),
        "note": meta.get("note", ""),
    }
