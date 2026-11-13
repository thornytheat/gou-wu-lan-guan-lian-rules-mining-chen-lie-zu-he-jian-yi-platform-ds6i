"""商品换码（主数据迁移）：方案 / 映射 / 旧码别名 三表。

设计口径：
  SkuRecodePlan    一次换码方案（可预览、可执行、可续跑）；preview/result/checkpoint 全是快照
  SkuRecodeMapping 方案内一条旧码 → 新码映射（执行断点的最小粒度，重跑不新增）
  SkuAlias         旧码 → 新码别名（原商品编号永久保留；后续挖掘按新身份合并统计）
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.config.settings import settings
from src.models.base import Base, TimestampMixin, new_uuid, utcnow


class SkuRecodePlan(Base, TimestampMixin):
    __tablename__ = "sku_recode_plans"
    __table_args__ = {"schema": settings.db_schema}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    plan_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    mappings_input: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    preview: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.users.id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SkuRecodeMapping(Base, TimestampMixin):
    __tablename__ = "sku_recode_mappings"
    __table_args__ = (
        UniqueConstraint("plan_id", "old_code", name="uq_recode_mapping_plan_old"),
        {"schema": settings.db_schema},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.sku_recode_plans.id"), nullable=False, index=True
    )
    old_code: Mapped[str] = mapped_column(String(24), nullable=False)
    new_code: Mapped[str] = mapped_column(String(24), nullable=False)
    create_sku: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    old_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    new_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    affected_baskets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affected_rules: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affected_slots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applied_baskets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applied_lines: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SkuAlias(Base, TimestampMixin):
    __tablename__ = "sku_aliases"
    __table_args__ = {"schema": settings.db_schema}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    old_code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    new_code: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{settings.db_schema}.sku_recode_plans.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
