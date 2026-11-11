"""Provedor de LLM.

Tudo passa pela API compatível com OpenAI: Gemini (free tier), Groq,
OpenRouter e Ollama (local) funcionam só trocando base_url, modelo e chave.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from ..config import is_local_llm
from ..i18n import t


class LlmError(RuntimeError):
    """Falha ao falar com o provedor de LLM, com uma mensagem acionável."""


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

    @property
    def where(self) -> str:
        empty = t("(vazio)", "(empty)")
        return t(
            f"modelo '{self.model or empty}' em {self.base_url}",
            f"model '{self.model or empty}' at {self.base_url}",
        )


def explain_llm_error(exc: Exception, cfg: LlmConfig) -> LlmError:
    """Translate provider errors into a message with the likely fix.

    The openai/langchain stack trace does not say which model or URL failed, nor
    what to do. This names both and suggests the correction."""
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    name = type(exc).__name__
    ollama = cfg.is_local and "11434" in cfg.base_url
    base = t(f"Falha no LLM ({cfg.where}).", f"LLM failure ({cfg.where}).")

    if status == 404 or "NotFound" in name:
        hint = t(
            f"O provedor não conhece o modelo '{cfg.model}'. "
            "Confira o nome exato — ele precisa bater com o que o provedor expõe.",
            f"The provider does not know the model '{cfg.model}'. "
            "Check the exact name — it must match what the provider exposes.",
        )
        if ollama:
            hint += t(
                " No Ollama: rode `ollama list` e use o nome com a tag "
                "(ex.: 'qwen3:8b', não 'qwen3'); baixe com `ollama pull <modelo>`.",
                " On Ollama: run `ollama list` and use the name with its tag "
                "(e.g. 'qwen3:8b', not 'qwen3'); pull it with `ollama pull <model>`.",
            )
        else:
            hint += t(
                " Confira também se SCOPEHOUND_LLM_BASE_URL aponta para o caminho "
                "compatível com OpenAI (geralmente terminando em /v1).",
                " Also check that SCOPEHOUND_LLM_BASE_URL points to the "
                "OpenAI-compatible path (usually ending in /v1).",
            )
        return LlmError(f"{base} {hint}")
    if status in (401, 403) or "Authentication" in name or "PermissionDenied" in name:
        return LlmError(
            base
            + t(
                f" Credencial recusada ({status}). Verifique SCOPEHOUND_LLM_API_KEY "
                "ou a chave do projeto (`scopehound project llm <projeto> --api-key`).",
                f" Credential refused ({status}). Check SCOPEHOUND_LLM_API_KEY "
                "or the project key (`scopehound project llm <project> --api-key`).",
            )
        )
    if status == 429 or "RateLimit" in name:
        return LlmError(
            base
            + t(
                " Limite do provedor atingido (429). Aguarde ou troque de modelo.",
                " Provider rate limit hit (429). Wait or switch model.",
            )
        )
    if "Connection" in name or "Timeout" in name or "APIConnection" in name:
        service = (
            t(
                "o servidor do Ollama está rodando (`ollama serve`)",
                "the Ollama server is running (`ollama serve`)",
            )
            if ollama
            else t("a URL e a rede", "the URL and the network")
        )
        return LlmError(
            base
            + t(
                f" Não foi possível conectar. Confira se {service}.",
                f" Could not connect. Check that {service}.",
            )
        )
    return LlmError(f"{base} {name}: {exc}")


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
