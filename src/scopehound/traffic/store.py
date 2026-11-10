"""Persistência e consultas do histórico de tráfego de um projeto."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..guardrails import Scope, ScopeViolation, check_url
from ..store import Exchange
from .model import ExchangeIn, clip
from .sitemap import build_sitemap, render_sitemap

SITEMAP_ROW_LIMIT = 20_000


@dataclass
class IngestResult:
    stored: int
    skipped_out_of_scope: int
    ids: list[str]


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class TrafficStore:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        project_id: str,
        scope: Scope,
        task_id: str | None = None,
    ) -> None:
        self._session = session_factory
        self.project_id = project_id
        self.scope = scope
        self.task_id = task_id

    def _row(self, ex: ExchangeIn, source: str) -> Exchange | None:
        """Só guarda o que está no escopo: o proxy vê toda a navegação do analista."""
        try:
            target = check_url(self.scope, ex.url)
        except ScopeViolation:
            return None
        split = urlsplit(ex.url)
        return Exchange(
            project_id=self.project_id,
            task_id=self.task_id if source == "agent" else None,
            source=source,
            method=ex.method.upper()[:10],
            url=ex.url,
            scheme=target.scheme,
            host=target.host,
            port=target.port,
            path=split.path or "/",
            query=split.query,
            request_headers=[list(h) for h in ex.request_headers],
            request_body=clip(ex.request_body),
            status=ex.status,
            response_headers=[list(h) for h in ex.response_headers],
            response_body=clip(ex.response_body),
            response_size=len(ex.response_body.encode()),
            mime=ex.mime[:200],
            elapsed_ms=ex.elapsed_ms,
        )

    async def ingest(self, exchanges: Iterable[ExchangeIn], source: str) -> IngestResult:
        rows: list[Exchange] = []
        skipped = 0
        for ex in exchanges:
            row = self._row(ex, source)
            if row is None:
                skipped += 1
            else:
                rows.append(row)
        if rows:
            async with self._session() as session:
                session.add_all(rows)
                await session.commit()
        return IngestResult(len(rows), skipped, [r.id for r in rows])

    async def search(
        self,
        *,
        text: str = "",
        host: str = "",
        method: str = "",
        path_contains: str = "",
        status: int | None = None,
        param: str = "",
        source: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> list[Exchange]:
        query = select(Exchange).where(Exchange.project_id == self.project_id)
        if text:
            pattern = _like(text)
            query = query.where(
                or_(
                    Exchange.url.like(pattern, escape="\\"),
                    Exchange.request_body.like(pattern, escape="\\"),
                    Exchange.response_body.like(pattern, escape="\\"),
                )
            )
        if host:
            query = query.where(Exchange.host == host.lower())
        if method:
            query = query.where(Exchange.method == method.upper())
        if path_contains:
            query = query.where(Exchange.path.like(_like(path_contains), escape="\\"))
        if status is not None:
            query = query.where(Exchange.status == status)
        if param:
            query = query.where(
                or_(
                    Exchange.query.like(_like(f"{param}="), escape="\\"),
                    Exchange.request_body.like(_like(f'"{param}"'), escape="\\"),
                    Exchange.request_body.like(_like(f"{param}="), escape="\\"),
                )
            )
        if source:
            query = query.where(Exchange.source == source)
        query = query.order_by(Exchange.created_at.desc()).offset(offset).limit(min(limit, 500))
        async with self._session() as session:
            return list(await session.scalars(query))

    async def get(self, ref: str) -> Exchange | None:
        """Busca por id completo ou prefixo (mínimo 8 caracteres)."""
        if len(ref) < 8:
            return None
        async with self._session() as session:
            rows = list(
                await session.scalars(
                    select(Exchange)
                    .where(Exchange.project_id == self.project_id, Exchange.id.like(f"{ref}%"))
                    .limit(2)
                )
            )
        return rows[0] if len(rows) == 1 else None

    async def sitemap(self, host: str | None = None):
        async with self._session() as session:
            rows = await session.scalars(
                select(Exchange)
                .where(Exchange.project_id == self.project_id)
                .order_by(Exchange.created_at.desc())
                .limit(SITEMAP_ROW_LIMIT)
            )
            return build_sitemap(list(rows), host.lower() if host else None)

    async def sitemap_text(self, host: str | None = None) -> str:
        return render_sitemap(await self.sitemap(host))


def summarize(row: Exchange) -> str:
    return (
        f"{row.id[:12]}  {row.method:7} {row.url}  -> {row.status or '-'} "
        f"{row.response_size}B [{row.source}]"
    )


def render_exchange(row: Exchange, max_body: int = 4000) -> str:
    def headers(items) -> str:
        return "\n".join(f"{k}: {v}" for k, v in items)

    req_body = row.request_body[:max_body]
    res_body = row.response_body[:max_body]
    cut = " [truncado]" if len(row.response_body) > max_body else ""
    return (
        f"id {row.id} · origem {row.source}\n"
        f"{row.method} {row.url}\n{headers(row.request_headers)}\n\n{req_body}\n"
        f"--- resposta: {row.status or '(sem resposta)'} ---\n"
        f"{headers(row.response_headers)}\n\n{res_body}{cut}"
    )
