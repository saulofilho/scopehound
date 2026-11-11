"""Provedor de LLM.

Tudo passa pela API compatível com OpenAI: Gemini (free tier), Groq,
OpenRouter e Ollama (local) funcionam só trocando base_url, modelo e chave.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from ..config import is_local_llm


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
        return f"modelo '{self.model or '(vazio)'}' em {self.base_url}"


def explain_llm_error(exc: Exception, cfg: LlmConfig) -> LlmError:
    """Traduz erros do provedor em uma mensagem com o provável ajuste.

    O stack trace do openai/langchain não diz qual modelo ou URL falhou, nem o
    que fazer. Aqui a mensagem nomeia os dois e sugere a correção."""
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    name = type(exc).__name__
    ollama = cfg.is_local and "11434" in cfg.base_url
    base = f"Falha no LLM ({cfg.where})."

    if status == 404 or "NotFound" in name:
        hint = (
            f"O provedor não conhece o modelo '{cfg.model}'. "
            "Confira o nome exato — ele precisa bater com o que o provedor expõe."
        )
        if ollama:
            hint += (
                " No Ollama: rode `ollama list` e use o nome com a tag "
                "(ex.: 'qwen3:8b', não 'qwen3'); baixe com `ollama pull <modelo>`."
            )
        else:
            hint += (
                " Confira também se SCOPEHOUND_LLM_BASE_URL aponta para o caminho "
                "compatível com OpenAI (geralmente terminando em /v1)."
            )
        return LlmError(f"{base} {hint}")
    if status in (401, 403) or "Authentication" in name or "PermissionDenied" in name:
        return LlmError(
            f"{base} Credencial recusada ({status}). Verifique SCOPEHOUND_LLM_API_KEY "
            "ou a chave do projeto (`scopehound project llm <projeto> --api-key`)."
        )
    if status == 429 or "RateLimit" in name:
        return LlmError(f"{base} Limite do provedor atingido (429). Aguarde ou troque de modelo.")
    if "Connection" in name or "Timeout" in name or "APIConnection" in name:
        service = (
            "o servidor do Ollama está rodando (`ollama serve`)" if ollama else "a URL e a rede"
        )
        return LlmError(f"{base} Não foi possível conectar. Confira se {service}.")
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
