from __future__ import annotations

import mmap
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config.constants import BINARY_Z_FIELDS, FMT_MESSAGE_SIZE, FMT_PAYLOAD_STRUCT, FMT_TYPE_ID, MESSAGE_HEADER
from src.config.logging_config import get_logger
from src.models.bin_messages import MessageFormat

logger = get_logger(__name__)

FORMAT_MAP: Dict[str, Tuple[str, int, Optional[float]]] = {
    "a": ("64s", 64, None),
    "b": ("b", 1, None),
    "B": ("B", 1, None),
    "g": ("e", 2, None),
    "h": ("h", 2, None),
    "H": ("H", 2, None),
    "i": ("i", 4, None),
    "I": ("I", 4, None),
    "f": ("f", 4, None),
    "n": ("4s", 4, None),
    "N": ("16s", 16, None),
    "Z": ("64s", 64, None),
    "c": ("h", 2, 0.01),
    "C": ("H", 2, 0.01),
    "e": ("i", 4, 0.01),
    "E": ("I", 4, 0.01),
    "L": ("i", 4, 1.0e-7),
    "d": ("d", 8, None),
    "M": ("b", 1, None),
    "q": ("q", 8, None),
    "Q": ("Q", 8, None),
}


def build_struct(fmt_string: str) -> Tuple[struct.Struct, List[Optional[float]], List[int], List[int]]:
    parts, multipliers, string_indices, array_indices = [], [], [], []
    for idx, char in enumerate(fmt_string):
        if char == "\x00" or char not in FORMAT_MAP:
            continue
        struct_char, _, multiplier = FORMAT_MAP[char]
        parts.append(struct_char)
        multipliers.append(multiplier)
        if char in ("n", "N", "Z"):
            string_indices.append(idx)
        elif char == "a":
            array_indices.append(idx)
    return struct.Struct("<" + "".join(parts)), multipliers, string_indices, array_indices


def null_term(s: bytes) -> str:
    return s.split(b"\0", 1)[0].decode("ascii", errors="ignore").strip()


def create_message_format(
    type_id: int, length: int, raw_name: bytes, raw_format: bytes, raw_columns: bytes
) -> MessageFormat:
    name = null_term(raw_name)
    fmt_obj = MessageFormat(
        type_id=type_id,
        length=length,
        name=name,
        format_string=null_term(raw_format),
        columns=[null_term(c) for c in raw_columns.split(b",") if c.strip()],
    )
    struct_obj, multipliers, string_indices, array_indices = build_struct(fmt_obj.format_string)
    
    # Filter out columns that represent raw binary data (configured in BINARY_Z_FIELDS)
    # so they remain bytes and are not decoded as null-terminated strings.
    for col_idx in list(string_indices):
        if col_idx < len(fmt_obj.columns) and (name, fmt_obj.columns[col_idx]) in BINARY_Z_FIELDS:
            string_indices.remove(col_idx)

    fmt_obj.struct_obj = struct_obj
    fmt_obj.string_indices = string_indices
    fmt_obj.array_indices = array_indices

    # Pre-compute scaled indices
    fmt_obj.scaled_indices = [
        (idx, mult)
        for idx, (char, mult) in enumerate(zip(fmt_obj.format_string, multipliers))
        if mult is not None and char in ("c", "C", "e", "E", "L")
    ]
    fmt_obj.needs_processing = bool(fmt_obj.string_indices or fmt_obj.scaled_indices or fmt_obj.array_indices)
    return fmt_obj


def load_message_formats(file_path: Path) -> Dict[int, MessageFormat]:
    formats: Dict[int, MessageFormat] = {}
    fmt_header = MESSAGE_HEADER + bytes([FMT_TYPE_ID])

    if not file_path.exists():
        logger.warning(f"File {file_path} does not exist.")
        return formats
    if file_path.stat().st_size < FMT_MESSAGE_SIZE + 1:
        return formats

    with file_path.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            position = data.find(fmt_header)
            while position != -1:
                payload = data[position + 3 : position + FMT_MESSAGE_SIZE]
                try:
                    type_id, length, raw_name, raw_format, raw_columns = FMT_PAYLOAD_STRUCT.unpack(payload)
                    if type_id not in formats:
                        fmt_obj = create_message_format(type_id, length, raw_name, raw_format, raw_columns)
                        if fmt_obj.name:
                            formats[type_id] = fmt_obj
                except struct.error:
                    pass
                position = data.find(fmt_header, position + FMT_MESSAGE_SIZE)
    return formats
