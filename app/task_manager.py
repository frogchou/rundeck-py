import asyncio
import os
import signal
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, List, Optional

MAX_BUFFER_BYTES = 5 * 1024 * 1024


class TaskStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    FINISHED = "finished"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    mode: str
    value: str
    start_time: float
    status: TaskStatus = TaskStatus.RUNNING
    output_buffer: Deque[str] = field(default_factory=deque)
    buffer_size: int = 0
    process: Optional[asyncio.subprocess.Process] = None
    subscribers: List[asyncio.Queue] = field(default_factory=list)

    def append_output(self, text: str) -> None:
        encoded = text.encode()
        length = len(encoded)
        self.output_buffer.append(text)
        self.buffer_size += length
        while self.buffer_size > MAX_BUFFER_BYTES and self.output_buffer:
            removed = self.output_buffer.popleft()
            self.buffer_size -= len(removed.encode())

        for queue in list(self.subscribers):
            try:
                queue.put_nowait(text)
            except asyncio.QueueFull:
                # Drop updates for slow consumers
                pass

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)


class TaskManager:
    def __init__(self) -> None:
        self.current_task: Optional[Task] = None
        self._lock = asyncio.Lock()

    async def create_task(self, mode: str, value: str) -> Task:
        async with self._lock:
            if self.current_task and self.current_task.status == TaskStatus.RUNNING:
                raise RuntimeError("Another task is currently running")
            task = Task(task_id=str(uuid.uuid4()), mode=mode, value=value, start_time=time.time())
            self.current_task = task
            return task

    def get_task(self, task_id: str) -> Optional[Task]:
        if self.current_task and self.current_task.task_id == task_id:
            return self.current_task
        return None

    async def finish_task(self, task: Task, status: TaskStatus) -> None:
        async with self._lock:
            if task.status == TaskStatus.RUNNING:
                task.status = status

    async def stop_task(self, task_id: str) -> None:
        async with self._lock:
            if not self.current_task or self.current_task.task_id != task_id:
                return
            task = self.current_task
            if task.process and task.status == TaskStatus.RUNNING:
                try:
                    os.killpg(task.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                task.status = TaskStatus.STOPPED


task_manager = TaskManager()
