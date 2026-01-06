import asyncio
import os
import shlex
from pathlib import Path
from typing import List, Tuple

from fastapi import HTTPException, status

from .config import get_settings
from .task_manager import Task, TaskManager, TaskStatus, task_manager


class ValidationError(HTTPException):
    def __init__(self, code: str, message: str, http_status: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=http_status, detail={"code": code, "message": message})


def validate_script(path_str: str, settings=get_settings()) -> List[str]:
    path = Path(path_str).resolve()
    allowed_root = Path(settings.allowed_script_root).resolve()
    if not str(path).startswith(str(allowed_root)):
        raise ValidationError("path_not_allowed", "Script path outside allowed root")
    if not path.is_file():
        raise ValidationError("not_a_file", "Script path is not a file")
    if not os.access(path, os.X_OK):
        raise ValidationError("not_executable", "Script is not executable")
    return [str(path)]


def validate_command(command: str, settings=get_settings()) -> List[str]:
    raw = command.strip()
    if not raw:
        raise ValidationError("empty_command", "Command is empty")

    if settings.allow_arbitrary_command:
        # Even in arbitrary mode, avoid shell=True; split arguments.
        return shlex.split(raw)

    # Controlled mode: ensure command starts with whitelisted prefix
    for prefix in settings.whitelist_commands:
        if raw.startswith(prefix):
            return shlex.split(raw)
    raise ValidationError("command_not_allowed", "Command not permitted in controlled mode")


def build_command(mode: str, value: str) -> Tuple[List[str], str]:
    settings = get_settings()
    if mode == "script":
        args = validate_script(value, settings)
        return args, value
    if mode == "command":
        args = validate_command(value, settings)
        return args, value
    raise ValidationError("invalid_mode", "Unsupported execution mode")


async def run_task(mode: str, value: str, manager: TaskManager = task_manager) -> Task:
    """Start a task asynchronously and return immediately."""

    args, display_value = build_command(mode, value)
    task = await manager.create_task(mode, value)

    async def _runner() -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except Exception as exc:  # pragma: no cover - startup failures are rare
            task.status = TaskStatus.FAILED
            task.append_output(f"[system] Failed to start task: {exc}\n")
            await manager.finish_task(task, task.status)
            return

        task.process = process
        task.append_output(f"[task {task.task_id}] Started {mode}: {display_value}\n")

        async def read_stream(stream: asyncio.StreamReader, label: str) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace")
                task.append_output(f"[{label}] {decoded}")

        stdout_task = asyncio.create_task(read_stream(process.stdout, "stdout"))
        stderr_task = asyncio.create_task(read_stream(process.stderr, "stderr"))

        await asyncio.wait({stdout_task, stderr_task})
        return_code = await process.wait()

        if task.status == TaskStatus.STOPPED:
            task.append_output("[system] Task stopped by user\n")
        elif return_code == 0:
            task.status = TaskStatus.FINISHED
            task.append_output("[system] Task finished successfully\n")
        else:
            task.status = TaskStatus.FAILED
            task.append_output(f"[system] Task failed with code {return_code}\n")

        await manager.finish_task(task, task.status)

    asyncio.create_task(_runner())
    return task
