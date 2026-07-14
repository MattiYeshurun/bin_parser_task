import array
import mmap
import struct
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

    result: Dict[str, List[Tuple[Any, ...]]] = {fmt.name: [] for fmt in formats.values()}
    wanted_set = set(wanted_names) if wanted_names is not None else None

    # Cache local variables and references to reduce global lookup overhead in the hot loop
    struct_error = struct.error
    array_class = array.array
    mapped_len = len(mapped)

    aligned = False
    position = mapped.find(MESSAGE_HEADER, start_offset)
    while position != -1 and position < end_offset:  # TODO check this loop
        if position + 3 > mapped_len:
            break

        if mapped[position : position + 2] == MESSAGE_HEADER:
            type_id = mapped[position + 2]
            message_format = formats.get(type_id)
            if message_format is not None:
                aligned = True
                end_msg = position + message_format.length
                if end_msg > mapped_len:
                    break

                if wanted_set is None or message_format.name in wanted_set:
                    s_obj = message_format.struct_obj
                    if s_obj is not None:
                        try:
                            raw = s_obj.unpack_from(mapped, position + 3)
                        except struct_error as e:
                            logger.error(f"Failed to unpack message '{message_format.name}' at offset {position}: {e}")
                            position = mapped.find(MESSAGE_HEADER, position + 1)
                            continue
                    else:
                        logger.warning(
                            f"Message format '{message_format.name}' (type_id {type_id}) has no struct object defined"
                        )
                        position = mapped.find(MESSAGE_HEADER, position + 1)
                        continue

                    name = message_format.name
                    if message_format.needs_processing:
                        values = list(raw)

                        # String decoding (File Data column is pre-filtered out of string_indices in format_bank)
                        string_indices = message_format.string_indices
                        if string_indices:
                            for idx in string_indices:
                                values[idx] = values[idx].split(b"\0", 1)[0].decode("ISO-8859-1")

                        # Scaling
                        for idx, mul in message_format.scaled_indices:
                            values[idx] *= mul

                        # Array fields
                        array_indices = message_format.array_indices
                        if array_indices:
                            for idx in array_indices:
                                a = array_class("h")
                                a.frombytes(values[idx])
                                values[idx] = a.tolist()

                        msg_tuple = tuple(values)
                    else:
                        msg_tuple = raw

                    result[name].append(msg_tuple)

                # Advance position
                position = end_msg
                continue
            else:
                if aligned:
                    logger.warning(
                        f"Found MESSAGE_HEADER at offset {position} but type_id {type_id} is unregistered/unknown"
                    )

        position = mapped.find(MESSAGE_HEADER, position + 1)

    return result


def multiprocessing_byte_worker(args: Tuple[Path, int, int, Optional[Set[str]]]) -> Dict[str, List[Tuple[Any, ...]]]:
    """Multiprocessing entry point for byte range worker."""
    file_path, start_offset, end_offset, wanted_names = args
    formats = load_message_formats(file_path)
    with file_path.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            return parse_bytes_to_dict(mapped, start_offset, end_offset, formats, wanted_names)
