from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Dict

from src.business_logic.bank_manager import parse_log_formats
from src.utils.constants import (
    GPS_COORDINATE_SCALE,
    HEADER_SKIP_BYTES_COUNT,
    MSG_HEADER_BYTES,
)


def parse_flight_data(
    file_path: str | Path,
    target_msg_name: str = "GPS",
    chunk_size: int = 65536,
) -> Dict[int, Dict[str, Any]]:
    bank = parse_log_formats(file_path)

    target_type = None
    for message_type, info in bank.items():
        if info["name"] == target_msg_name:
            target_type = message_type
            break

    if target_type is None:
        print(f"Error: Message type '{target_msg_name}' not found in dynamic bank.")
        return {}

    print(
        f"Parsing messages of type '{target_msg_name}' (type ID {target_type})...\n"
    )

    parsed_messages: Dict[int, Dict[str, Any]] = {}
    max_msg_len = max(info["msg_len"] for info in bank.values())
    overlap_size = max_msg_len + 1

    buffer = b""
    file_offset = 0

    with open(file_path, "rb") as file_handle:
        while True:
            chunk = file_handle.read(chunk_size)
            if not chunk and not buffer:
                break

            buffer += chunk
            location = buffer.find(MSG_HEADER_BYTES)

            while location != -1:
                if location + 2 >= len(buffer):
                    break

                current_type = buffer[location + 2]

                if current_type == target_type:
                    msg_info = bank[target_type]
                    msg_len = msg_info["msg_len"]

                    if location + msg_len > len(buffer):
                        break

                    msg_bytes = buffer[location : location + msg_len]
                    fmt = f"<{HEADER_SKIP_BYTES_COUNT}x" + msg_info["format"].replace("<", "")
                    unpacked_data = struct.unpack(fmt, msg_bytes)

                    if (
                        target_msg_name == "FMT"
                        and not unpacked_data[2]
                        .decode("ascii", errors="ignore")
                        .strip("\x00 ")
                        .isalnum()
                    ):
                        return parsed_messages

                    current_msg_dict: Dict[str, Any] = {}
                    for column, value in zip(msg_info["columns"], unpacked_data):
                        if isinstance(value, bytes):
                            value = value.decode("ascii", errors="ignore").strip("\x00 ").strip()
                        if column in ["Lat", "Lng"] and isinstance(value, int):
                            value = value / GPS_COORDINATE_SCALE
                        current_msg_dict[column] = value

                    absolute_location = file_offset + location
                    parsed_messages[absolute_location] = current_msg_dict
                    location = buffer.find(MSG_HEADER_BYTES, location + msg_len)
                    continue

                location = buffer.find(MSG_HEADER_BYTES, location + 1)

            if len(buffer) > overlap_size:
                bytes_to_keep = overlap_size
                file_offset += len(buffer) - bytes_to_keep
                buffer = buffer[-bytes_to_keep:]

    return parsed_messages