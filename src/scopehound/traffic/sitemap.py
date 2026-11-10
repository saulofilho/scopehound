"""Site map: host → path (normalizado) → método, com parâmetros observados."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .normalize import extract_params, is_numeric_param, path_template


@dataclass
class ParamInfo:
    name: str
    location: str
    numeric: bool = True
    examples: list[str] = field(default_factory=list)

    def observe(self, value: str, numeric: bool) -> None:
        self.numeric = self.numeric and numeric
        if value and value not in self.examples and len(self.examples) < 3:
            self.examples.append(value[:60])


@dataclass
class Endpoint:
    method: str
    template: str
    count: int = 0
    statuses: set[int] = field(default_factory=set)
    params: dict[tuple[str, str], ParamInfo] = field(default_factory=dict)
    sample_id: str = ""

    @property
    def numeric_params(self) -> list[ParamInfo]:
        return [p for p in self.params.values() if p.numeric and p.location != "cookie"]

    def to_json(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.template,
            "count": self.count,
            "statuses": sorted(self.statuses),
            "sample_id": self.sample_id,
            "params": [
                {
                    "name": p.name,
                    "location": p.location,
                    "numeric": p.numeric,
                    "examples": p.examples,
                }
                for p in self.params.values()
            ],
        }


def build_sitemap(rows: Iterable[Any], host: str | None = None) -> dict[str, list[Endpoint]]:
    """Agrupa trocas (linhas `Exchange`) por origem e endpoint."""
    hosts: dict[str, dict[tuple[str, str], Endpoint]] = {}
    for row in rows:
        if host and row.host != host:
            continue
        default_port = {"http": 80, "https": 443}.get(row.scheme)
        origin = f"{row.scheme}://{row.host}" + ("" if row.port == default_port else f":{row.port}")
        template = path_template(row.path)
        key = (row.method, template)
        endpoint = hosts.setdefault(origin, {}).get(key)
        if endpoint is None:
            endpoint = hosts[origin][key] = Endpoint(row.method, template, sample_id=row.id)
        endpoint.count += 1
        if row.status is not None:
            endpoint.statuses.add(row.status)
        url = row.url
        for param in extract_params(url, row.request_headers or [], row.request_body or ""):
            info = endpoint.params.get((param.name, param.location))
            if info is None:
                info = endpoint.params[(param.name, param.location)] = ParamInfo(
                    param.name, param.location
                )
            info.observe(param.value, is_numeric_param(param))
    return {
        origin: sorted(endpoints.values(), key=lambda e: (e.template, e.method))
        for origin, endpoints in sorted(hosts.items())
    }


def render_sitemap(sitemap: dict[str, list[Endpoint]], max_endpoints: int = 300) -> str:
    """Texto compacto para o modelo e para o terminal."""
    if not sitemap:
        return "(site map vazio: nenhum tráfego no projeto)"
    lines: list[str] = []
    shown = 0
    for origin, endpoints in sitemap.items():
        lines.append(origin)
        for e in endpoints:
            if shown >= max_endpoints:
                lines.append(f"… (+{sum(len(v) for v in sitemap.values()) - shown} endpoints)")
                return "\n".join(lines)
            shown += 1
            statuses = ",".join(str(s) for s in sorted(e.statuses)) or "-"
            params = ", ".join(
                f"{p.name}[{p.location}{'#num' if p.numeric and p.examples else ''}]"
                for p in e.params.values()
            )
            lines.append(
                f"  {e.method:7} {e.template}  ×{e.count} [{statuses}] ex:{e.sample_id[:12]}"
                + (f"\n          params: {params}" if params else "")
            )
    return "\n".join(lines)
