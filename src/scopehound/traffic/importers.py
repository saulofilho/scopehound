"""Importadores: HAR e XML de itens do Burp ("Save items")."""

from __future__ import annotations

import base64
import json

from defusedxml import ElementTree

from .model import ExchangeIn, Headers, clip


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def parse_har(text: str) -> list[ExchangeIn]:
    data = json.loads(text)
    out: list[ExchangeIn] = []
    for entry in data.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        res = entry.get("response", {})
        content = res.get("content", {}) or {}
        body = content.get("text") or ""
        if content.get("encoding") == "base64" and body:
            body = _decode(base64.b64decode(body))
        status = res.get("status")
        out.append(
            ExchangeIn(
                method=str(req.get("method", "GET")).upper(),
                url=req.get("url", ""),
                request_headers=[(h["name"], h["value"]) for h in req.get("headers", [])],
                request_body=clip((req.get("postData") or {}).get("text") or ""),
                status=status if status else None,  # HAR usa 0 para "sem resposta"
                response_headers=[(h["name"], h["value"]) for h in res.get("headers", [])],
                response_body=clip(body),
                elapsed_ms=entry.get("time"),
            )
        )
    return out


def parse_raw_http(raw: bytes) -> tuple[str, Headers, str]:
    """Divide uma mensagem HTTP crua em (linha inicial, cabeçalhos, corpo)."""
    for sep in (b"\r\n\r\n", b"\n\n"):
        if sep in raw:
            head, body = raw.split(sep, 1)
            break
    else:
        head, body = raw, b""
    lines = _decode(head).replace("\r\n", "\n").split("\n")
    headers: Headers = []
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers.append((name.strip(), value.strip()))
    return lines[0] if lines else "", headers, clip(_decode(body))


def _item_bytes(element) -> bytes:
    if element is None or element.text is None:
        return b""
    if element.get("base64") == "true":
        return base64.b64decode(element.text)
    return element.text.encode()


def parse_burp_xml(text: str) -> list[ExchangeIn]:
    # defusedxml: o XML do Burp traz um DTD interno; entidades externas são recusadas.
    root = ElementTree.fromstring(text, forbid_dtd=False)
    out: list[ExchangeIn] = []
    for item in root.iter("item"):
        url = (item.findtext("url") or "").strip()
        request_line, request_headers, request_body = parse_raw_http(
            _item_bytes(item.find("request"))
        )
        method = (item.findtext("method") or request_line.split(" ", 1)[0] or "GET").upper()
        raw_response = _item_bytes(item.find("response"))
        status: int | None = None
        response_headers: Headers = []
        response_body = ""
        if raw_response:
            status_line, response_headers, response_body = parse_raw_http(raw_response)
            parts = status_line.split(" ")
            if len(parts) > 1 and parts[1].isdigit():
                status = int(parts[1])
        out.append(
            ExchangeIn(
                method=method,
                url=url,
                request_headers=request_headers,
                request_body=request_body,
                status=status,
                response_headers=response_headers,
                response_body=response_body,
            )
        )
    return out


def detect_format(filename: str, text: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".har") or text.lstrip().startswith("{"):
        return "har"
    if lowered.endswith(".xml") or text.lstrip().startswith("<"):
        return "burp"
    raise ValueError("formato não reconhecido (use HAR ou XML do Burp)")


def parse_traffic(text: str, fmt: str) -> list[ExchangeIn]:
    if fmt == "har":
        return parse_har(text)
    if fmt == "burp":
        return parse_burp_xml(text)
    raise ValueError(f"formato inválido: {fmt}")
