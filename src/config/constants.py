import struct
from pathlib import Path

MESSAGE_HEADER = b"\xa3\x95"
FMT_MESSAGE_TYPE_ID = 0x80
FMT_MESSAGE_SIZE = 89
FMT_PAYLOAD_STRUCT = struct.Struct("<BB4s16s64s")
HEADER_SIZE = 3
GPS_COORDINATE_SCALE = 10_000_000.0
DEFAULT_LOG_FILE = Path("log_file_test_01.bin")
