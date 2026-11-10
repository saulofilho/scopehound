from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.messages import BaseMessage

from ..secrets import mask


def message_dict(m: BaseMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"id": m.id, "role": m.type, "content": m.content}
    if getattr(m, "tool_calls", None):
        out["tool_calls"] = [
            {"id": c["id"], "name": c["name"], "args": c["args"]} for c in m.tool_calls
        ]
    if m.type == "tool":
        out["tool_call_id"] = m.tool_call_id
        out["name"] = m.name
    return out


def row_dict(row: Any, *, exclude: set[str] = frozenset()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        if col.name in exclude:
            continue
        value = getattr(row, col.name)
        out[col.name] = value.isoformat() if isinstance(value, datetime) else value
    return out


def project_dict(p: Any) -> dict[str, Any]:
    out = row_dict(p, exclude={"llm_api_key_enc"})
    out["llm_api_key"] = mask("x" * 12) if p.llm_api_key_enc else None
    return out
