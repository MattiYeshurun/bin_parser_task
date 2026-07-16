import sys
from pathlib import Path
from collections import defaultdict
from pymavlink import mavutil

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))

from src.business_logic.ardupilot_bin_parser import BinParser
from test_helpers import scan_message_offsets

def main():
    file_path = Path(__file__).resolve().parent.parent / "log_file_test_01.bin"
    if not file_path.exists():
        print(f"Error: {file_path.name} not found.")
        return

    print("Scanning file using Custom Parser...")
    parser = BinParser(file_path)
    offsets = scan_message_offsets(file_path, parser.formats)
    
    custom_counts = defaultdict(int)
    for pos, type_id in offsets:
        fmt_obj = parser.formats.get(type_id)
        name = fmt_obj.name if fmt_obj else f"UNKNOWN_ID_{type_id}"
        custom_counts[name] += 1

    print("Scanning file using pymavlink...")
    mavlink_counts = defaultdict(int)
    connection = mavutil.mavlink_connection(str(file_path))
    while True:
        msg = connection.recv_match()
        if msg is None:
            break
        msg_type = msg.get_type()
        mavlink_counts[msg_type] += 1

    # Get union of all message types found
    all_types = sorted(list(set(custom_counts.keys()) | set(mavlink_counts.keys())))

    print("\n" + "=" * 60)
    print(" MESSAGE TYPE COUNT COMPARISON: CUSTOM VS PYMAVLINK")
    print("=" * 60)
    print(f"| {'Message Type':<15} | {'Custom Count':<15} | {'pymavlink Count':<15} | {'Difference':<10} |")
    print("-" * 60)

    total_custom = 0
    total_mavlink = 0
    total_diff = 0

    for m_type in all_types:
        c_count = custom_counts[m_type]
        m_count = mavlink_counts[m_type]
        diff = c_count - m_count
        
        total_custom += c_count
        total_mavlink += m_count
        total_diff += abs(diff)

        diff_str = f"{diff:+d}" if diff != 0 else "0"
        print(f"| {m_type:<15} | {c_count:<15,} | {m_count:<15,} | {diff_str:<10} |")

    print("-" * 60)
    diff_total_str = f"{total_diff:+d}" if total_diff != 0 else "0"
    print(f"| {'TOTAL':<15} | {total_custom:<15,} | {total_mavlink:<15,} | {diff_total_str:<10} |")
    print("=" * 60 + "\n")

    if total_diff == 0:
        print("[SUCCESS] All message types match exactly between Custom and pymavlink!")
    else:
        print("[WARNING] There are discrepancies between message counts.")

if __name__ == "__main__":
    main()
