"""建表引导：幂等 create_all（容器 entrypoint 第一步）。

demo 场景下用 SQLAlchemy metadata 建表，避免首次启动卡在迁移版本对齐；
正式环境可改用 `alembic upgrade head`（见 backend/migrations/）。

create_all 只建新表、不补列；对已有库用 ADD COLUMN IF NOT EXISTS 幂等补列
（换码迁移给 skus 加的 status / successor_code 走这条路）。
"""
from __future__ import annotations

from sqlalchemy import text

from src.config.database import engine
from src.models import Base

# 对已有库的幂等补列清单（新表由 create_all 负责，不在此列）
COLUMN_PATCHES = (
    "ALTER TABLE {schema}.skus ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active'",
    "ALTER TABLE {schema}.skus ADD COLUMN IF NOT EXISTS successor_code VARCHAR(24) NOT NULL DEFAULT ''",
)


def main() -> None:
    from src.config.settings import settings

    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.db_schema}"'))
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for patch in COLUMN_PATCHES:
            conn.execute(text(patch.format(schema=settings.db_schema)))
    print(f"[bootstrap] schema={settings.db_schema} tables={len(Base.metadata.tables)}", flush=True)


if __name__ == "__main__":
    main()
