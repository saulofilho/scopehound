import pytest

from scopehound.redact import CATEGORIES, Redactor


def test_off_is_identity():
    r = Redactor.from_policy("off")
    assert not r.active
    assert r.text("Bearer abc123 a@b.com") == "Bearer abc123 a@b.com"


@pytest.mark.parametrize(
    ("raw", "needle"),
    [
        ("contato: joao@empresa.com", "«email»"),
        ("Authorization: Bearer eyJhbGci.payloadpart.sigpartxx", "«"),
        ("cartão 4111 1111 1111 1111", "«card»"),
        ("AKIAIOSFODNN7EXAMPLE", "«aws_key»"),
        ("cpf 123.456.789-00", "«pix_cpf»"),
    ],
)
def test_on_masks(raw, needle):
    assert needle in Redactor.from_policy("on").text(raw)
    assert "empresa.com" not in Redactor.from_policy("on").text("joao@empresa.com")


def test_header_masking():
    r = Redactor.from_policy("headers")
    assert r.header_value("Authorization", "Bearer secret-token-value") == "«oculto»"
    assert r.header_value("Cookie", "session=xyz") == "«oculto»"
    assert r.header_value("Accept", "application/json") == "application/json"


def test_category_subset():
    r = Redactor.from_policy("email")
    assert r.categories == frozenset({"email"})
    assert "«email»" in r.text("a@b.com")
    assert r.text("4111 1111 1111 1111") == "4111 1111 1111 1111"  # card não está no subset


def test_all_categories_known():
    assert "headers" in CATEGORIES and "email" in CATEGORIES
