"""Simple monitoring utilities for the workflow engine."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Dict, Iterable, Optional


class MetricsRecorder:
    """In-memory metrics recorder used for tests and demo deployments."""

    def __init__(self) -> None:
        self.counters: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.histograms: Dict[str, Dict[str, Iterable[float]]] = defaultdict(dict)

    def inc(self, name: str, labels: Optional[Dict[str, str]] = None, value: float = 1) -> None:
        labels_key = self._labels_key(labels)
        self.counters[name][labels_key] += value

    def observe(
        self, name: str, value: float, labels: Optional[Dict[str, str]] = None
    ) -> None:
        labels_key = self._labels_key(labels)
        bucket = self.histograms[name].setdefault(labels_key, [])
        bucket.append(value)

    def get_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        labels_key = self._labels_key(labels)
        return self.counters[name].get(labels_key, 0.0)

    def _labels_key(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return "__no_labels__"
        sorted_items = sorted(labels.items())
        return "|".join(f"{k}={v}" for k, v in sorted_items)


class TracingManager:
    """Very small tracing helper producing structured logs."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("workflow.tracing")

    @contextmanager
    def span(self, name: str, **attrs: str):
        start = time.time()
        self.logger.debug("Span start", extra={"span": name, **attrs})
        try:
            yield
        finally:
            duration = time.time() - start
            self.logger.debug(
                "Span end", extra={"span": name, "duration": duration, **attrs}
            )


class EventLogger:
    """Structured event logger for workflow executions."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("workflow.events")

    def log(self, event: str, **payload: str) -> None:
        self.logger.info(event, extra=payload)
