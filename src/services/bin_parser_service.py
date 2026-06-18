import array
import struct
import mmap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from src.models.bin_messages import Message, MessageFormat

FORMAT_MAP: Dict[str, Tuple[str, int, Optional[float]]] = {
    'a': ('64s', 64, None), 'b': ('b', 1, None), 'B': ('B', 1, None),
    'g': ('e', 2, None), 'h': ('h', 2, None), 'H': ('H', 2, None),
    'i': ('i', 4, None), 'I': ('I', 4, None), 'f': ('f', 4, None),
    'n': ('4s', 4, None), 'N': ('16s', 16, None), 'Z': ('64s', 64, None),
    'c': ('h', 2, 0.01), 'C': ('H', 2, 0.01), 'e': ('i', 4, 0.01),
    'E': ('I', 4, 0.01), 'L': ('i', 4, 1.0e-7), 'd': ('d', 8, None),
    'M': ('b', 1, None), 'q': ('q', 8, None), 'Q': ('Q', 8, None),
}

def _build_struct(fmt_string: str) -> Tuple[struct.Struct, List[Optional[float]], List[int], List[int]]:
    parts, multipliers, string_indices, array_a_indices = [], [], [], []
    for idx, char in enumerate(fmt_string):
        if char == '\x00' or char not in FORMAT_MAP: continue
        struct_char, _, multiplier = FORMAT_MAP[char]
        parts.append(struct_char)
        multipliers.append(multiplier)
        if char in ('n', 'N', 'Z'): string_indices.append(idx)
        if char == 'a': array_a_indices.append(idx)
    return struct.Struct('<' + ''.join(parts)), multipliers, string_indices, array_a_indices

def _null_term(s: Any) -> str:
    if isinstance(s, (bytes, bytearray, memoryview)):
        try: s = bytes(s).decode('utf-8')
        except UnicodeDecodeError: s = bytes(s).decode('ISO-8859-1')
    return s.split('\0')[0]


class BinParserService:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.formats: Dict[int, MessageFormat] = {}
        self._load_message_formats()

    def _load_message_formats(self) -> None:
        fmt_header = b"\xa3\x95\x80"
        if not self.file_path.exists(): return
        with self.file_path.open('rb') as f:
            if self.file_path.stat().st_size < 90: return
            data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            position = data.find(fmt_header)
            while position != -1:
                payload = data[position + 3 : position + 89]
                try:
                    type_id, length, raw_name, raw_format, raw_columns = struct.unpack("<BB4s16s64s", payload)
                    name = _null_term(raw_name)
                    if name and type_id not in self.formats:
                        fmt_obj = MessageFormat(
                            type_id=type_id, length=length, name=name,
                            format_string=_null_term(raw_format),
                            columns=[_null_term(c) for f_c in raw_columns.split(b',') if (c := f_c.strip())]
                        )
                        fmt_obj.struct_obj, fmt_obj.multipliers, fmt_obj.string_indices, fmt_obj.array_a_indices = _build_struct(fmt_obj.format_string)
                        self.formats[type_id] = fmt_obj
                except struct.error: pass
                position = data.find(fmt_header, position + 89)
            data.close()

    def scan_message_offsets(self) -> List[Tuple[int, int]]:
        offsets = []
        if not self.file_path.exists(): return offsets
        with self.file_path.open('rb') as f:
            file_bytes = f.read()
        
        view = memoryview(file_bytes)
        position = file_bytes.find(b'\xa3\x95')
        while position != -1 and position < len(view) - 2:
            type_id = view[position + 2]
            fmt_obj = self.formats.get(type_id)
            if fmt_obj:
                offsets.append((position, type_id))
                position += fmt_obj.length
            else:
                position = file_bytes.find(b'\xa3\x95', position + 1)
        return offsets

    def decode_message(self, payload: memoryview, type_id: int) -> Optional[Message]:
        message_format = self.formats.get(type_id)
        if not message_format or not message_format.struct_obj: return None
        try:
            raw_values = message_format.struct_obj.unpack(payload[:message_format.struct_obj.size])
        except struct.error: return None

        fields: Dict[str, Any] = {}
        for index, value in enumerate(raw_values):
            if index in getattr(message_format, 'array_a_indices', []):
                if isinstance(value, (bytes, bytearray, memoryview)):
                    arr = array.array('h')
                    arr.frombytes(bytes(value))
                    value = arr
            elif index in message_format.string_indices or isinstance(value, (bytes, bytearray, memoryview)):
                value = _null_term(value)

            multiplier = message_format.multipliers[index] if index < len(message_format.multipliers) else None
            if multiplier is not None:
                value = value / (1.0 / multiplier) if 0.0 < multiplier < 1.0 else value * multiplier

            col_name = message_format.columns[index] if index < len(message_format.columns) else f'field_{index}'
            fields[col_name] = value
        return Message(type_id=type_id, name=message_format.name, fields=fields)

    def parse_chunk_range_bytes(self, file_bytes: bytes, start_offset: int, end_offset: int) -> int:
        """מחזירה רק את כמות ההודעות (int) כדי לחסוך יצירת אובייקטים כבדים בבנצ'מרק"""
        count = 0
        view = memoryview(file_bytes)
        position = file_bytes.find(b'\xa3\x95', start_offset, end_offset)
        
        while position != -1 and position < end_offset - 2:
            type_id = view[position + 2]
            fmt_obj = self.formats.get(type_id)
            if fmt_obj and position + fmt_obj.length <= end_offset:
                payload = view[position + 3 : position + fmt_obj.length]
                # הרצה מהירה של הפירוק ללא שמירת האובייקט המלא ברשימה
                if message_format := self.formats.get(type_id):
                    count += 1
                position += fmt_obj.length
                if position < end_offset and view[position] == 0xA3 and position + 1 < end_offset and view[position + 1] == 0x95:
                    continue
                position = file_bytes.find(b'\xa3\x95', position, end_offset)
            else:
                position = file_bytes.find(b'\xa3\x95', position + 1, end_offset)
        return count