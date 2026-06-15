import struct


def build_perfect_dynamic_bank(data):
    dynamic_bank = {}
    magic_bytes = b'\xa3\x95'
    fmt_struct_format = '<BB4s16s64s'
    fmt_msg_len = 89
    
    ardupilot_to_struct = {
        'b': 'b', 'B': 'B', 'h': 'h', 'H': 'H', 'i': 'i', 'I': 'I',
        'f': 'f', 'd': 'd', 'n': '4s', 'N': '16s', 'Z': '64s',
        'c': 'h', 'C': 'H', 'e': 'i', 'E': 'I', 'L': 'i', 'M': 'b',
        'q': 'q', 'Q': 'Q', 'a': '3h'
    }

    location = data.find(magic_bytes)

    while location != -1:
        msg = data[location : location + fmt_msg_len]
        if len(msg) < fmt_msg_len:
            break
            
        if msg[2] == 128: 
            unpacked_fmt = struct.unpack(fmt_struct_format, msg[3:])
            target_type = unpacked_fmt[0]


            name_raw = unpacked_fmt[2]
            raw_fmt = unpacked_fmt[3].decode('ascii', errors='ignore').strip('\x00')
            columns_raw = unpacked_fmt[4].decode('ascii', errors='ignore').strip('\x00')
            try:
                name = name_raw.decode('ascii').strip('\x00')
                is_valid_name = name.isalnum() and len(name) > 0
            except UnicodeDecodeError:
                is_valid_name = False

            if is_valid_name:
                python_fmt = ""
                total_msg_len = 3
            
                for char in raw_fmt:
                    if char in ardupilot_to_struct:
                        struct_char = ardupilot_to_struct[char]
                        python_fmt += struct_char
                        total_msg_len += struct.calcsize(f"<{struct_char}")

                msg_fmt = f"<3x{python_fmt}"

                dynamic_bank[target_type] = {
                    'name': name,
                    'columns': [col.strip() for col in columns_raw.split(',') if col.strip()],
                    'msg_len': total_msg_len,
                    'msg_fmt': msg_fmt,
                }
            
                location = data.find(magic_bytes, location + fmt_msg_len)
                continue
            
        location = data.find(magic_bytes, location + 1)
            
    return dynamic_bank

def parse_flight_data(file_path, target_msg_name="GPS"):
    with open(file_path, 'rb') as file:
        data = file.read()
        
    bank = build_perfect_dynamic_bank(data)
    
    target_type = None
    for m_type, info in bank.items():
        if info['name'] == target_msg_name:
            target_type = m_type
            break
            
    if target_type is None:
        print(f"Error: Message type '{target_msg_name}' not found in dynamic bank.")
        return {}

    print(f"Parsing messages of type '{target_msg_name}' (type ID {target_type})...\n")
    
    parsed_messages = {}

    magic_bytes = b'\xa3\x95'
    data_len = len(data)
    msg_info = bank[target_type]
    msg_len = msg_info['msg_len']
    msg_fmt = msg_info['msg_fmt']
    columns = msg_info['columns']

    location = data.find(magic_bytes)
    
    while location != -1:
        if location + msg_len <= data_len and data[location + 2] == target_type:
            msg_bytes = data[location : location + msg_len]

            unpacked_data = struct.unpack(msg_fmt, msg_bytes)

            
            if target_msg_name == "FMT" and not (
                isinstance(unpacked_data[2], bytes) 
                and unpacked_data[2].decode('ascii', errors='ignore').strip('\x00 ').isalnum()):
                break
                
            current_msg_dict = {}
            for col, val in zip(columns, unpacked_data):
                if isinstance(val, bytes):
                    val = val.decode('ascii', errors='ignore').strip('\x00')
                elif col in ('Lat', 'Lng') and isinstance(val, int):
                    val = val / 10000000.0

                current_msg_dict[col] = val

            parsed_messages[location] = current_msg_dict

            location = data.find(magic_bytes, location + msg_len)
        else:
            location = data.find(magic_bytes, location + 1)

    return parsed_messages
                

if __name__ == "__main__":
    file_path = "log_file_test_01.bin"

    # with open(file_path, "rb") as file:
    #     file_bytes = file.read()

    # bank = build_perfect_dynamic_bank(file_bytes)
    # print(f"Built dynamic bank with {len(bank)} message types.")

    # if 128 in bank:
    #     print(f"Message type 128 details: {bank[128]}")

    # print("\n--- All available message types ---")
    # for i in bank:
    #     print(f"Type {i}: {bank[i]}")



    msg_name = 'STAK'
    data_parse = parse_flight_data(file_path, target_msg_name=msg_name)
    print(f"\nSuccessfully parsed {len(data_parse)} {msg_name} messages.")
    
    print("\nFirst few parsed messages:")
    for loc, msg in list(data_parse.items())[:5]:
        print(f"Location {loc}: {msg}")
