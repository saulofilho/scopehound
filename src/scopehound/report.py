"""Relatórios: resumo e SARIF (para o modo CI)."""

from __future__ import annotations

import json
from typing import Any

SEVERITY_ORDER = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
# SARIF só tem error/warning/note/none
SARIF_LEVEL = {
    "CRITICAL": "error",
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "note",
    "INFO": "note",
}


def severity_at_least(severity: str, threshold: str) -> bool:
    try:
        return SEVERITY_ORDER.index(severity.upper()) >= SEVERITY_ORDER.index(threshold.upper())
    except ValueError:
        return False


def max_severity(leads: list[Any]) -> str | None:
    best = -1
    for lead in leads:
        try:
            best = max(best, SEVERITY_ORDER.index(lead.severity.upper()))
        except ValueError:
            continue
    return SEVERITY_ORDER[best] if best >= 0 else None


def to_sarif(leads: list[Any], *, tool_version: str = "0.1.0") -> dict:
    """Converte leads em SARIF 2.1.0 (consumível por GitHub code scanning)."""
    rules: dict[str, dict] = {}
    results = []
    for lead in leads:
        rule_id = f"scopehound/{lead.severity.lower()}"
        rules.setdefault(
            rule_id,
            {
                "id": rule_id,
                "name": f"scopehound-{lead.severity.lower()}",
                "shortDescription": {"text": f"Achado de severidade {lead.severity}"},
            },
        )
        results.append(
            {
                "ruleId": rule_id,
                "level": SARIF_LEVEL.get(lead.severity.upper(), "warning"),
                "message": {"text": f"[{lead.status}] {lead.title}\n{lead.evidence[:1000]}"},
                "locations": [
                    {"physicalLocation": {"artifactLocation": {"uri": lead.url or "about:blank"}}}
                ],
                "properties": {
                    "severity": lead.severity,
                    "status": lead.status,
                    "confirmed": lead.status == "confirmed",
                },
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "scopehound",
                        "version": tool_version,
                        "informationUri": "https://github.com/saulofilho/scopehound",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }


def sarif_json(leads: list[Any]) -> str:
    return json.dumps(to_sarif(leads), ensure_ascii=False, indent=2)
