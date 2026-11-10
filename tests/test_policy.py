import pytest

from scopehound.policy import ToolSpec, decide, grant_key, validate_response
from scopehound.tools import get_tool

SEND = get_tool("send_request").spec
LEAD = get_tool("save_lead").spec
SCRIPT = ToolSpec("run_script", "executa script", "admin", always_ask=True)


@pytest.mark.parametrize(
    ("spec", "args", "mode", "settings", "grants", "expected"),
    [
        (SEND, {"method": "GET"}, "smart", None, [], "allow"),
        (SEND, {"method": "POST"}, "smart", None, [], "ask"),
        (
            SEND,
            {"method": "POST"},
            "smart",
            None,
            [grant_key("send_request", "intrusive")],
            "allow",
        ),
        (SEND, {"method": "POST"}, "smart", None, [grant_key("send_request", "active")], "ask"),
        (LEAD, {}, "smart", None, [], "allow"),
        (SEND, {"method": "GET"}, "manual", None, [], "ask"),
        (SEND, {"method": "POST"}, "manual", {"manual": "act"}, [], "allow"),
        (LEAD, {}, "manual", None, [], "allow"),
        (SEND, {"method": "POST"}, "autonomous", None, [], "allow"),
        (SEND, {"method": "GET"}, "autonomous", {"enabled": False}, [], "deny"),
        (SCRIPT, {}, "autonomous", None, [], "ask"),
        (SCRIPT, {}, "manual", {"manual": "act"}, [], "ask"),
        (SCRIPT, {}, "smart", None, [grant_key("run_script", "admin")], "ask"),
    ],
)
def test_decision_matrix(spec, args, mode, settings, grants, expected):
    assert (
        decide(spec, args, mode=mode, settings=settings, session_grants=grants).outcome == expected
    )


def test_response_rules():
    validate_response("once", mode="manual", spec=SEND)
    validate_response("session", mode="smart", spec=SEND)
    validate_response("always", mode="manual", spec=SEND)
    for response, mode, spec in [
        ("session", "manual", SEND),
        ("always", "smart", SEND),
        ("always", "manual", SCRIPT),
        ("maybe", "smart", SEND),
    ]:
        with pytest.raises(ValueError):
            validate_response(response, mode=mode, spec=spec)
