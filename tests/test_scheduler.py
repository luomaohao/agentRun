import asyncio

import pytest

from workflow_engine.scheduler import ExecutionPlanCache, TaskScheduler
from workflow_engine.models import ScheduledTask, ExecutionContext, Node


def test_task_scheduler_batches():
    async def runner():
        scheduler = TaskScheduler(concurrency=1)
        processed = []

        async def worker(task: ScheduledTask):
            processed.append(task.node.id)

        await scheduler.start(worker)
        context = ExecutionContext(workflow_id="wf", execution_id="exe")
        tasks = [
            ScheduledTask(node=Node(id=str(i), type="noop"), context=context)
            for i in range(4)
        ]
        await scheduler.schedule_batch(tasks, batch_size=2)
        await scheduler.wait_until_idle()
        await scheduler.stop()

        assert processed == ["0", "1", "2", "3"]

    asyncio.run(runner())


def test_execution_plan_cache_eviction():
    cache = ExecutionPlanCache(capacity=2)
    cache.put("a", object())  # type: ignore[arg-type]
    cache.put("b", object())  # type: ignore[arg-type]
    cache.get("a")
    cache.put("c", object())  # type: ignore[arg-type]
    assert cache.get("b") is None
    assert cache.get("a") is not None
