"""Scoped, bounded reference memory with correction, expiry, and deletion semantics."""

from collections import OrderedDict
from dataclasses import dataclass
import math
import time
from typing import Callable


@dataclass(frozen=True)
class MemoryValue:
    value: str
    version: int
    expires_at: float


class ScopedMemory:
    def __init__(self, *, capacity: int = 128, clock: Callable[[], float] = time.monotonic):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity, self.clock = capacity, clock
        self._values: OrderedDict[tuple[str, str, str], MemoryValue] = OrderedDict()
        self._sequence = 0

    @staticmethod
    def _key(tenant: str, user: str, key: str):
        if any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in (tenant, user, key)):
            raise ValueError("memory scope and key must be nonempty, bounded strings")
        return tenant, user, key

    def _expire(self):
        now = self.clock()
        for key in list(self._values):
            if self._values[key].expires_at <= now:
                del self._values[key]

    def put(self, tenant: str, user: str, key: str, value: str, *, ttl: float = 300) -> MemoryValue:
        scoped = self._key(tenant, user, key)
        if not isinstance(value, str) or len(value) > 4000 or type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("memory requires a bounded text value and positive finite TTL")
        self._expire()
        self._sequence += 1
        entry = MemoryValue(value, self._sequence, self.clock() + ttl)
        self._values[scoped] = entry
        self._values.move_to_end(scoped)
        while len(self._values) > self.capacity:
            self._values.popitem(last=False)
        return entry

    def get(self, tenant: str, user: str, key: str) -> MemoryValue | None:
        scoped = self._key(tenant, user, key)
        self._expire()
        return self._values.get(scoped)

    def forget(self, tenant: str, user: str, key: str) -> bool:
        return self._values.pop(self._key(tenant, user, key), None) is not None
