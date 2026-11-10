"""Proxy de captura (addon do mitmproxy).

O analista navega no app pelo proxy; cada troca é enviada à API do
scopehound (`POST /projects/{id}/traffic`), que guarda só o que está no
escopo do projeto. Funciona igual com a API local ou remota.

O proxy só escuta em 127.0.0.1. Ele não é usado pelo agente: o agente fala
com a rede apenas pelo egress.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .model import MAX_BODY_CHARS, ExchangeIn

log = logging.getLogger(__name__)


def flow_to_exchange(flow: Any) -> ExchangeIn | None:
    request = flow.request
    if request.method == "CONNECT":
        return None
    response = flow.response
    elapsed = None
    if response is not None and response.timestamp_end and request.timestamp_start:
        elapsed = (response.timestamp_end - request.timestamp_start) * 1000
    return ExchangeIn(
        method=request.method,
        url=request.pretty_url,
        request_headers=[(k, v) for k, v in request.headers.items(multi=True)],
        request_body=(request.get_text(strict=False) or "")[:MAX_BODY_CHARS],
        status=response.status_code if response is not None else None,
        response_headers=(
            [(k, v) for k, v in response.headers.items(multi=True)] if response else []
        ),
        response_body=(
            (response.get_text(strict=False) or "")[:MAX_BODY_CHARS] if response else ""
        ),
        elapsed_ms=elapsed,
    )


class CaptureAddon:
    def __init__(
        self,
        api_url: str,
        project_id: str,
        *,
        batch_size: int = 20,
        flush_interval: float = 2.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = f"{api_url.rstrip('/')}/projects/{project_id}/traffic"
        self.api_host = httpx.URL(api_url).host
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.pending: list[dict[str, Any]] = []
        self.stored = 0
        self.skipped = 0
        self._client = client or httpx.AsyncClient(timeout=10, trust_env=False)
        self._lock = asyncio.Lock()
        self._ticker: asyncio.Task[None] | None = None

    def running(self) -> None:
        self._ticker = asyncio.get_running_loop().create_task(self._tick())

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval)
            await self.flush()

    async def response(self, flow: Any) -> None:
        await self._capture(flow)

    async def error(self, flow: Any) -> None:
        if flow.response is None:
            await self._capture(flow)

    async def _capture(self, flow: Any) -> None:
        exchange = flow_to_exchange(flow)
        if exchange is None:
            return
        self.pending.append(exchange.to_json())
        if len(self.pending) >= self.batch_size:
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            if not self.pending:
                return
            batch, self.pending = self.pending, []
            try:
                response = await self._client.post(self.endpoint, json={"exchanges": batch})
                response.raise_for_status()
                data = response.json()
                self.stored += data["stored"]
                self.skipped += data["skipped_out_of_scope"]
            except httpx.HTTPError as exc:
                log.warning("scopehound: falha ao enviar %d trocas: %s", len(batch), exc)
                self.pending = batch + self.pending  # tenta de novo no próximo ciclo

    async def done(self) -> None:
        if self._ticker:
            self._ticker.cancel()
        await self.flush()
        await self._client.aclose()


async def run_proxy(api_url: str, project_id: str, port: int) -> None:
    from mitmproxy import options
    from mitmproxy.tools.dump import DumpMaster

    opts = options.Options(listen_host="127.0.0.1", listen_port=port)
    master = DumpMaster(opts, with_termlog=True, with_dumper=False)
    master.addons.add(CaptureAddon(api_url, project_id))
    await master.run()
