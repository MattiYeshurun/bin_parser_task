import array
import mmap
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.business_logic.format_bank import load_message_formats
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

    # ── Pre-computation: format lookup table and pre-allocated buffers ──
    format_table: list = [None] * 256
    name_to_fmt: Dict[str, MessageFormat] = {}
    raw_buffers: Dict[str, bytearray] = {}
    wanted_ids: Optional[Set[int]] = set() if wanted_set is not None else None
    for tid, fmt in formats.items():
        format_table[tid] = fmt
        name_to_fmt[fmt.name] = fmt
        if wanted_set is None or fmt.name in wanted_set:
            raw_buffers[fmt.name] = bytearray()
            if wanted_ids is not None:
                wanted_ids.add(tid)

    # ── Pre-computation: wanted type IDs for multi-type targeted search ──
    wanted_ids: Optional[Set[int]] = None
    if wanted_set is not None:
        wanted_ids = {tid for tid, fmt in formats.items() if fmt.name in wanted_set}

    # Always search for the general MESSAGE_HEADER to ensure sequential parsing sequence
    # and avoid false matches inside other message payloads.
    search_header = MESSAGE_HEADER

    # ── Cache local references for hot loop performance ──
    mapped_len = len(mapped)
    mapped_find = mapped.find
    _MESSAGE_HEADER = MESSAGE_HEADER

    position = mapped_find(search_header, start_offset)
    while position != -1 and position < end_offset:
        if position + 3 > mapped_len:
            break

        if mapped[position : position + 2] == _MESSAGE_HEADER:
            type_id = mapped[position + 2]
            fmt = format_table[type_id]
            if fmt is not None:
                end_msg = position + fmt.length
                if end_msg > mapped_len:
                    break

                if wanted_ids is None or type_id in wanted_ids:
                    s_obj = fmt.struct_obj
                    if s_obj is not None:
                        stride = s_obj.size
                        if position + 3 + stride > mapped_len:
                            logger.warning(
                                f"Message '{fmt.name}' at offset {position} is truncated (extends beyond mapped length)"
                            )
                            break
                        raw_buffers[fmt.name].extend(mapped[position + 3 : position + 3 + stride])
                    else:
                        logger.warning(f"Message format '{fmt.name}' (type_id {type_id}) has no struct object defined")
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
            result[name] = list(s_obj.iter_unpack(buf))
        else:
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

    total_parsed = sum(len(b) for b in result.values())
    logger.debug(f"parse_bytes_to_dict: parsed {total_parsed:,} messages in range {start_offset} to {end_offset}.")

    return result


def multiprocessing_byte_worker(args: Tuple[Path, int, int, Optional[Set[str]]]) -> Dict[str, List[Tuple[Any, ...]]]:
    """Multiprocessing entry point for byte range worker with safe boundary alignment."""

    file_path, start_offset, end_offset, wanted_names = args

    formats = load_message_formats(file_path)
    file_size = file_path.stat().st_size

    with file_path.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            # --- 1. Align Start Offset ---
            # If not the first chunk, skip partial message bytes and align to next valid header
            if start_offset > 0:
                aligned_start = start_offset
                while aligned_start < file_size:
                    if aligned_start + 2 < file_size and mapped[aligned_start : aligned_start + 2] == MESSAGE_HEADER:
                        msg_type = mapped[aligned_start + 2]
                        if msg_type in formats:
                            break  # Valid recognized message start found
                    aligned_start += 1
                start_offset = aligned_start

            # --- 2. Align End Offset (Over-reading) ---
            # Extend end_offset dynamically to include the full trailing message of this chunk
            aligned_end = end_offset
            if aligned_end < file_size:
                while aligned_end < file_size:
                    if aligned_end + 2 < file_size and mapped[aligned_end : aligned_end + 2] == MESSAGE_HEADER:
                        msg_type = mapped[aligned_end + 2]
                        if msg_type in formats:
                            break  # Start of next chunk's first message found
                    aligned_end += 1
                end_offset = aligned_end

            logger.debug(f"Worker processing aligned chunk {start_offset:,} to {end_offset:,} on {file_path.name}")
            res = parse_bytes_to_dict(mapped, start_offset, end_offset, formats, wanted_names)
            return res
