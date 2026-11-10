from __future__ import annotations

from dataclasses import dataclass, field

MAX_BODY_CHARS = 256_000

Headers = list[tuple[str, str]]


def clip(text: str) -> str:
    return text if len(text) <= MAX_BODY_CHARS else text[:MAX_BODY_CHARS]


def header(headers: Headers, name: str) -> str:
    lname = name.lower()
    return next((v for k, v in headers if k.lower() == lname), "")


@dataclass
class ExchangeIn:
    """Troca HTTP normalizada, independente da origem (proxy, HAR, Burp, agente)."""

    method: str
    url: str
    request_headers: Headers = field(default_factory=list)
    request_body: str = ""
    status: int | None = None
    response_headers: Headers = field(default_factory=list)
    response_body: str = ""
    elapsed_ms: float | None = None

    @property
    def mime(self) -> str:
        return header(self.response_headers, "content-type").split(";")[0].strip().lower()

    def to_json(self) -> dict:
        return {
            "method": self.method,
            "url": self.url,
            "request_headers": [list(h) for h in self.request_headers],
            "request_body": self.request_body,
            "status": self.status,
            "response_headers": [list(h) for h in self.response_headers],
            "response_body": self.response_body,
            "elapsed_ms": self.elapsed_ms,
        }

    @classmethod
    def from_json(cls, data: dict) -> ExchangeIn:
        return cls(
            method=str(data["method"]).upper(),
            url=str(data["url"]),
            request_headers=[(str(k), str(v)) for k, v in data.get("request_headers", [])],
            request_body=str(data.get("request_body") or ""),
            status=data.get("status"),
            response_headers=[(str(k), str(v)) for k, v in data.get("response_headers", [])],
            response_body=str(data.get("response_body") or ""),
            elapsed_ms=data.get("elapsed_ms"),
        )
