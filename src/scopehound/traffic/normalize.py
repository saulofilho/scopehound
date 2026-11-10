"""Normalização de paths e extração de parâmetros para o site map."""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from .model import Headers, header

_NUMERIC = re.compile(r"^\d+$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HEX = re.compile(r"^[0-9a-f]{16,}$", re.I)
_TOKEN = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9_\-]{20,}$")


def segment_kind(segment: str) -> str | None:
    if _NUMERIC.match(segment):
        return "id"
    if _UUID.match(segment):
        return "uuid"
    if _HEX.match(segment):
        return "hash"
    if _TOKEN.match(segment):
        return "token"
    return None


def path_template(path: str) -> str:
    """`/api/Users/12/orders` → `/api/Users/{id}/orders`."""
    parts = []
    for segment in path.split("/"):
        kind = segment_kind(segment)
        parts.append(f"{{{kind}}}" if kind else segment)
    return "/".join(parts) or "/"


@dataclass(frozen=True)
class Param:
    name: str
    location: str  # path | query | form | json | cookie
    value: str


def _is_numeric(value: str) -> bool:
    return bool(_NUMERIC.match(value.strip()))


def _json_params(data: object, prefix: str = "", depth: int = 0) -> list[Param]:
    out: list[Param] = []
    if depth > 2:
        return out
    if isinstance(data, dict):
        for key, value in data.items():
            name = f"{prefix}{key}"
            if isinstance(value, dict | list):
                out += _json_params(value, f"{name}.", depth + 1)
            else:
                out.append(Param(name, "json", "" if value is None else str(value)))
    elif isinstance(data, list) and data:
        out += _json_params(data[0], f"{prefix}[].", depth + 1)
    return out


def extract_params(url: str, headers: Headers, body: str) -> list[Param]:
    split = urlsplit(url)
    params: list[Param] = []
    for index, segment in enumerate(split.path.split("/")):
        kind = segment_kind(segment)
        if kind:
            params.append(Param(f"{{{kind}}}#{index}", "path", segment))
    params += [Param(k, "query", v) for k, v in parse_qsl(split.query, keep_blank_values=True)]
    content_type = header(headers, "content-type").lower()
    if body:
        if "json" in content_type or body.lstrip().startswith(("{", "[")):
            with contextlib.suppress(ValueError):
                params += _json_params(json.loads(body))
        elif "x-www-form-urlencoded" in content_type:
            params += [Param(k, "form", v) for k, v in parse_qsl(body, keep_blank_values=True)]
    cookie = header(headers, "cookie")
    for pair in cookie.split(";"):
        if "=" in pair:
            name = pair.split("=", 1)[0].strip()
            params.append(Param(name, "cookie", ""))
    return params


def is_numeric_param(param: Param) -> bool:
    return _is_numeric(param.value)
