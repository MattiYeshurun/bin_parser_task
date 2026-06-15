"""
bin_parser.py — Parser ו-benchmark לקריאת קובצי ArduPilot BIN
===============================================================

קובץ זה מכיל את כל הלוגיקה שמתקשרת עם פורמט BIN:
  - קריאת מבנה FMT והגדרת סוגי ההודעות
  - פענוח הודעות לפי סוג ופורמט
  - קריאת הודעות GPS בלבד
  - השוואת ביצועים בין שיטות קריאה שונות
  - השוואה ל-pymavlink כ-benchmark חיצוני

המטרה היא להסביר וליישם את המשימות הבאות:
  1. להבין איך BIN מחלק את ההודעות ל-bytes
  2. לקרוא את ההודעות בעצמנו, בלי להשתמש ב-pymavlink
  3. לממש קריאה מקבילה עם ThreadPool, ProcessPool ו-asyncio
  4. להשוות ביצועים מול קריאה עם pymavlink
"""

from __future__ import annotations

import asyncio
import os
import struct
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# הגדרות פורמט BIN בסיסיות
# ---------------------------------------------------------------------------

# שני בתים קבועים שמצביעים על תחילת הודעה
HEADER_MAGIC = b'\xa3\x95'

# מזהה סוג עבור הודעות FMT (כל ההגדרות של מבנה ההודעות)
FMT_TYPE_ID = 0x80

# גודל הודעת FMT תמיד קבוע: 89 בתים
FMT_MSG_SIZE = 89

# מבנה payload של הודעת FMT לאחר ראש התקן
#   1B type + 1B length + 4B name + 16B format + 64B columns = 86B
FMT_PAYLOAD_STRUCT = struct.Struct('<BB4s16s64s')

# גודל ראש הודעה: 2 בתים של magic + 1 בית של type
HEADER_SIZE = 3

# מיפוי בין תווים פורמט של DataFlash ל-struct ולמכפיל
FORMAT_MAP: Dict[str, Tuple[str, int, Optional[float]]] = {
    'b': ('b',   1, None),       # int8
    'B': ('B',   1, None),       # uint8
    'h': ('h',   2, None),       # int16
    'H': ('H',   2, None),       # uint16
    'i': ('i',   4, None),       # int32
    'I': ('I',   4, None),       # uint32
    'f': ('f',   4, None),       # float32
    'd': ('d',   8, None),       # float64
    'q': ('q',   8, None),       # int64
    'Q': ('Q',   8, None),       # uint64
    'c': ('h',   2, 0.01),       # int16 × 0.01
    'C': ('H',   2, 0.01),       # uint16 × 0.01
    'e': ('i',   4, 0.01),       # int32 × 0.01
    'E': ('I',   4, 0.01),       # uint32 × 0.01
    'L': ('i',   4, 1.0e-7),     # int32 × 1e-7 (latitude/longitude)
    'M': ('B',   1, None),       # uint8 (flight mode)
    'n': ('4s',  4, None),       # 4-char string
    'N': ('16s', 16, None),      # 16-char string
    'Z': ('64s', 64, None),      # 64-char string
    'a': ('32h', 64, None),      # array of 32 int16
}


# ---------------------------------------------------------------------------
# מחלקות נתונים
# ---------------------------------------------------------------------------

@dataclass
class MessageFormat:
    """מתאר את פורמט ההודעה כפי שמוגדר ב-FMT."""
    type_id: int
    length: int
    name: str
    format_string: str
    columns: List[str]
    struct_obj: struct.Struct = field(repr=False, default=None)  # type: ignore[assignment]
    multipliers: List[Optional[float]] = field(repr=False, default_factory=list)
    string_indices: List[int] = field(repr=False, default_factory=list)

    def __post_init__(self) -> None:
        self.struct_obj, self.multipliers, self.string_indices = _build_struct(
            self.format_string
        )


@dataclass
class Message:
    """הודעה אחת מפוענחת מתוך קובץ BIN."""
    type_id: int
    name: str
    fields: Dict[str, Any]


@dataclass
class BenchmarkResult:
    """תוצאה של ריצת benchmark אחת."""
    method: str
    message_count: int
    elapsed_seconds: float

    @property
    def messages_per_second(self) -> float:
        return self.message_count / max(self.elapsed_seconds, 1e-9)


# ---------------------------------------------------------------------------
# פונקציות עזר פנימיות
# ---------------------------------------------------------------------------

def _build_struct(fmt_string: str) -> Tuple[struct.Struct, List[Optional[float]], List[int]]:
    """ממיר מחרוזת פורמט של DataFlash לאובייקט struct.

    מחזיר גם את המכפילים עבור ערכים מיושרים ואת מיקומי השדות המחרוזתיים.
    """
    parts: List[str] = []
    multipliers: List[Optional[float]] = []
    string_indices: List[int] = []
    idx = 0

    for ch in fmt_string:
        if ch not in FORMAT_MAP:
            continue
        struct_ch, _size, mult = FORMAT_MAP[ch]
        parts.append(struct_ch)
        multipliers.append(mult)
        if ch in ('n', 'N', 'Z'):
            string_indices.append(idx)
        idx += 1

    full_fmt = '<' + ''.join(parts)
    return struct.Struct(full_fmt), multipliers, string_indices


def _clean_null_padded(raw: bytes) -> str:
    """מסיר אפסים ('\x00') מסוף מחרוזת וממיר ל-ASCII."""
    return raw.split(b'\x00', 1)[0].decode('ascii', errors='replace')


# ---------------------------------------------------------------------------
# מחלקת BinParser - הקריאה העיקרית של קובץ BIN
# ---------------------------------------------------------------------------

class BinParser:
    """פרסר של קבצי ArduPilot BIN ללא שימוש ב-pymavlink."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.formats: Dict[int, MessageFormat] = {}
        self._parse_fmt_messages()

    def _parse_fmt_messages(self) -> None:
        """קורא את כל הודעות FMT בתחילת הקובץ ומאחסן את הפורמטים."""
        with self.file_path.open('rb') as f:
            while True:
                header = f.read(HEADER_SIZE)
                if len(header) < HEADER_SIZE:
                    break
                if header[:2] != HEADER_MAGIC or header[2] != FMT_TYPE_ID:
                    f.seek(-HEADER_SIZE, 1)
                    break
                payload = f.read(FMT_MSG_SIZE - HEADER_SIZE)
                if len(payload) < FMT_MSG_SIZE - HEADER_SIZE:
                    break
                type_id, length, raw_name, raw_format, raw_columns = (
                    FMT_PAYLOAD_STRUCT.unpack(payload)
                )
                name = _clean_null_padded(raw_name)
                fmt_str = _clean_null_padded(raw_format)
                columns_str = _clean_null_padded(raw_columns)
                columns = [c.strip() for c in columns_str.split(',') if c.strip()]
                try:
                    mf = MessageFormat(
                        type_id=type_id,
                        length=length,
                        name=name,
                        format_string=fmt_str,
                        columns=columns,
                    )
                    self.formats[type_id] = mf
                except struct.error:
                    pass

    def scan_message_offsets(self) -> List[Tuple[int, int]]:
        """סורק את הקובץ ומאחסן את מיקום ההודעות והסוג שלהן."""
        offsets: List[Tuple[int, int]] = []
        file_size = self.file_path.stat().st_size

        with self.file_path.open('rb') as f:
            pos = 0
            while pos < file_size - HEADER_SIZE:
                f.seek(pos)
                header = f.read(HEADER_SIZE)
                if len(header) < HEADER_SIZE:
                    break
                if header[0] == 0xA3 and header[1] == 0x95:
                    type_id = header[2]
                    if type_id in self.formats:
                        offsets.append((pos, type_id))
                        pos += self.formats[type_id].length
                    else:
                        pos += 1
                else:
                    pos += 1

        return offsets

    def decode_message(self, data: bytes, type_id: int) -> Optional[Message]:
        """מפענח הודעה בודדת לפי פורמט ה-FMT המתאים."""
        fmt = self.formats.get(type_id)
        if fmt is None or fmt.struct_obj is None:
            return None

        payload_size = fmt.length - HEADER_SIZE
        if len(data) < payload_size:
            return None

        try:
            raw_values = fmt.struct_obj.unpack(data[:fmt.struct_obj.size])
        except struct.error:
            return None

        fields: Dict[str, Any] = {}
        for i, val in enumerate(raw_values):
            mult = fmt.multipliers[i] if i < len(fmt.multipliers) else None
            if mult is not None:
                val = val * mult
            if i in fmt.string_indices and isinstance(val, (bytes, bytearray)):
                val = _clean_null_padded(val)
            if isinstance(val, tuple):
                val = list(val)
            col_name = fmt.columns[i] if i < len(fmt.columns) else f'field_{i}'
            fields[col_name] = val

        return Message(type_id=type_id, name=fmt.name, fields=fields)

    def parse_all_messages(self) -> List[Message]:
        """קורא את כל ההודעות בקובץ באופן סדרתי, משמאל לימין."""
        messages: List[Message] = []
        file_size = self.file_path.stat().st_size

        with self.file_path.open('rb') as f:
            pos = 0
            while pos < file_size - HEADER_SIZE:
                f.seek(pos)
                header = f.read(HEADER_SIZE)
                if len(header) < HEADER_SIZE:
                    break
                if header[0] != 0xA3 or header[1] != 0x95:
                    pos += 1
                    continue
                type_id = header[2]
                fmt = self.formats.get(type_id)
                if fmt is None:
                    pos += 1
                    continue
                payload_size = fmt.length - HEADER_SIZE
                payload = f.read(payload_size)
                if len(payload) < payload_size:
                    break
                msg = self.decode_message(payload, type_id)
                if msg is not None:
                    messages.append(msg)
                pos += fmt.length

        return messages

    def parse_messages_by_type(self, name: str) -> List[Message]:
        """קורא רק הודעות מסוג ספציפי, כגון GPS."""
        target_ids = {
            tid for tid, fmt in self.formats.items() if fmt.name == name
        }
        if not target_ids:
            print(f"Warning: message type '{name}' not found in FMT definitions.")
            return []

        messages: List[Message] = []
        file_size = self.file_path.stat().st_size

        with self.file_path.open('rb') as f:
            pos = 0
            while pos < file_size - HEADER_SIZE:
                f.seek(pos)
                header = f.read(HEADER_SIZE)
                if len(header) < HEADER_SIZE:
                    break
                if header[0] != 0xA3 or header[1] != 0x95:
                    pos += 1
                    continue
                type_id = header[2]
                fmt = self.formats.get(type_id)
                if fmt is None:
                    pos += 1
                    continue
                payload_size = fmt.length - HEADER_SIZE
                if type_id in target_ids:
                    payload = f.read(payload_size)
                    if len(payload) < payload_size:
                        break
                    msg = self.decode_message(payload, type_id)
                    if msg is not None:
                        messages.append(msg)
                pos += fmt.length

        return messages

    def parse_chunk(self, start_offset: int, end_offset: int) -> List[Message]:
        """קורא קטע מתוך הקובץ, מתאים לקריאה מקבילה."""
        messages: List[Message] = []
        with self.file_path.open('rb') as f:
            pos = start_offset
            while pos < end_offset - HEADER_SIZE:
                f.seek(pos)
                header = f.read(HEADER_SIZE)
                if len(header) < HEADER_SIZE:
                    break
                if header[0] != 0xA3 or header[1] != 0x95:
                    pos += 1
                    continue
                type_id = header[2]
                fmt = self.formats.get(type_id)
                if fmt is None:
                    pos += 1
                    continue
                payload_size = fmt.length - HEADER_SIZE
                payload = f.read(payload_size)
                if len(payload) < payload_size:
                    break
                msg = self.decode_message(payload, type_id)
                if msg is not None:
                    messages.append(msg)
                pos += fmt.length

        return messages

    def get_message_type_summary(self) -> Dict[str, int]:
        """מספק ספירה של כל סוגי ההודעות בקובץ."""
        counts: Dict[str, int] = {}
        file_size = self.file_path.stat().st_size

        with self.file_path.open('rb') as f:
            pos = 0
            while pos < file_size - HEADER_SIZE:
                f.seek(pos)
                header = f.read(HEADER_SIZE)
                if len(header) < HEADER_SIZE:
                    break
                if header[0] != 0xA3 or header[1] != 0x95:
                    pos += 1
                    continue
                type_id = header[2]
                fmt = self.formats.get(type_id)
                if fmt is None:
                    pos += 1
                    continue
                counts[fmt.name] = counts.get(fmt.name, 0) + 1
                pos += fmt.length

        return counts

    def describe(self) -> None:
        """מציג טבלה של כל סוגי ההודעות שמוגדרים ב-FMT."""
        print(f"File: {self.file_path}")
        print(f"Size: {self.file_path.stat().st_size:,} bytes "
              f"({self.file_path.stat().st_size / 1024 / 1024:.1f} MB)")
        print(f"FMT definitions: {len(self.formats)} message types\n")
        print(f"{'Type':>4}  {'Len':>3}  {'Name':<6}  {'Format':<20}  Columns")
        print("-" * 80)
        for tid in sorted(self.formats):
            fmt = self.formats[tid]
            cols = ', '.join(fmt.columns)
            print(f"{fmt.type_id:4d}  {fmt.length:3d}  {fmt.name:<6}  "
                  f"{fmt.format_string:<20}  {cols}")


# ---------------------------------------------------------------------------
# קריאה מקבילה ו-benchmark
# ---------------------------------------------------------------------------

def parse_chunk_worker(args: Tuple[Path, int, int, Dict[int, Tuple[int, str, str, List[str]]]]) -> List[Message]:
    """עובד לכוּנת ProcessPool: טוען פורמטים וקריאת קטע קובץ."""
    file_path, start_offset, end_offset, fmt_data = args
    parser = BinParser.__new__(BinParser)
    parser.file_path = file_path
    parser.formats = {}
    for tid, (length, name, fmt_str, columns) in fmt_data.items():
        try:
            mf = MessageFormat(
                type_id=tid,
                length=length,
                name=name,
                format_string=fmt_str,
                columns=columns,
            )
            parser.formats[tid] = mf
        except struct.error:
            pass
    return parser.parse_chunk(start_offset, end_offset)


def _compute_chunk_boundaries(
    offsets: List[Tuple[int, int]],
    file_size: int,
    num_workers: int,
) -> List[Tuple[int, int]]:
    """חלק את רשימת ההודעות לחלקים מבוססי מיקום, למניעת חלוקה בתוך הודעה."""
    if not offsets or num_workers <= 0:
        return []
    chunk_size = max(1, len(offsets) // num_workers)
    boundaries: List[Tuple[int, int]] = []
    for i in range(num_workers):
        start_idx = i * chunk_size
        if start_idx >= len(offsets):
            break
        start_byte = offsets[start_idx][0]
        if i == num_workers - 1:
            end_byte = file_size
        else:
            next_start = (i + 1) * chunk_size
            end_byte = offsets[next_start][0] if next_start < len(offsets) else file_size
        boundaries.append((start_byte, end_byte))
    return boundaries


def _get_serializable_formats(parser: BinParser) -> Dict[int, Tuple[int, str, str, List[str]]]:
    return {
        tid: (fmt.length, fmt.name, fmt.format_string, fmt.columns)
        for tid, fmt in parser.formats.items()
    }


def parse_sequential(file_path: Path) -> BenchmarkResult:
    """קריאה סדרתית של כל ההודעות בקובץ."""
    start = time.perf_counter()
    parser = BinParser(file_path)
    messages = parser.parse_all_messages()
    elapsed = time.perf_counter() - start
    return BenchmarkResult(
        method="Sequential (custom)",
        message_count=len(messages),
        elapsed_seconds=elapsed,
    )


def parse_threaded(file_path: Path, num_workers: Optional[int] = None) -> BenchmarkResult:
    """קריאה מקבילה באמצעות ThreadPoolExecutor."""
    if num_workers is None:
        num_workers = min(os.cpu_count() or 4, 8)
    start = time.perf_counter()
    parser = BinParser(file_path)
    offsets = parser.scan_message_offsets()
    file_size = file_path.stat().st_size
    boundaries = _compute_chunk_boundaries(offsets, file_size, num_workers)
    all_messages: List[Message] = []
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(parser.parse_chunk, start_off, end_off)
            for start_off, end_off in boundaries
        ]
        for future in futures:
            all_messages.extend(future.result())
    elapsed = time.perf_counter() - start
    return BenchmarkResult(
        method=f"ThreadPool ({num_workers} workers)",
        message_count=len(all_messages),
        elapsed_seconds=elapsed,
    )


def parse_multiprocess(file_path: Path, num_workers: Optional[int] = None) -> BenchmarkResult:
    """קריאה מקבילה באמצעות ProcessPoolExecutor."""
    if num_workers is None:
        num_workers = min(os.cpu_count() or 4, 8)
    start = time.perf_counter()
    parser = BinParser(file_path)
    offsets = parser.scan_message_offsets()
    file_size = file_path.stat().st_size
    boundaries = _compute_chunk_boundaries(offsets, file_size, num_workers)
    fmt_data = _get_serializable_formats(parser)
    args_list = [
        (file_path, start_off, end_off, fmt_data)
        for start_off, end_off in boundaries
    ]
    all_messages: List[Message] = []
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        results = executor.map(parse_chunk_worker, args_list)
        for chunk_messages in results:
            all_messages.extend(chunk_messages)
    elapsed = time.perf_counter() - start
    return BenchmarkResult(
        method=f"ProcessPool ({num_workers} workers)",
        message_count=len(all_messages),
        elapsed_seconds=elapsed,
    )


async def _async_parse_chunk(
    parser: BinParser,
    start_offset: int,
    end_offset: int,
    loop: asyncio.AbstractEventLoop,
) -> List[Message]:
    return await loop.run_in_executor(
        None, parser.parse_chunk, start_offset, end_offset
    )


async def _async_parse_all(file_path: Path, num_workers: int) -> List[Message]:
    parser = BinParser(file_path)
    offsets = parser.scan_message_offsets()
    file_size = file_path.stat().st_size
    boundaries = _compute_chunk_boundaries(offsets, file_size, num_workers)
    loop = asyncio.get_event_loop()
    tasks = [
        _async_parse_chunk(parser, start_off, end_off, loop)
        for start_off, end_off in boundaries
    ]
    results = await asyncio.gather(*tasks)
    all_messages: List[Message] = []
    for chunk in results:
        all_messages.extend(chunk)
    return all_messages


def parse_async(file_path: Path, num_workers: Optional[int] = None) -> BenchmarkResult:
    """קריאה מקבילה באמצעות asyncio והרצת קריאת קטעים ב-thread pool."""
    if num_workers is None:
        num_workers = min(os.cpu_count() or 4, 8)
    start = time.perf_counter()
    all_messages = asyncio.run(_async_parse_all(file_path, num_workers))
    elapsed = time.perf_counter() - start
    return BenchmarkResult(
        method=f"Asyncio ({num_workers} workers)",
        message_count=len(all_messages),
        elapsed_seconds=elapsed,
    )


def run_benchmark(
    method_fn: Callable[[Path], BenchmarkResult],
    file_path: Path,
    runs: int = 3,
    label: Optional[str] = None,
) -> List[BenchmarkResult]:
    results: List[BenchmarkResult] = []
    name = label or method_fn.__name__
    for i in range(runs):
        print(f"  Run {i + 1}/{runs} of {name}...", end=" ", flush=True)
        result = method_fn(file_path)
        results.append(result)
        print(f"{result.elapsed_seconds:.2f}s  ({result.message_count:,} msgs)")
    return results


def parse_with_pymavlink(
    file_path: Path,
    message_type: Optional[str] = None,
) -> Dict[str, Any]:
    """קורא את הקובץ באמצעות pymavlink כדי לקבל benchmark השוואתי."""
    try:
        from pymavlink import mavutil
    except ImportError:
        return {
            'message_count': 0,
            'type_counts': {},
            'elapsed': 0.0,
            'error': 'pymavlink not installed. Run: pip install pymavlink',
        }
    start = time.perf_counter()
    mlog = mavutil.mavlink_connection(str(file_path))
    type_counts: Dict[str, int] = {}
    total = 0
    while True:
        if message_type:
            msg = mlog.recv_match(type=message_type)
        else:
            msg = mlog.recv_match()
        if msg is None:
            break
        msg_type = msg.get_type()
        type_counts[msg_type] = type_counts.get(msg_type, 0) + 1
        total += 1
    elapsed = time.perf_counter() - start
    return {
        'message_count': total,
        'type_counts': type_counts,
        'elapsed': elapsed,
    }


def parse_pymavlink_benchmark(file_path: Path) -> BenchmarkResult:
    result = parse_with_pymavlink(file_path)
    if 'error' in result:
        print(f"  [!] pymavlink error: {result['error']}")
        return BenchmarkResult(
            method="Pymavlink",
            message_count=0,
            elapsed_seconds=0.0,
        )
    return BenchmarkResult(
        method="Pymavlink",
        message_count=result['message_count'],
        elapsed_seconds=result['elapsed'],
    )


def read_gps_messages(file_path: Path) -> List[Message]:
    """קורא ומחזיר את כל ההודעות מסוג GPS."""
    parser = BinParser(file_path)
    return parser.parse_messages_by_type('GPS')


def format_gps_record(msg: Message, index: int) -> str:
    f = msg.fields
    time_us = f.get('TimeUS', 0)
    time_s = time_us / 1_000_000.0 if isinstance(time_us, (int, float)) else 0
    status = f.get('Status', 0)
    num_sats = f.get('NSats', f.get('GMS', 0))
    lat = f.get('Lat', 0.0)
    lng = f.get('Lng', 0.0)
    alt = f.get('Alt', 0.0)
    spd = f.get('Spd', 0.0)
    gcrs = f.get('GCrs', 0.0)
    status_names = {0: 'No Fix', 1: 'No Fix', 2: '2D Fix', 3: '3D Fix',
                    4: 'DGPS', 5: 'RTK Float', 6: 'RTK Fixed'}
    status_str = status_names.get(status, f'Unknown({status})')
    return (
        f"  GPS #{index + 1:>6}  |  "
        f"t={time_s:12.3f}s  |  "
        f"Fix={status_str:<10}  |  "
        f"Sats={num_sats:>2}  |  "
        f"Lat={lat:12.7f}  Lng={lng:12.7f}  |  "
        f"Alt={alt:8.2f}m  |  "
        f"Spd={spd:6.2f}m/s  |  "
        f"Crs={gcrs:6.2f}"
    )


def print_gps_summary(file_path: Path, max_display: int = 20) -> None:
    print(f"{'=' * 80}")
    print(f"  GPS Message Reader — {file_path.name}")
    print(f"{'=' * 80}\n")
    messages = read_gps_messages(file_path)
    if not messages:
        print("  No GPS messages found in this file.")
        return
    print(f"  Total GPS messages: {len(messages):,}\n")
    print(f"  --- First {min(max_display, len(messages))} GPS records ---\n")
    for i, msg in enumerate(messages[:max_display]):
        print(format_gps_record(msg, i))
    if len(messages) > max_display:
        print(f"\n  ... ({len(messages) - max_display:,} more GPS messages)")
    print(f"\n  --- GPS Statistics ---\n")
    lats = [m.fields.get('Lat', 0.0) for m in messages
            if isinstance(m.fields.get('Lat'), (int, float))]
    lngs = [m.fields.get('Lng', 0.0) for m in messages
            if isinstance(m.fields.get('Lng'), (int, float))]
    alts = [m.fields.get('Alt', 0.0) for m in messages
            if isinstance(m.fields.get('Alt'), (int, float))]
    spds = [m.fields.get('Spd', 0.0) for m in messages
            if isinstance(m.fields.get('Spd'), (int, float))]
    if lats:
        print(f"  Latitude  range: {min(lats):12.7f}  ->  {max(lats):12.7f}")
    if lngs:
        print(f"  Longitude range: {min(lngs):12.7f}  ->  {max(lngs):12.7f}")
    if alts:
        print(f"  Altitude  range: {min(alts):8.2f}m  ->  {max(alts):8.2f}m")
    if spds:
        print(f"  Speed     range: {min(spds):6.2f}m/s  ->  {max(spds):6.2f}m/s")
    times = [m.fields.get('TimeUS', 0) for m in messages if isinstance(m.fields.get('TimeUS'), (int, float))]
    if times:
        duration_s = (max(times) - min(times)) / 1_000_000.0
        print(f"  Duration:        {duration_s:.1f}s  ({duration_s / 60:.1f} min)")
        print(f"  Avg GPS rate:    {len(messages) / max(duration_s, 0.001):.1f} msgs/sec")


def print_comparison_table(all_results: Dict[str, List[BenchmarkResult]]) -> None:
    baseline_avg = None
    if "Sequential (custom)" in all_results:
        seq_times = [r.elapsed_seconds for r in all_results["Sequential (custom)"]]
        baseline_avg = sum(seq_times) / len(seq_times)
    print()
    print("=" * 110)
    print(f"  {'Method':<30} | {'Messages':>10} | {'Min(s)':>8} | {'Avg(s)':>8} | "
          f"{'Max(s)':>8} | {'Msgs/sec':>12} | {'Speedup':>8}")
    print("-" * 110)
    for method_name, results in all_results.items():
        if not results:
            continue
        times = [r.elapsed_seconds for r in results]
        counts = [r.message_count for r in results]
        avg_time = sum(times) / len(times)
        avg_count = sum(counts) / len(counts)
        min_time = min(times)
        max_time = max(times)
        msgs_per_sec = avg_count / max(avg_time, 1e-9)
        if baseline_avg and avg_time > 0:
            speedup = baseline_avg / avg_time
            speedup_str = f"{speedup:.2f}x"
        else:
            speedup_str = "1.00x" if method_name == "Sequential (custom)" else "N/A"
        print(f"  {method_name:<30} | {int(avg_count):>10,} | {min_time:>8.2f} | "
              f"{avg_time:>8.2f} | {max_time:>8.2f} | {msgs_per_sec:>12,.0f} | {speedup_str:>8}")
    print("=" * 110)


def generate_bar_chart(all_results: Dict[str, List[BenchmarkResult]], output_path: Optional[Path] = None) -> None:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not available — skipping chart generation)")
        return
    methods = []
    avg_times: List[float] = []
    colors = ['#4C72B0', '#55A868', '#C44E52', '#8172B2', '#CCB974']
    for name, results in all_results.items():
        if results and results[0].message_count > 0:
            methods.append(name)
            times = [r.elapsed_seconds for r in results]
            avg_times.append(sum(times) / len(times))
    if not methods:
        return
    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.barh(methods, avg_times, color=colors[:len(methods)], edgecolor='white', height=0.6)
    for bar, t in zip(bars, avg_times):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                f'{t:.2f}s', va='center', fontsize=11, fontweight='bold')
    ax.set_xlabel('Time (seconds)', fontsize=12)
    ax.set_title('BIN File Parsing — Method Comparison', fontsize=14, fontweight='bold')
    ax.invert_yaxis()
    ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    save_path = output_path or Path('benchmark_results.png')
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    print(f"\n  Chart saved to: {save_path}")
    plt.close()


def run_full_benchmark(
    file_path: Path,
    runs: int = 3,
    include_pymavlink: bool = True,
    num_workers: Optional[int] = None,
) -> None:
    """מריץ את כל השיטות ומשווה ביניהן בטבלה מסודרת."""
    workers = num_workers or min(os.cpu_count() or 4, 8)
    print(f"\n{'=' * 80}")
    print(f"  BIN File Parsing Benchmark")
    print(f"{'=' * 80}")
    print(f"  File:      {file_path}")
    print(f"  Size:      {file_path.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  Runs:      {runs} per method")
    print(f"  Workers:   {workers}")
    print(f"  CPU cores: {os.cpu_count()}")
    print(f"{'=' * 80}\n")
    all_results: Dict[str, List[BenchmarkResult]] = {}

    print("[1/5] Sequential (custom parser)")
    all_results["Sequential (custom)"] = run_benchmark(
        parse_sequential, file_path, runs
    )

    print(f"\n[2/5] ThreadPoolExecutor ({workers} workers)")
    all_results[f"ThreadPool ({workers}w)"] = run_benchmark(
        lambda p: parse_threaded(p, num_workers=workers),
        file_path, runs, f"ThreadPool({workers}w)"
    )

    print(f"\n[3/5] ProcessPoolExecutor ({workers} workers)")
    all_results[f"ProcessPool ({workers}w)"] = run_benchmark(
        lambda p: parse_multiprocess(p, num_workers=workers),
        file_path, runs, f"ProcessPool({workers}w)"
    )

    print(f"\n[4/5] asyncio ({workers} workers)")
    all_results[f"Asyncio ({workers}w)"] = run_benchmark(
        lambda p: parse_async(p, num_workers=workers),
        file_path, runs, f"Asyncio({workers}w)"
    )

    if include_pymavlink:
        print("\n[5/5] Pymavlink")
        all_results["Pymavlink"] = run_benchmark(
            parse_pymavlink_benchmark, file_path, runs
        )
    else:
        print("\n[5/5] Pymavlink -- skipped")

    print_comparison_table(all_results)
    generate_bar_chart(all_results)


if __name__ == '__main__':
    path = Path('log_file_test_01.bin')
    if not path.exists():
        print(f"File not found: {path}")
        raise SystemExit(1)
    parser = BinParser(path)
    parser.describe()
    print("\n--- Message type counts ---")
    counts = parser.get_message_type_summary()
    total = 0
    for name, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {name:<8} {count:>8,}")
        total += count
    print(f"  {'TOTAL':<8} {total:>8,}")
