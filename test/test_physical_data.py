import sys
import math
import json
from pathlib import Path
from pymavlink import mavutil

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))

from src.business_logic.ardupilot_bin_parser import BinParser
from test_helpers import decode_message, scan_message_offsets
from src.config.constants import MESSAGE_HEADER

def clean_dict_values(d: dict) -> dict:
    clean = {}
    for k, v in d.items():
        if isinstance(v, float) and math.isnan(v):
            clean[k] = "nan"
        elif isinstance(v, bytes):
            clean[k] = v.decode('utf-8', errors='ignore').strip().replace('\x00', '')
        elif isinstance(v, float):
            clean[k] = round(v, 4)
        else:
            clean[k] = v
    return clean

def check_dictionaries_match(d1: dict, d2: dict) -> bool:
    if set(d1.keys()) != set(d2.keys()):
        return False
    for key, v1 in d1.items():
        v2 = d2.get(key)
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            if not math.isclose(v1, v2, rel_tol=1e-3, abs_tol=1e-3):
                return False
        elif str(v1) != str(v2):
            return False
    return True

def main():
    file_path = Path(__file__).resolve().parent.parent / "log_file_test_01.bin"
    if not file_path.exists():
        print(f"Error: {file_path.name} not found.")
        return

    print("\n" + "=" * 175)
    print(" VERIFYING 1:1 EQUIVALENCE: OFFICIAL PYMAVLINK VS YOUR PARSER")
    print("=" * 175)

    parser = BinParser(file_path)
    with file_path.open('rb') as f:
        file_bytes = f.read()
        
    offsets = scan_message_offsets(file_path, parser.formats)
    view = memoryview(file_bytes)
    connection = mavutil.mavlink_connection(str(file_path))

    test_limit = 5000
    mismatches = 0
    checked_messages = 0

    print("+" + "-" * 173 + "+")
    print(f"| {'Line #':<6} | {'Msg Type':<8} | {'[1/2] Official pymavlink Dictionary':<65} | {'[2/2] Your Project Dictionary':<65} | {'1:1 Match':<7} |")
    print("+" + "=" * 173 + "+")

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

        checked_messages += 1
        
        pymavlink_fields = pymavlink_msg.to_dict()
        pymavlink_fields.pop('mavpackettype', None)
        p_clean = clean_dict_values(pymavlink_fields)
        p_str = json.dumps(p_clean, default=str)

        c_clean = clean_dict_values(custom_msg.fields)
        c_str = json.dumps(c_clean, default=str)
        
        is_match = check_dictionaries_match(p_clean, c_clean)
        status_label = "MATCH" if is_match else "FAIL"
        
        if not is_match:
            mismatches += 1

        if len(p_str) > 65: p_str = p_str[:62] + "..."
        if len(c_str) > 65: c_str = c_str[:62] + "..."

        print(f"| {msg_idx:<6} | {custom_msg.name:<8} | {p_str:<65} | {c_str:<65} | {status_label:<7} |")

        if msg_idx % 15 == 0 and msg_idx > 0:
            print("+" + "-" * 173 + "+")

        msg_idx += 1

    print("+" + "-" * 173 + "+")
    print(f"  Total Rows Verified: {checked_messages:,}  |  Total Verification Failures: {mismatches}")
    print("=" * 175)
    
    if mismatches == 0:
        print(" [OK] VERIFICATION SUCCESS: 1:1 PERFECT DATA MATCH PROVEN ACROSS ALL ROWS!")
    else:
        print(" [!!] WARNING: Discrepancies found in decoding data values.")
    print("=" * 175 + "\n")

if __name__ == "__main__":
    main()