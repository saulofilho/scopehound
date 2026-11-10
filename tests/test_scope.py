import pytest
from conftest import make_scope
from pydantic import ValidationError

from scopehound.guardrails import ScopeViolation, check_method, check_url, load_scope


# Portados do hackbot -------------------------------------------------------
def test_blocks_out_of_scope_host(scope):
    with pytest.raises(ScopeViolation):
        check_url(scope, "http://evil.com/")


def test_allows_wildcard_subdomain(scope):
    assert check_url(scope, "http://juice-shop.lab/api").host == "juice-shop.lab"


def test_blocks_excluded_path(scope):
    with pytest.raises(ScopeViolation):
        check_url(scope, "http://localhost/logout")


def test_wildcard_host_rejected():
    with pytest.raises(ValidationError):
        make_scope(allowed_hosts=["*"])


# Novos ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "/Logout",
        "/logout/",
        "/./logout",
        "//logout",
        "/%6cogout",
        "/logout;jsessionid=abc",
        "/x/../logout",
        "/x/..;/logout",
        "/logout/extra",
        "/ADMIN/delete",
        "/admin%2fdelete",
    ],
)
def test_exclusion_cannot_be_bypassed(scope, path):
    with pytest.raises(ScopeViolation):
        check_url(scope, f"http://localhost{path}")


def test_similar_path_is_not_excluded(scope):
    assert check_url(scope, "http://localhost/logout-info").path == "/logout-info"


def test_double_encoding_rejected(scope):
    with pytest.raises(ScopeViolation, match="dupla"):
        check_url(scope, "http://localhost/%252e%252e/logout")


def test_dotdot_above_root_rejected(scope):
    with pytest.raises(ScopeViolation):
        check_url(scope, "http://localhost/%2e%2e/etc")


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pw@localhost/",
        "http://evil.com\\@localhost/",
        "http://localhost/a b",
        "http://localhost/\r\nX: y",
        "ftp://localhost/",
        "file:///etc/passwd",
        "gopher://localhost/",
        "http:///nohost",
    ],
)
def test_malformed_or_tricky_urls_rejected(scope, url):
    with pytest.raises(ScopeViolation):
        check_url(scope, url)


def test_wildcard_does_not_match_apex_or_lookalike():
    sc = make_scope(allowed_hosts=["*.example.com"])
    assert check_url(sc, "http://a.b.example.com/").host == "a.b.example.com"
    for url in ("http://example.com/", "http://evilexample.com/", "http://example.com.evil.io/"):
        with pytest.raises(ScopeViolation):
            check_url(sc, url)


def test_host_normalization(scope):
    assert check_url(scope, "http://LOCALHOST./").host == "localhost"


def test_ip_literal_needs_cidr_or_exact_host():
    sc = make_scope(allowed_hosts=["127.0.0.1"], allowed_cidrs=["10.1.0.0/16"])
    check_url(sc, "http://127.0.0.1/")
    check_url(sc, "http://10.1.2.3/")
    with pytest.raises(ScopeViolation):
        check_url(sc, "http://10.2.0.1/")


def test_ports():
    sc = make_scope(allowed_ports=[3000])
    assert check_url(sc, "http://localhost:3000/").port == 3000
    with pytest.raises(ScopeViolation):
        check_url(sc, "http://localhost/")


def test_allowed_paths():
    sc = make_scope(allowed_paths=["/api/*"])
    check_url(sc, "http://localhost/api/v1/users")
    with pytest.raises(ScopeViolation):
        check_url(sc, "http://localhost/api/../internal")


def test_methods(scope):
    assert check_method(scope, "post") == "POST"
    with pytest.raises(ScopeViolation):
        check_method(scope, "DELETE")


@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed_hosts": ["*.com"]},
        {"allowed_hosts": ["a*b.example.com"]},
        {"allowed_hosts": ["exa mple.com"]},
        {"allowed_cidrs": ["0.0.0.0/0"]},
        {"allowed_cidrs": ["10.0.0.0/7"]},
        {"allowed_paths": ["api/*"]},
        {"allowed_methods": ["CONNECT"]},
        {"allowed_ports": [0]},
        {"authorized_by": "   "},
        {"unknown_field": 1},
    ],
)
def test_invalid_scopes(overrides):
    with pytest.raises(ValidationError):
        make_scope(**overrides)


def test_authorized_by_required():
    from scopehound.guardrails import Scope

    with pytest.raises(ValidationError):
        Scope(allowed_hosts=["localhost"])


def test_load_example_scope():
    from pathlib import Path

    sc = load_scope(Path(__file__).parent.parent / "scope.example.yaml")
    assert "localhost" in sc.allowed_hosts
