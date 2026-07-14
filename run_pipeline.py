import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.business_logic.ardupilot_bin_parser import BinParser
from src.services.compare_service import run_comparison_report

def main():

    file_path = Path("log_file_test_01.bin")
    if not file_path.exists():
        print(f"Error: File not found at {file_path}")
        return

    print(f"--- Starting Pipeline for: {file_path.name} ---")
    
    parser = BinParser(file_path)
    print("\n[1/3] File Structure Analysis:")
    parser.describe()
    
    print("\n[2/3] Extracting GPS Summary:")
    gps_result = parser.parse_all_messages(parsing_mode='simple', wanted_names=['GPS'])
    messages = gps_result.get('GPS', [])
    if messages:
        print(f"Successfully retrieved {len(messages)} GPS records.")
    else:
        print("No GPS messages found.")
    print("\n[3/3] Running Performance Benchmark (Auto Workers):")
    run_comparison_report(file_path)
    
    print("\n--- Pipeline Completed Successfully ---")

if __name__ == '__main__':
    main()