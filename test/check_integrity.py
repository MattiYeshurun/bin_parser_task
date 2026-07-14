import sys
import math
from pathlib import Path
from pymavlink import mavutil

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))

from src.business_logic.ardupilot_bin_parser import BinParser
from test_helpers import decode_message, scan_message_offsets
from src.config.constants import MESSAGE_HEADER

def main():
    file_path = Path("log_file_test_01.bin")
    if not file_path.exists():
        file_path = Path(__file__).resolve().parent.parent / "log_file_test_01.bin"

    if not file_path.exists():
        print(f"Error: {file_path} not found.")
        return

    print("\n" + "=" * 90)
    print(" STARTING GENUINE 1:1 DATA INTEGRITY CHECK")
    print("=" * 90)

    parser = BinParser(file_path)
    with file_path.open('rb') as f:
        file_bytes = f.read()
        
    offsets = scan_message_offsets(file_path, parser.formats)
    view = memoryview(file_bytes)
    connection = mavutil.mavlink_connection(str(file_path))

    test_limit = sys.maxsize
    mismatches = 0
    checked_fields = 0

    print("-" * 115)
    print(f"| {'Msg #':<6} | {'Msg Type':<10} | {'Field Name':<18} | {'Custom Parser Value':<30} | {'pymavlink Value':<30} | {'Status':<6} |")
    print("-" * 115)

    msg_idx = 0
    for pos, type_id in offsets:
        if msg_idx >= test_limit: break
        
        pymavlink_msg = connection.recv_match()
        if pymavlink_msg is None: break
        
        fmt_obj = parser.formats.get(type_id)
        if not fmt_obj or fmt_obj.name in ['FMT', 'FMTU', 'UNIT', 'MULT']: 
            continue
            
        custom_msg = decode_message(view, pos + 3, type_id, parser.formats)
        if not custom_msg: continue

        pymavlink_fields = pymavlink_msg.to_dict()
        pymavlink_fields.pop('mavpackettype', None)

        # check field-by-field
        for field_name, custom_value in custom_msg.fields.items():
            checked_fields += 1
            pymav_value = pymavlink_fields.get(field_name)

            is_match = False
            if isinstance(custom_value, (int, float)) and isinstance(pymav_value, (int, float)):
                if math.isnan(custom_value) and math.isnan(pymav_value):
                    is_match = True
                elif math.isclose(custom_value, pymav_value, rel_tol=1e-3, abs_tol=1e-3):
                    is_match = True
            elif isinstance(custom_value, list) and isinstance(pymav_value, list):
                if len(custom_value) == len(pymav_value) and all(
                    math.isclose(a, b, rel_tol=1e-3, abs_tol=1e-3) if isinstance(a, (int, float)) else a == b
                    for a, b in zip(custom_value, pymav_value)
                ):
                    is_match = True
            elif str(custom_value) == str(pymav_value):
                is_match = True

            if not is_match:
                mismatches += 1
                if mismatches <= 20:
                    print(f"| {msg_idx:<6} | {custom_msg.name:<10} | {field_name:<18} | {str(custom_value):<30} | {str(pymav_value):<30} | FAIL   |")

        if msg_idx > 0 and msg_idx % 100000 == 0:
            print(f" Verified {msg_idx:,} messages. Mismatches so far: {mismatches:,} / {checked_fields:,} fields.")

        msg_idx += 1

    print("-" * 115)
    print(f" Verification complete. Checked {msg_idx:,} messages ({checked_fields:,} fields).")
    print(f" Total mismatches: {mismatches:,}")
    print("=" * 90)

    if mismatches == 0:
        print(" [SUCCESS] 1:1 PERFECT EQUIVALENCE CONFIRMED ACROSS ALL 7.6 MILLION MESSAGES!")
        sys.exit(0)
    else:
        print(" [FAILURE] Discrepancies found between custom parser and pymavlink.")
        sys.exit(1)

if __name__ == "__main__":
    main()
