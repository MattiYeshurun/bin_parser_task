from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MessageFormat:
    type_id: int
    length: int
    name: str
    format_string: str
    columns: List[str]
    struct_obj: Optional[struct.Struct] = field(repr=False, default=None)
    string_indices: List[int] = field(repr=False, default_factory=list)
    array_indices: List[int] = field(repr=False, default_factory=list)
    timestamp_scale: float = field(repr=False, default=0.0)
    scaled_indices: List[Tuple[int, float]] = field(repr=False, default_factory=list)
    timestamp_index: Optional[int] = field(repr=False, default=None)
    needs_processing: bool = field(repr=False, default=False)


@dataclass(slots=True)
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
