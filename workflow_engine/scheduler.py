"""Cooperative scheduler used by the execution engine."""
from __future__ import annotations

import asyncio
from collections import deque
from typing import Awaitable, Callable, Deque, Dict, List, Optional

from .errors import SchedulerError
from .models import ExecutionPlan, ScheduledTask


class ExecutionPlanCache:
    """Simple LRU cache for execution plans."""

    def __init__(self, capacity: int = 128) -> None:
        self.capacity = capacity
        self._cache: Dict[str, ExecutionPlan] = {}
        self._order: Deque[str] = deque()

    def get(self, key: str) -> Optional[ExecutionPlan]:
        plan = self._cache.get(key)
        if plan is not None:
            self._order.remove(key)
            self._order.append(key)
        return plan

    def put(self, key: str, plan: ExecutionPlan) -> None:
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self.capacity:
            oldest = self._order.popleft()
            self._cache.pop(oldest, None)
        self._cache[key] = plan
        self._order.append(key)

    def clear(self) -> None:
        self._cache.clear()
        self._order.clear()


class TaskScheduler:
    """Minimal cooperative task scheduler for workflow nodes."""

    def __init__(self, concurrency: int = 4) -> None:
        self.concurrency = concurrency
        self._queue: "asyncio.Queue[ScheduledTask]" = asyncio.Queue()
        self._workers: List[asyncio.Task[None]] = []
        self._running = False

    async def start(self, worker: Callable[[ScheduledTask], Awaitable[None]]) -> None:
        if self._running:
            return
        self._running = True
        for _ in range(self.concurrency):
            self._workers.append(asyncio.create_task(self._worker_loop(worker)))

    async def schedule(self, tasks: List[ScheduledTask]) -> None:
        if not self._running:
            raise SchedulerError("Scheduler must be started before scheduling tasks")
        for task in tasks:
            await self._queue.put(task)

    async def schedule_batch(self, tasks: List[ScheduledTask], batch_size: int) -> None:
        if batch_size <= 0:
            raise SchedulerError("batch_size must be positive")
        for index in range(0, len(tasks), batch_size):
            batch = tasks[index : index + batch_size]
            await self.schedule(batch)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for _ in self._workers:
            await self._queue.put(None)  # type: ignore[arg-type]
        await asyncio.gather(*self._workers)
        self._workers.clear()

    async def wait_until_idle(self) -> None:
        await self._queue.join()

    async def _worker_loop(
        self, worker: Callable[[ScheduledTask], Awaitable[None]]
    ) -> None:
        while True:
            scheduled = await self._queue.get()
            if scheduled is None:  # sentinel for shutdown
                break
            await worker(scheduled)
            self._queue.task_done()
