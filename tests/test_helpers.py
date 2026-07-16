from __future__ import annotations

import mmap
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.config.constants import MESSAGE_HEADER
from src.models.bin_messages import Message, MessageFormat
from src.parsing_methods.shared import parse_bytes_to_dict


def scan_message_offsets(file_path: Path, formats: Dict[int, MessageFormat]) -> List[Tuple[int, int]]:
    """Scans a BIN file and returns a list of (offset, type_id) for every valid message."""
    offsets = []
    with file_path.open('rb') as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            position = mapped.find(MESSAGE_HEADER)
            while position != -1 and position < len(mapped) - 2:
                type_id = mapped[position + 2]
                fmt_obj = formats.get(type_id)
                if fmt_obj and fmt_obj.length > 0:
                    offsets.append((position, type_id))
                    position += fmt_obj.length
                else:
                    position += 1
                position = mapped.find(MESSAGE_HEADER, position)
    return offsets

def decode_message(
    buffer: Any,
    offset: int,
    type_id: int,
    formats: Dict[int, MessageFormat],
) -> Optional[Message]:
    """Decodes a single message from the buffer using the unified parsing core."""
    
    message_format = formats.get(type_id)
    if not message_format:
        return None

    frame = MESSAGE_HEADER + bytes([type_id]) + bytes(buffer[offset : offset + message_format.length - 3])
    
    result = parse_bytes_to_dict(
        frame, 0, len(frame), formats, wanted_names=[message_format.name]
    )
    
    messages = result.get(message_format.name, [])
    if messages:
        row = messages[0]
        cols = message_format.columns
        if len(row) > len(cols):
            cols = list(cols) + ['timestamp']
        fields_dict = dict(zip(cols, row))
        return Message(type_id=type_id, name=message_format.name, fields=fields_dict)
    return None
