from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import struct


@dataclass
class MessageFormat:
    type_id: int
    length: int
    name: str
    format_string: str
    columns: List[str]
    struct_obj: struct.Struct = field(repr=False, default=None)  # type: ignore[assignment]
    multipliers: List[Optional[float]] = field(repr=False, default_factory=list)
    string_indices: List[int] = field(repr=False, default_factory=list)
    array_a_indices: List[int] = field(repr=False, default_factory=list)


@dataclass
class Message:
    type_id: int
    name: str
    fields: Dict[str, Any]


@dataclass
class BenchmarkResult:
    method: str
    message_count: int
    elapsed_seconds: float

    @property
    def messages_per_second(self) -> float:
        return self.message_count / max(self.elapsed_seconds, 1e-9)
