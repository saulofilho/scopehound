"""Execução das tarefas (uma execução por tarefa de cada vez)."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from .errors import Conflict
from .serialize import message_dict

if TYPE_CHECKING:
    from .runtime import Runtime

log = logging.getLogger(__name__)


class TaskRunner:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._background: dict[str, asyncio.Task[None]] = {}

    def busy(self, task_id: str) -> bool:
        return self._locks[task_id].locked()

    def start(self, task_id: str, graph_input: Any) -> None:
        """Roda em segundo plano (API)."""
        if self.busy(task_id):
            raise Conflict("a tarefa já está em execução")
        job = asyncio.create_task(self.run(task_id, graph_input))
        self._background[task_id] = job
        job.add_done_callback(lambda _: self._background.pop(task_id, None))

    async def wait(self, task_id: str) -> None:
        job = self._background.get(task_id)
        if job is not None:
            await job

    async def cancel_all(self) -> None:
        for job in list(self._background.values()):
            job.cancel()
        await asyncio.gather(*self._background.values(), return_exceptions=True)

    async def run(self, task_id: str, graph_input: Any) -> str:
        rt = self.rt
        async with self._locks[task_id]:
            await rt.set_task_status(task_id, "running")
            config = {"configurable": {"thread_id": task_id}}
            error: str | None = None
            try:
                async for update in rt.graph.astream(graph_input, config, stream_mode="updates"):
                    for node, data in update.items():
                        if node == "__interrupt__" or not isinstance(data, dict):
                            continue
                        for message in data.get("messages", []):
                            rt.events.publish(
                                task_id, {"type": "message", "message": message_dict(message)}
                            )
                snapshot = await rt.graph.aget_state(config)
                if snapshot.interrupts:
                    status = "waiting_approval"
                    for intr in snapshot.interrupts:
                        rt.events.publish(task_id, {"type": "approval", "approval": intr.value})
                elif snapshot.values.get("stopped"):
                    status = "stopped"
                elif snapshot.values.get("finished"):
                    status = "done"
                else:
                    status = "idle"
            except Exception as exc:  # noqa: BLE001 - a falha vira status da tarefa
                log.exception("tarefa %s falhou", task_id)
                status, error = "failed", f"{type(exc).__name__}: {exc}"
            await rt.set_task_status(task_id, status, error=error)
            return status
