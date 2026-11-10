import pytest

from scopehound.guardrails import ToolArgsDenied, evaluate_poc, sanitize_sqlmap_args


def test_forced_args_and_allowed_flags():
    out = sanitize_sqlmap_args(["--dbs", "-p", "id", "--risk=3", "--level", "5", "--threads=50"])
    assert out[:3] == ["--batch", "--risk=1", "--level=1"]
    assert out[3:] == ["--dbs", "-p", "id", "--threads", "4"]


@pytest.mark.parametrize(
    "args",
    [
        ["--os-shell"],
        ["--os-sh"],  # abreviação
        ["-u", "http://evil.com/"],
        ["--url=http://evil.com/"],
        ["-m", "targets.txt"],
        ["-g", "inurl:php?id="],
        ["--alert=id"],
        ["--dump-all"],
        ["--file-read=/etc/passwd"],
        ["--proxy=http://x"],
        ["--tamper=/tmp/evil.py"],
        ["-p", "--os-shell"],  # valor que é flag
        ["--headers", "Host: evil.com"],
        ["-H", "X-A: 1\\nHost: evil.com"],
        ["http://evil.com/"],
        ["--dbs=1"],
        ["-p"],
    ],
)
def test_denied(args):
    with pytest.raises(ToolArgsDenied):
        sanitize_sqlmap_args(args)


def test_poc():
    assert evaluate_poc(status=200, body="admin", expected_substring="admin").reproduced
    assert not evaluate_poc(status=403, body="", expected_status=200).reproduced
    assert not evaluate_poc(status=None, body="", expected_status=200).reproduced
    with pytest.raises(ValueError):
        evaluate_poc(status=200, body="")
