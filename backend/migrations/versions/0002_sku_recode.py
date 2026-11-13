"""商品换码：skus 增加状态列 + 换码方案/映射/别名三表。

Revision ID: 0002_sku_recode
Revises: 0001_initial
Create Date: 2026-11-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_sku_recode"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

SCHEMA = "basketrule"


def upgrade() -> None:
    op.add_column(
        "skus",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        schema=SCHEMA,
    )
    op.add_column(
        "skus",
        sa.Column("successor_code", sa.String(24), nullable=False, server_default=""),
        schema=SCHEMA,
    )
    op.create_index("ix_skus_status", "skus", ["status"], schema=SCHEMA)

    op.create_table(
        "sku_recode_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_code", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("mappings_input", postgresql.JSONB(), nullable=False),
        sa.Column("preview", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("checkpoint", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_sku_recode_plans_status", "sku_recode_plans", ["status"], schema=SCHEMA)

    op.create_table(
        "sku_recode_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.sku_recode_plans.id"), nullable=False),
        sa.Column("old_code", sa.String(24), nullable=False),
        sa.Column("new_code", sa.String(24), nullable=False),
        sa.Column("create_sku", postgresql.JSONB(), nullable=True),
        sa.Column("old_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("new_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("affected_baskets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affected_rules", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affected_slots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied_baskets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied_lines", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plan_id", "old_code", name="uq_recode_mapping_plan_old"),
        schema=SCHEMA,
    )
    op.create_index("ix_sku_recode_mappings_plan", "sku_recode_mappings", ["plan_id"], schema=SCHEMA)
    op.create_index("ix_sku_recode_mappings_status", "sku_recode_mappings", ["status"], schema=SCHEMA)

    op.create_table(
        "sku_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("old_code", sa.String(24), nullable=False, unique=True),
        sa.Column("new_code", sa.String(24), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.sku_recode_plans.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_sku_aliases_new_code", "sku_aliases", ["new_code"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("sku_aliases", schema=SCHEMA)
    op.drop_table("sku_recode_mappings", schema=SCHEMA)
    op.drop_table("sku_recode_plans", schema=SCHEMA)
    op.drop_column("skus", "successor_code", schema=SCHEMA)
    op.drop_column("skus", "status", schema=SCHEMA)
