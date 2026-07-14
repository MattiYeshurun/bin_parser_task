import unittest
import struct
import tempfile
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))

from src.business_logic.ardupilot_bin_parser import BinParser
from test_helpers import decode_message
from src.business_logic.format_bank import load_message_formats


class TestArduPilotParserEdgeCases(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_dir_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_non_existent_file(self):
        """Test how parser handles a missing file."""
        non_existent = self.test_dir_path / "missing_file.bin"
        parser = BinParser(non_existent)
        
        # Calling describe/parse shouldn't crash, should return empty structures
        self.assertEqual(parser.formats, {})
        result = parser.parse_all_messages(parsing_mode="simple")
        self.assertEqual(result, {})

    def test_zero_byte_file(self):
        """Test how parser handles a completely empty 0-byte file."""
        empty_file = self.test_dir_path / "empty.bin"
        empty_file.write_bytes(b"")

        parser = BinParser(empty_file)
        self.assertEqual(parser.formats, {})

        # Sequential parse
        result_seq = parser.parse_all_messages(parsing_mode="simple")
        self.assertEqual(result_seq, {})

        # Multiprocessing parse (shouldn't crash with division by zero or empty chunks)
        result_mp = parser.parse_all_messages(parsing_mode="processes", num_workers=4)
        self.assertEqual(result_mp, {})

    def test_corrupted_message_payload(self):
        """Test parser resilience to corrupted/truncated message payloads."""
        corrupted_file = self.test_dir_path / "corrupted.bin"
        
        # Write a valid FMT message format definition header, but truncate the payload
        # FMT type is 128 (0x80), length of FMT is 89 bytes
        fmt_bytes = b"\xa3\x95\x80" + b"\x80\x59FMT\x00\x00\x00FMT" + b"A" * 70  # Valid start but trash data
        corrupted_file.write_bytes(fmt_bytes)

        # Loading formats shouldn't crash; it should skip corrupted structs safely
        formats = load_message_formats(corrupted_file)
        self.assertNotIn(128, formats)

    def test_incomplete_message_at_end_of_file(self):
        """Test when a message header starts but the file ends before the message length is met."""
        incomplete_file = self.test_dir_path / "incomplete.bin"
        
        # Let's say we have a format for 'TEST' message, ID 150, length 10 bytes
        # Write the format first (FMT header is 89 bytes)
        # Struct format for FMT description: type_id (B), length (B), name (4s), format (16s), columns (64s)
        fmt_payload = struct.pack("<BB4s16s64s", 150, 10, b"TEST", b"I", b"Val")
        fmt_msg = b"\xa3\x95\x80" + fmt_payload
        
        # Write the format, and then write an incomplete TEST message (only header + 2 bytes instead of 10)
        incomplete_data = fmt_msg + b"\xa3\x95\x96\x01\x02" 
        incomplete_file.write_bytes(incomplete_data)

        parser = BinParser(incomplete_file)
        self.assertIn(150, parser.formats)

        # Parse sequential (should skip the incomplete message gracefully without IndexError/StructError crash)
        result = parser.parse_all_messages(parsing_mode="simple")
        self.assertEqual(result.get("TEST"), [])

if __name__ == "__main__":
    unittest.main()
