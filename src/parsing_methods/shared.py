import array
import mmap
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config.constants import MESSAGE_HEADER
from src.config.logging_config import get_logger
from src.models.bin_messages import MessageFormat

logger = get_logger(__name__)


def merge_dicts(dict_list: List[Dict[str, List[Any]]]) -> Dict[str, List[Any]]:
    """Merges a list of dictionaries with list values by extending lists for matching keys."""
    if not dict_list:
        return {}
    merged = dict_list[0]
    for d in dict_list[1:]:
        for k, v in d.items():
            if v:
                if k in merged:
                    merged[k].extend(v)
                else:
                    merged[k] = v
    return merged


def parse_bytes_to_dict(
    mapped: mmap.mmap | bytes,
    start_offset: int,
    end_offset: int,
    formats: Dict[int, MessageFormat],
    wanted_names: Optional[List[str] | Set[str]] = None,
) -> Dict[str, List[Tuple[Any, ...]]]:

    wanted_set = set(wanted_names) if wanted_names is not None else None

    # ── Pre-computation: format lookup table (list[256] instead of dict.get) ──
    format_table: list = [None] * 256
    name_to_fmt: Dict[str, MessageFormat] = {}
    for tid, fmt in formats.items():
        format_table[tid] = fmt
        name_to_fmt[fmt.name] = fmt

    # ── Pre-computation: wanted type IDs for multi-type targeted search ──
    wanted_ids: Optional[Set[int]] = None
    if wanted_set is not None:
        wanted_ids = {tid for tid, fmt in formats.items() if fmt.name in wanted_set}

    # Targeted search optimization for single wanted message type
    search_header = MESSAGE_HEADER
    if wanted_ids is not None and len(wanted_ids) == 1:
        search_header = MESSAGE_HEADER + bytes([next(iter(wanted_ids))])

    # ── Cache local references for hot loop performance ──
    mapped_len = len(mapped)
    mapped_find = mapped.find
    _MESSAGE_HEADER = MESSAGE_HEADER

    raw_buffers: Dict[str, bytearray] = {}
    msg_counts: Dict[str, int] = {}

    position = mapped_find(search_header, start_offset)
    while position != -1 and position < end_offset:
        if position + 3 > mapped_len:
            break

        if mapped[position : position + 2] == _MESSAGE_HEADER:
            type_id = mapped[position + 2]
            fmt = format_table[type_id]
            if fmt is not None:
                msg_length = fmt.length
                end_msg = position + msg_length
                if end_msg > mapped_len:
                    break

                if wanted_ids is None or type_id in wanted_ids:
                    s_obj = fmt.struct_obj
                    if s_obj is not None:
                        name = fmt.name
                        stride = s_obj.size
                        if name in raw_buffers:
                            raw_buffers[name].extend(mapped[position + 3 : position + 3 + stride])
                            msg_counts[name] += 1
                        else:
                            raw_buffers[name] = bytearray(mapped[position + 3 : position + 3 + stride])
                            msg_counts[name] = 1
                    else:
                        logger.warning(
                            f"Message format '{fmt.name}' (type_id {type_id}) has no struct object defined"
                        )
                        position = mapped_find(_MESSAGE_HEADER, position + 1)
                        continue

                # Advance position past this message
                position = mapped_find(search_header, end_msg)
                continue

        position = mapped_find(search_header, position + 1)

    array_class = array.array
    result: Dict[str, List[Tuple[Any, ...]]] = {}

    for name, buf in raw_buffers.items():
        fmt = name_to_fmt[name]
        s_obj = fmt.struct_obj

        if not fmt.needs_processing:
            # Fast path: C-level batch unpack via iter_unpack
            result[name] = list(s_obj.iter_unpack(buf))
        else:
            # Slow path: unpack + per-message processing
            string_indices = fmt.string_indices
            scaled_indices = fmt.scaled_indices
            array_indices = fmt.array_indices
            rows = []
            rows_append = rows.append
            for raw in s_obj.iter_unpack(buf):
                values = list(raw)

                # String decoding (FILE Data column pre-filtered in format_bank)
                if string_indices:
                    for idx in string_indices:
                        values[idx] = values[idx].partition(b"\0")[0].decode("ISO-8859-1")

                # Scaling
                for idx, mul in scaled_indices:
                    values[idx] *= mul

                # Array fields
                if array_indices:
                    for idx in array_indices:
                        a = array_class("h")
                        a.frombytes(values[idx])
                        values[idx] = a.tolist()

                rows_append(tuple(values))
            result[name] = rows

    # Add empty lists for message types not found in this chunk
    for fmt in formats.values():
        if wanted_set is None or fmt.name in wanted_set:
            if fmt.name not in result:
                result[fmt.name] = []

    return result


def multiprocessing_byte_worker(args: Tuple[Path, int, int, Optional[Set[str]]]) -> Dict[str, List[Tuple[Any, ...]]]:
    """Multiprocessing entry point for byte range worker."""
    from src.business_logic.format_bank import load_message_formats
    file_path, start_offset, end_offset, wanted_names = args
    formats = load_message_formats(file_path)
    with file_path.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            return parse_bytes_to_dict(mapped, start_offset, end_offset, formats, wanted_names)
