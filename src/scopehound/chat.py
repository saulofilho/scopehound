"""Chat de terminal (equivalente ao painel de conversa do Burp AT)."""

from __future__ import annotations

import asyncio
import json

import typer

from .core import Conflict, Runtime
from .core import service as svc

CHOICES = {
    "o": ("once", "aprovar uma vez"),
    "s": ("session", "aprovar para a sessão (smart)"),
    "a": ("always", "sempre aprovar (manual)"),
    "r": ("reject", "rejeitar"),
    "d": ("redirect", "rejeitar e redirecionar"),
}


def _print_message(m: dict) -> None:
    if m["role"] == "ai":
        if m["content"]:
            typer.secho(f"\nscopehound › {m['content']}", fg="cyan")
        for call in m.get("tool_calls", []):
            typer.secho(
                f"  ↳ {call['name']} {json.dumps(call['args'], ensure_ascii=False)}",
                fg="bright_black",
            )
    elif m["role"] == "tool":
        text = m["content"] if len(m["content"]) < 1200 else m["content"][:1200] + " […]"
        typer.secho(f"  ⇠ {m['name']}: {text}", fg="bright_black")


async def _ask(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def run_chat(rt: Runtime, project_ref: str, task_id: str | None, mode: str) -> None:
    project = await svc.find_project(rt, project_ref)
    seen = 0
    if task_id:
        seen = len(await svc.get_messages(rt, task_id))
    typer.secho(f"projeto {project.name} · modo {mode} · /mode <modo> · /sair", fg="green")
    while True:
        try:
            text = (await _ask("\nvocê › ")).strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not text:
            continue
        if text in ("/sair", "/exit"):
            return
        if text.startswith("/mode "):
            mode = text.split(maxsplit=1)[1]
            if task_id:
                await svc.set_task_mode(rt, task_id, mode)
            typer.echo(f"modo: {mode}")
            continue
        try:
            if task_id is None:
                task = await svc.create_task(rt, project.id, prompt=text, mode=mode, wait=True)
                task_id = task.id
                typer.secho(f"(tarefa {task_id})", fg="bright_black")
            else:
                task = await svc.send_message(rt, task_id, text, wait=True)
        except Conflict as exc:
            typer.secho(str(exc), fg="red")
            continue

        while True:
            messages = await svc.get_messages(rt, task_id)
            for m in messages[seen:]:
                _print_message(m)
            seen = len(messages)
            task = await svc.get_task(rt, task_id)
            if task.status == "failed":
                typer.secho(f"falhou: {task.error}", fg="red")
            if task.status != "waiting_approval":
                break
            pending = await svc.list_approvals(rt, task_id, "pending")
            approval = pending[0]
            typer.secho(
                f"\n⚠ aprovação: {approval.tool} ({approval.impact}) — {approval.reason}\n"
                f"  {json.dumps(approval.args, ensure_ascii=False)}",
                fg="yellow",
            )
            options = " ".join(f"[{k}] {label}" for k, (_, label) in CHOICES.items())
            choice = ""
            while choice not in CHOICES:
                choice = (await _ask(f"  {options}\n  › ")).strip().lower()
            response = CHOICES[choice][0]
            note = await _ask("  instrução › ") if response == "redirect" else ""
            try:
                await svc.resolve_approval(rt, approval.id, response, note, wait=True)
            except Conflict as exc:
                typer.secho(str(exc), fg="red")
