import struct

# fmt_schema = {}

# def parse_message(data, location, msg_type):
#     if msg_type == 128:
#         raw = struct.unpack_from('<BB4s16s64s', data, location + 3)
        
#         type_id = raw[1]
#         fmt_string = raw[3].decode('ascii', errors='ignore').strip('\x00')
#         cols = raw[4].decode('ascii', errors='ignore').strip('\x00')
        
#         fmt_schema[type_id] = {
#             'length': raw[0],
#             'format': '<' + fmt_string.replace(" ", ""), 
#             'columns': cols
#         }
#         return f"Learned type {type_id} with format {fmt_schema[type_id]['format']}"
    
#     elif msg_type in fmt_schema:
#         schema = fmt_schema[msg_type]
#         try:
#             unpacked = struct.unpack_from(schema['format'], data, location + 3)
#             return dict(zip(schema['columns'].split(','), unpacked))
#         except struct.error as e:
#             return f"Error decoding type {msg_type}: {e}"
    
#     return None

# def test_parsing():
#     bank = {128: {'length': 89, 'format': '<BB4s16s64s', 'columns': 'Type,Length,Name,Format,Columns'}}
    
#     try:
#         with open('log_file_test_01.bin', 'rb') as f:
#             data = f.read()
        
#         target = b'\xa3\x95'
#         location = data.find(target)
        
#         while location != -1:
#             if location + 3 >= len(data):
#                 break
            
#             msg_type = data[location + 2]
            
#             if msg_type in bank or msg_type in fmt_schema:
#                 parsed_data = parse_message(data, location, msg_type)
#                 if parsed_data:
#                     print(f"Found message of type {msg_type} at location {location}: {parsed_data}")
            
#             location = data.find(target, location + 1)
            
#     except FileNotFoundError:
#         print("Error: File not found.")

# if __name__ == "__main__":
#     test_parsing()



def parse_message():
    bank = {128: {'length': 89, 'format': '<BB4s16s64s', 'columns': 'Type,Length,Name,Format,Columns'}}
    
    leng = bank.get(128)['length']
    columns = bank.get(128)['columns'].split(',')
    magic_bytes = b'\xa3\x95'

    with open('log_file_test_01.bin', 'rb') as file:
        data = file.read()

        location = data.find(b'\xa3\x95')
        msg_count = 0

        while location != -1:
            msg = data[location:location + leng]
            if len(msg) < leng:
                print(f"Warning: Incomplete message at location {location}. Expected length {leng}, got {len(msg)}.")
                break

            if msg[2] == 128:  # Type field is at offset 2
                msg_count += 1
                print(f"\nMessage {msg_count} at location {location}:")

                unpacked = [
                    msg[2],  # Length
                    msg[3],  # Type
                    msg[4:8],  # Name (4 bytes)
                    msg[8:24],  # Format (16 bytes)
                    msg[24:88]  # Columns (64 bytes)
                ]

                for col, val in zip(columns, unpacked):
                    if isinstance(val, bytes):
                        val = val.decode('ascii', errors='ignore').strip('\x00')
                    print(f"{col}: {val}")

                location = data.find(magic_bytes, location + leng)
            else:
                location = data.find(magic_bytes, location + 1)


    #     print("Found FMT message at location:", location)
    #     leng = bank.get(128)['length']
    #     print(f"Message length from bank: {leng}")
    #     msg = data[location:location + leng]
    #     format = bank.get(128)['format']

    #     print(f"Debug: Format string is {repr(format)}")
    #     unpacked = struct.unpack(format, msg[3:])
    #     print(unpacked)
    #     columns = bank.get(128)['columns'].split(',')
    #     for col, val in zip(columns, unpacked):
    #         if isinstance(val, bytes):
    #             val = val.decode('ascii', errors='ignore').strip('\x00')
    #         print(f"{col}: {val}")

if __name__ == "__main__":
    parse_message()