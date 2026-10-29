"""Thread-safe single-slot frame buffers.

A surveillance pipeline must never grow without bound. Instead of a queue we use
a "latest frame wins" buffer: producers overwrite the slot, consumers take the
newest item and count how many frames were skipped. Memory therefore stays at
exactly one frame per stage, no matter how slow inference is.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


class LatestBuffer(Generic[T]):
    """A one-slot buffer with a condition variable for blocking consumers."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._item: Optional[T] = None
        self._seq = 0
        self._dropped = 0
        self._closed = False

    def put(self, item: T) -> None:
        with self._cond:
            if self._item is not None:
                self._dropped += 1
            self._item = item
            self._seq += 1
            self._cond.notify_all()

    def get_nowait(self) -> Optional[T]:
        with self._cond:
            item, self._item = self._item, None
            return item

    def wait_get(self, timeout: float = 0.1) -> Optional[T]:
        """Block until a frame is available or ``timeout`` elapses."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._item is None and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
            item, self._item = self._item, None
            return item

    def peek(self) -> Optional[T]:
        with self._cond:
            return self._item

    def clear(self) -> None:
        with self._cond:
            self._item = None

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def reopen(self) -> None:
        with self._cond:
            self._closed = False

    @property
    def dropped(self) -> int:
        with self._cond:
            return self._dropped

    @property
    def sequence(self) -> int:
        with self._cond:
            return self._seq

    def reset_counters(self) -> None:
        with self._cond:
            self._dropped = 0


@dataclass
class FramePacket:
    """A raw decoded frame travelling from capture to inference."""

    index: int
    timestamp: float
    frame: Any  # numpy.ndarray, BGR
    position_s: float = 0.0
    duration_s: float = 0.0
    source_fps: float = 0.0


@dataclass
class ProcessedFrame:
    """An annotated frame plus everything the interface needs to describe it."""

    index: int
    timestamp: float
    image: Any  # QImage, owned by the buffer
    detections: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
