import argparse
from pathlib import Path
from src.services.compare_service import run_comparison_report

def main():
    parser = argparse.ArgumentParser(description="Fast MAVLink Benchmark Tool")
    parser.add_argument("--file", type=str, default="log_file_test_01.bin")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    
    args = parser.parse_args()
    file_path = Path(args.file)

    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.")
        return

    print("\n" + "=" * 60)
    print(f" RUNNING FAST PARALLEL BENCHMARK REPORT")
    print("=" * 60, flush=True)
    
    run_comparison_report(file_path, runs=args.runs, num_workers=args.workers)

if __name__ == "__main__":
    main()