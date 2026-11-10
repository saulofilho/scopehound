import json
from dataclasses import dataclass

from scopehound.report import max_severity, severity_at_least, to_sarif


@dataclass
class L:
    severity: str
    title: str
    url: str
    evidence: str
    status: str


def leads():
    return [
        L(
            "HIGH",
            "IDOR",
            "http://app.lab/api/basket/7",
            "200 com dados de outro user",
            "confirmed",
        ),
        L("LOW", "Header ausente", "http://app.lab/", "sem CSP", "lead"),
    ]


def test_severity_threshold():
    assert severity_at_least("HIGH", "medium")
    assert not severity_at_least("LOW", "high")
    assert max_severity(leads()) == "HIGH"
    assert max_severity([]) is None


def test_sarif_structure():
    sarif = to_sarif(leads())
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "scopehound"
    results = run["results"]
    assert len(results) == 2
    assert results[0]["level"] == "error"  # HIGH
    assert results[1]["level"] == "note"  # LOW
    assert results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"].endswith("/7")
    assert results[0]["properties"]["confirmed"] is True
    # serializável
    json.loads(json.dumps(sarif))
