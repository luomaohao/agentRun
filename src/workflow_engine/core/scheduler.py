"""
任务调度器实现
"""
import asyncio
import heapq
from typing import Dict, List, Set, Optional, Callable, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
import logging

from ..models.workflow import Workflow, Node, NodeType
from ..models.execution import (
    WorkflowExecution, NodeExecution, ExecutionContext,
    NodeExecutionStatus, ExecutionStatus
)
from ..exceptions import SchedulingError, ResourceAllocationError, ConcurrencyLimitError


logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """调度任务"""
    node_id: str
    execution_id: str
    priority: int = 0
    scheduled_time: datetime = field(default_factory=datetime.utcnow)
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __lt__(self, other):
        """用于优先队列比较"""
        if self.priority != other.priority:
            return self.priority > other.priority  # 高优先级先执行
        return self.scheduled_time < other.scheduled_time


@dataclass
class ResourceQuota:
    """资源配额"""
    max_concurrent_tasks: int = 100
    max_tasks_per_type: Dict[str, int] = field(default_factory=dict)
    max_tasks_per_agent: Dict[str, int] = field(default_factory=dict)
    max_memory_mb: Optional[int] = None
    max_cpu_percent: Optional[float] = None


class ResourceManager:
    """资源管理器"""
    
    def __init__(self, quota: ResourceQuota = None):
        self.quota = quota or ResourceQuota()
        self.active_tasks: Set[str] = set()
        self.active_by_type: Dict[str, Set[str]] = defaultdict(set)
        self.active_by_agent: Dict[str, Set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()
    
    async def can_allocate(self, node: Node) -> bool:
        """检查是否可以分配资源"""
        async with self._lock:
            # 检查总并发数
            if len(self.active_tasks) >= self.quota.max_concurrent_tasks:
                return False
            
            # 检查节点类型限制
            node_type = node.type.value
            if node_type in self.quota.max_tasks_per_type:
                if len(self.active_by_type[node_type]) >= self.quota.max_tasks_per_type[node_type]:
                    return False
            
            # 检查智能体限制
            if node.type == NodeType.AGENT:
                agent_id = node.config.get('agent_id')
                if agent_id and agent_id in self.quota.max_tasks_per_agent:
                    if len(self.active_by_agent[agent_id]) >= self.quota.max_tasks_per_agent[agent_id]:
                        return False
            
            return True
    
    async def allocate(self, task_id: str, node: Node):
        """分配资源"""
        async with self._lock:
            if not await self.can_allocate(node):
                raise ResourceAllocationError(f"Cannot allocate resources for task {task_id}")
            
            self.active_tasks.add(task_id)
            self.active_by_type[node.type.value].add(task_id)
            
            if node.type == NodeType.AGENT:
                agent_id = node.config.get('agent_id')
                if agent_id:
                    self.active_by_agent[agent_id].add(task_id)
    
    async def release(self, task_id: str, node: Node):
        """释放资源"""
        async with self._lock:
            self.active_tasks.discard(task_id)
            self.active_by_type[node.type.value].discard(task_id)
            
            if node.type == NodeType.AGENT:
                agent_id = node.config.get('agent_id')
                if agent_id:
                    self.active_by_agent[agent_id].discard(task_id)
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """获取资源使用统计"""
        return {
            "total_active_tasks": len(self.active_tasks),
            "max_concurrent_tasks": self.quota.max_concurrent_tasks,
            "active_by_type": {k: len(v) for k, v in self.active_by_type.items()},
            "active_by_agent": {k: len(v) for k, v in self.active_by_agent.items()}
        }


class RateLimiter:
    """速率限制器"""
    
    def __init__(self, rate: int, interval: timedelta = timedelta(seconds=1)):
        self.rate = rate
        self.interval = interval
        self.tokens = rate
        self.last_update = datetime.utcnow()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1):
        """获取令牌"""
        async with self._lock:
            await self._update_tokens()
            
            while self.tokens < tokens:
                wait_time = (self.interval.total_seconds() * tokens) / self.rate
                await asyncio.sleep(wait_time)
                await self._update_tokens()
            
            self.tokens -= tokens
    
    async def _update_tokens(self):
        """更新令牌数"""
        now = datetime.utcnow()
        elapsed = (now - self.last_update).total_seconds()
        self.tokens = min(
            self.rate,
            self.tokens + (elapsed * self.rate / self.interval.total_seconds())
        )
        self.last_update = now


class TaskScheduler:
    """任务调度器"""
    
    def __init__(self, resource_manager: ResourceManager = None):
        self.resource_manager = resource_manager or ResourceManager()
        self.ready_queue: List[ScheduledTask] = []
        self.waiting_tasks: Dict[str, ScheduledTask] = {}
        self.running_tasks: Dict[str, ScheduledTask] = {}
        self.rate_limiters: Dict[str, RateLimiter] = {}
        self.task_executors: Dict[str, Callable] = {}
        self._scheduler_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
    
    async def start(self):
        """启动调度器"""
        if self._scheduler_task:
            return
        
        self._stop_event.clear()
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Task scheduler started")
    
    async def stop(self):
        """停止调度器"""
        if not self._scheduler_task:
            return
        
        self._stop_event.set()
        await self._scheduler_task
        self._scheduler_task = None
        logger.info("Task scheduler stopped")
    
    async def schedule_workflow(self, workflow: Workflow, execution: WorkflowExecution):
        """调度工作流"""
        # 找出所有没有依赖的节点作为起始节点
        start_nodes = []
        for node in workflow.nodes:
            if not node.dependencies:
                start_nodes.append(node)
        
        # 调度起始节点
        for node in start_nodes:
            await self.schedule_node(node, execution)
    
    async def schedule_node(self, node: Node, execution: WorkflowExecution):
        """调度节点"""
        # 检查节点是否可以执行
        if not execution.can_execute_node(node.id, node.dependencies):
            # 添加到等待队列
            task = ScheduledTask(
                node_id=node.id,
                execution_id=execution.id,
                priority=node.metadata.get('priority', 0)
            )
            async with self._lock:
                self.waiting_tasks[f"{execution.id}:{node.id}"] = task
            return
        
        # 创建调度任务
        task = ScheduledTask(
            node_id=node.id,
            execution_id=execution.id,
            priority=node.metadata.get('priority', 0)
        )
        
        # 添加到就绪队列
        async with self._lock:
            heapq.heappush(self.ready_queue, task)
    
    async def _scheduler_loop(self):
        """调度器主循环"""
        while not self._stop_event.is_set():
            try:
                # 处理就绪任务
                await self._process_ready_tasks()
                
                # 检查等待任务
                await self._check_waiting_tasks()
                
                # 短暂休眠避免CPU占用过高
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}", exc_info=True)
    
    async def _process_ready_tasks(self):
        """处理就绪任务"""
        async with self._lock:
            while self.ready_queue:
                # 查看队首任务
                task = self.ready_queue[0]
                
                # 获取节点信息（这里简化处理，实际需要从存储中获取）
                node = await self._get_node(task.node_id, task.execution_id)
                if not node:
                    heapq.heappop(self.ready_queue)
                    continue
                
                # 检查资源是否可用
                if not await self.resource_manager.can_allocate(node):
                    # 资源不足，等待下次循环
                    break
                
                # 弹出任务
                heapq.heappop(self.ready_queue)
                
                # 分配资源
                try:
                    await self.resource_manager.allocate(task.node_id, node)
                    
                    # 移到运行队列
                    self.running_tasks[f"{task.execution_id}:{task.node_id}"] = task
                    
                    # 异步执行任务
                    asyncio.create_task(self._execute_task(task, node))
                    
                except ResourceAllocationError:
                    # 资源分配失败，放回队列
                    heapq.heappush(self.ready_queue, task)
                    break
    
    async def _check_waiting_tasks(self):
        """检查等待任务是否可以执行"""
        ready_tasks = []
        
        async with self._lock:
            for task_key, task in list(self.waiting_tasks.items()):
                # 获取执行状态（简化处理）
                execution = await self._get_execution(task.execution_id)
                if not execution:
                    del self.waiting_tasks[task_key]
                    continue
                
                # 获取节点信息
                node = await self._get_node(task.node_id, task.execution_id)
                if not node:
                    del self.waiting_tasks[task_key]
                    continue
                
                # 检查是否可以执行
                if execution.can_execute_node(node.id, node.dependencies):
                    ready_tasks.append((task_key, task))
        
        # 将就绪的任务移到就绪队列
        async with self._lock:
            for task_key, task in ready_tasks:
                del self.waiting_tasks[task_key]
                heapq.heappush(self.ready_queue, task)
    
    async def _execute_task(self, task: ScheduledTask, node: Node):
        """执行任务"""
        task_key = f"{task.execution_id}:{task.node_id}"
        
        try:
            # 获取执行器
            executor = self.task_executors.get(node.type.value)
            if not executor:
                raise SchedulingError(f"No executor found for node type: {node.type}")
            
            # 应用速率限制
            if node.type.value in self.rate_limiters:
                await self.rate_limiters[node.type.value].acquire()
            
            # 执行任务
            await executor(task, node)
            
        except Exception as e:
            logger.error(f"Task execution failed: {task_key}", exc_info=True)
            # TODO: 处理执行失败，可能需要重试
            
        finally:
            # 释放资源
            await self.resource_manager.release(task.node_id, node)
            
            # 从运行队列移除
            async with self._lock:
                self.running_tasks.pop(task_key, None)
            
            # 触发下游节点调度
            await self._trigger_downstream_nodes(task.execution_id, node)
    
    async def _trigger_downstream_nodes(self, execution_id: str, node: Node):
        """触发下游节点调度"""
        # 获取工作流和执行信息（简化处理）
        workflow = await self._get_workflow(execution_id)
        execution = await self._get_execution(execution_id)
        
        if not workflow or not execution:
            return
        
        # 获取下游节点
        downstream_nodes = workflow.get_downstream_nodes(node.id)
        
        # 调度下游节点
        for downstream_node in downstream_nodes:
            await self.schedule_node(downstream_node, execution)
    
    def register_executor(self, node_type: str, executor: Callable):
        """注册任务执行器"""
        self.task_executors[node_type] = executor
    
    def set_rate_limiter(self, key: str, rate: int, interval: timedelta = timedelta(seconds=1)):
        """设置速率限制器"""
        self.rate_limiters[key] = RateLimiter(rate, interval)
    
    # 以下方法在实际实现中需要与存储层交互
    async def _get_node(self, node_id: str, execution_id: str) -> Optional[Node]:
        """获取节点信息"""
        # TODO: 从存储中获取节点信息
        return None
    
    async def _get_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """获取执行信息"""
        # TODO: 从存储中获取执行信息
        return None
    
    async def _get_workflow(self, execution_id: str) -> Optional[Workflow]:
        """获取工作流信息"""
        # TODO: 从存储中获取工作流信息
        return None
    
    def get_scheduler_stats(self) -> Dict[str, Any]:
        """获取调度器统计信息"""
        return {
            "ready_queue_size": len(self.ready_queue),
            "waiting_tasks_count": len(self.waiting_tasks),
            "running_tasks_count": len(self.running_tasks),
            "resource_usage": self.resource_manager.get_usage_stats()
        }
