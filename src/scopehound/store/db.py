"""Conexão com o banco e migrações."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _sync_url(url: str) -> str:
    return url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", _sync_url(url))
    return cfg


def run_migrations(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = create_async_engine(url)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine.sync_engine, "connect")
            def _sqlite_pragmas(conn, _record):  # pragma: no cover - trivial
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()

        self.session = async_sessionmaker(self.engine, expire_on_commit=False)

    def __call__(self) -> AsyncSession:
        return self.session()

    async def dispose(self) -> None:
        await self.engine.dispose()
