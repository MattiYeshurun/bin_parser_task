import math
from pathlib import Path
from pymavlink import mavutil
from src.services.bin_parser_service import BinParserService

def main():
    file_path = Path("log_file_test_01.bin")
    if not file_path.exists():
        print(f"Error: {file_path} not found.")
        return

    print("\n" + "=" * 90)
    print(" 🔍 STARTING GENUINE 1:1 DATA INTEGRITY CHECK")
    print("=" * 90)

    parser = BinParserService(file_path)
    with file_path.open('rb') as f:
        file_bytes = f.read()
        
    offsets = parser.scan_message_offsets()
    view = memoryview(file_bytes)
    connection = mavutil.mavlink_connection(str(file_path))

    test_limit = 500000000000
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
            
        payload = view[pos + 3 : pos + fmt_obj.length]
        custom_msg = parser.decode_message(payload, type_id)
        if not custom_msg: continue

        pymavlink_fields = pymavlink_msg.to_dict()
        pymavlink_fields.pop('mavpackettype', None)

        # לולאת בדיקה והצלבה אמיתית שדה-שדה
        for field_name, custom_value in custom_msg.fields.items():
            checked_fields += 1
            pymavlink_value = pymavlink_fields.get(field_name, "N/A")

            is_match = False
            if isinstance(custom_value, (int, float)) and isinstance(pymavlink_value, (int, float)):
                is_match = math.isclose(custom_value, pymavlink_value, rel_tol=1e-3, abs_tol=1e-3)
            else:
                is_match = str(custom_value).strip() == str(pymavlink_value).strip()

            if not is_match:
                mismatches += 1
                print(f"| {msg_idx:<6} | {custom_msg.name:<10} | {field_name:<18} | {str(custom_value)[:30]:<30} | {str(pymavlink_value)[:30]:<30} | FAIL   |")

        # הדפסת דוגמה אמיתית ומאומתת אחת לכל 450 הודעות רק אם היא עברה באמת בהצלחה!
        if msg_idx % 450 == 0:
            first_field = list(custom_msg.fields.keys())[0] if custom_msg.fields else "None"
            c_val = custom_msg.fields.get(first_field)
            p_val = pymavlink_fields.get(first_field)
            # פה ההדפסה מבוססת על השוואת אמת
            v_match = "MATCH" if str(c_val) == str(p_val) or (isinstance(c_val,(int,float)) and math.isclose(c_val,p_val,rel_tol=1e-2)) else "FAIL"
            print(f"| {msg_idx:<6} | {custom_msg.name:<10} | {first_field:<18} | {str(c_val)[:30]:<30} | {str(p_val)[:30]:<30} | {v_match:<6} |")
        
        msg_idx += 1

    print("-" * 115)
    print(f" Total Fields Sampled and Checked : {checked_fields:,}")
    print(f" Total Data Discrepancies Found   : {mismatches}")
    print("=" * 90)

if __name__ == "__main__":
    main()