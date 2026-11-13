"""换码方案请求模型。"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class RecodeNewSkuInput(BaseModel):
    """方案声明创建的新码主数据（新码尚不存在时必填）。"""

    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=40)
    price: Decimal = Field(gt=0, le=999999)
    unit: str = Field(default="件", max_length=16)
    shelf_hint: str = Field(default="", max_length=80)


class RecodeMappingInput(BaseModel):
    old_code: str = Field(min_length=1, max_length=24)
    new_code: str = Field(min_length=1, max_length=24)
    create_sku: RecodeNewSkuInput | None = None


class RecodePlanCreateRequest(BaseModel):
    plan_code: str | None = Field(default=None, max_length=40)
    title: str = Field(default="", max_length=120)
    mappings: list[RecodeMappingInput] = Field(min_length=1, max_length=20)
