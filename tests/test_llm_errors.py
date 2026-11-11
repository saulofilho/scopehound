import pytest
from conftest import LAB_SCOPE

from scopehound.agent.llm import LlmConfig, LlmError, explain_llm_error
from scopehound.core import service as svc


class _Err(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status_code = status


OLL = LlmConfig("openai_compat", "http://localhost:11434/v1", "qwen3", None)
CLOUD = LlmConfig("openai_compat", "https://api.groq.com/openai/v1", "m", "k")


def test_404_ollama_names_model_and_tag_hint():
    msg = str(explain_llm_error(_Err("model not found", 404), OLL))
    assert "qwen3" in msg and "ollama list" in msg and "11434" in msg


def test_404_cloud_hints_base_url():
    msg = str(explain_llm_error(_Err("x", 404), CLOUD))
    assert "/v1" in msg and "qwen" not in msg


def test_401_points_to_api_key():
    assert "Credencial" in str(explain_llm_error(_Err("bad", 401), CLOUD))


def test_connection_error_hints_ollama_serve():
    class Conn(Exception):
        pass

    Conn.__name__ = "APIConnectionError"
    assert "ollama serve" in str(explain_llm_error(Conn("refused"), OLL))


def test_name_based_detection_without_status():
    class OpenAIModelNotFoundError(Exception):
        pass

    assert "não conhece o modelo" in str(explain_llm_error(OpenAIModelNotFoundError("404"), OLL))


async def test_task_fails_with_clean_llm_message(harness):
    """Um erro do provedor vira a mensagem de erro da tarefa, não um traceback cru."""

    def boom(messages):  # o modelo roteirizado levanta um 404
        raise _Err("model not found", 404)

    harness.model.script = [boom]
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.create_task(rt, project.id, prompt="oi", wait=True)
        assert task.status == "failed"
        assert "LlmError" in task.error and "modelo" in task.error


def test_llm_error_is_runtime_error():
    assert issubclass(LlmError, RuntimeError)
    with pytest.raises(LlmError):
        raise explain_llm_error(_Err("x", 404), OLL)
