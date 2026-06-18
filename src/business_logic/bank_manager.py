from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Dict

from src.utils.constants import FMT_TYPE_ID, MSG_HEADER_BYTES


def parse_log_formats(file_path: str | Path) -> Dict[int, Dict[str, Any]]:
    format_bank: Dict[int, Dict[str, Any]] = {}
    fmt_msg_len = 89
    fmt_struct_format = "<3xBB4s16s64s"

    with open(file_path, "rb") as file_handle:
        data = file_handle.read()

    location = data.find(MSG_HEADER_BYTES)

    while location != -1:
        if location + 2 >= len(data):
            break

        current_type = data[location + 2]

        if current_type == FMT_TYPE_ID:
            msg_bytes = data[location : location + fmt_msg_len]

            if len(msg_bytes) == fmt_msg_len:
                unpacked = struct.unpack(fmt_struct_format, msg_bytes)
                type_id = unpacked[0]
                msg_len = unpacked[1]

                name = unpacked[2].decode("ascii", errors="ignore").strip("\x00 ").strip()
                format_str = unpacked[3].decode("ascii", errors="ignore").strip("\x00 ").strip()
                columns_raw = unpacked[4].decode("ascii", errors="ignore").strip("\x00 ").strip()

                if not name:
                    location = data.find(MSG_HEADER_BYTES, location + 1)
                    continue

                columns_list = [column.strip() for column in columns_raw.split(",") if column.strip()]
                format_bank[type_id] = {
                    "name": name,
                    "format": "<" + format_str,
                    "columns": columns_list,
                    "msg_len": msg_len,
                }

            location = data.find(MSG_HEADER_BYTES, location + fmt_msg_len)
            continue

        location = data.find(MSG_HEADER_BYTES, location + 1)

    return format_bank