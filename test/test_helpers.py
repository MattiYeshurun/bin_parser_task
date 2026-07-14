from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from src.config.constants import MESSAGE_HEADER
from src.models.bin_messages import Message, MessageFormat
from src.parsing_methods.shared import parse_bytes_to_dict

def decode_message(
    buffer: Any,
    offset: int,
    type_id: int,
    formats: Dict[int, MessageFormat],
    timebase_info: Optional[Tuple[float, int, bool]] = None,
) -> Optional[Message]:
    """Decodes a single message from the buffer using the unified parsing core."""
    
    message_format = formats.get(type_id)
    if not message_format:
        return None

    frame = MESSAGE_HEADER + bytes([type_id]) + bytes(buffer[offset : offset + message_format.length - 3])
    
    result = parse_bytes_to_dict(
        frame, 0, len(frame), formats, wanted_names=[message_format.name], timebase_info=timebase_info, limit=1
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
