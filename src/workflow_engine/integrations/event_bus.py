"""
事件总线集成
"""
import asyncio
from typing import Dict, Any, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging


logger = logging.getLogger(__name__)


@dataclass
class Event:
    """事件对象"""
    topic: str
    payload: Any
    timestamp: datetime = field(default_factory=datetime.utcnow)
    headers: Dict[str, str] = field(default_factory=dict)


class EventBus:
    """事件总线接口"""
    
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self._lock = asyncio.Lock()
    
    async def publish(self, topic: str, payload: Any, headers: Dict[str, str] = None):
        """发布事件"""
        event = Event(
            topic=topic,
            payload=payload,
            headers=headers or {}
        )
        
        # 获取订阅者
        async with self._lock:
            subscribers = self.subscribers.get(topic, [])
        
        # 异步通知所有订阅者
        tasks = []
        for subscriber in subscribers:
            task = asyncio.create_task(self._notify_subscriber(subscriber, event))
            tasks.append(task)
        
        # 等待所有通知完成
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.debug(f"Published event to topic '{topic}' with {len(subscribers)} subscribers")
    
    async def subscribe(self, topic: str, handler: Callable):
        """订阅事件"""
        async with self._lock:
            if topic not in self.subscribers:
                self.subscribers[topic] = []
            self.subscribers[topic].append(handler)
        
        logger.info(f"Subscribed to topic '{topic}'")
    
    async def unsubscribe(self, topic: str, handler: Callable):
        """取消订阅"""
        async with self._lock:
            if topic in self.subscribers:
                self.subscribers[topic].remove(handler)
                if not self.subscribers[topic]:
                    del self.subscribers[topic]
        
        logger.info(f"Unsubscribed from topic '{topic}'")
    
    async def _notify_subscriber(self, subscriber: Callable, event: Event):
        """通知订阅者"""
        try:
            if asyncio.iscoroutinefunction(subscriber):
                await subscriber(event)
            else:
                subscriber(event)
        except Exception as e:
            logger.error(f"Error notifying subscriber for topic '{event.topic}': {e}", exc_info=True)


class KafkaEventBus(EventBus):
    """Kafka事件总线实现"""
    
    def __init__(self, bootstrap_servers: str, group_id: str = "workflow-engine"):
        super().__init__()
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.producer = None
        self.consumer = None
        self._consumer_task = None
    
    async def start(self):
        """启动Kafka连接"""
        # TODO: 初始化Kafka生产者和消费者
        pass
    
    async def stop(self):
        """停止Kafka连接"""
        # TODO: 关闭Kafka连接
        pass
    
    async def publish(self, topic: str, payload: Any, headers: Dict[str, str] = None):
        """发布事件到Kafka"""
        # 序列化payload
        if isinstance(payload, dict):
            value = json.dumps(payload).encode('utf-8')
        elif isinstance(payload, str):
            value = payload.encode('utf-8')
        else:
            value = str(payload).encode('utf-8')
        
        # TODO: 发送到Kafka
        
        # 同时通知本地订阅者
        await super().publish(topic, payload, headers)


class NATSEventBus(EventBus):
    """NATS事件总线实现"""
    
    def __init__(self, servers: List[str]):
        super().__init__()
        self.servers = servers
        self.nc = None
        self.js = None
    
    async def start(self):
        """启动NATS连接"""
        # TODO: 初始化NATS连接
        pass
    
    async def stop(self):
        """停止NATS连接"""
        # TODO: 关闭NATS连接
        pass
    
    async def publish(self, topic: str, payload: Any, headers: Dict[str, str] = None):
        """发布事件到NATS"""
        # TODO: 发送到NATS
        
        # 同时通知本地订阅者
        await super().publish(topic, payload, headers)
