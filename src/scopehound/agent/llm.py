"""Provedor de LLM.

Tudo passa pela API compatível com OpenAI: Gemini (free tier), Groq,
OpenRouter e Ollama (local) funcionam só trocando base_url, modelo e chave.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from ..config import is_local_llm


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    base_url: str
    model: str
    api_key: str | None
    temperature: float = 0.1

    @property
    def is_local(self) -> bool:
        return is_local_llm(self.provider, self.base_url)


def build_chat_model(cfg: LlmConfig) -> BaseChatModel:
    if cfg.provider != "openai_compat":
        raise ValueError(f"provedor '{cfg.provider}' precisa ser injetado (ex.: testes)")
    if not cfg.model:
        raise ValueError("modelo não configurado: defina SCOPEHOUND_LLM_MODEL ou o LLM do projeto")
    if not cfg.api_key and not cfg.is_local:
        raise ValueError(
            "chave de API não configurada: defina SCOPEHOUND_LLM_API_KEY "
            "ou a chave do projeto (scopehound project llm --api-key)"
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=cfg.model,
        base_url=cfg.base_url,
        api_key=cfg.api_key or "local",
        temperature=cfg.temperature,
        max_retries=2,
        timeout=120,
    )
