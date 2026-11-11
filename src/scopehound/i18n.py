"""Idioma das mensagens voltadas ao usuário (pt padrão, en opcional).

O idioma é definido uma vez por processo a partir de SCOPEHOUND_LANGUAGE, mas
guardado num ContextVar para não vazar entre runtimes/testes que rodam no
mesmo processo. `t(pt, en)` escolhe a string; comentários e nomes no código
permanecem num idioma só (inglês), independentemente disto.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Literal

Language = Literal["pt", "en"]
LANGUAGES: tuple[Language, ...] = ("pt", "en")

_language: ContextVar[Language] = ContextVar("scopehound_language", default="pt")


def set_language(language: str) -> None:
    _language.set(language if language in LANGUAGES else "pt")  # type: ignore[arg-type]


def current_language() -> Language:
    return _language.get()


def t(pt: str, en: str) -> str:
    """Devolve a string no idioma atual."""
    return en if _language.get() == "en" else pt
