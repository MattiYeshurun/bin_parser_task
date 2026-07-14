import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.services.compare_service import benchmark_pymavlink, measure_parse_time
from src.business_logic.ardupilot_bin_parser import BinParser
from src.config.worker_config import get_optimal_num_workers

def main():
    log_file = Path("log_file_test_01.bin")
    if not log_file.exists():
        log_file = Path(__file__).resolve().parent.parent / "log_file_test_01.bin"
        
    if not log_file.exists():
        print(f"Error: {log_file} not found in workspace.")
        sys.exit(1)

    print("\n" + "=" * 100)
    print("  ARDUPILOT BIN LOG PARSING BENCHMARK")
    print(f"  File: {log_file.name}")
    print(f"  Size: {log_file.stat().st_size / (1024 * 1024):.2f} MB")
    print("=" * 100)

    # 1. Pymavlink Baseline
    print("\n[1/5] Running pymavlink baseline...")
    pymav_res = benchmark_pymavlink(log_file)
    pymav_time = pymav_res.elapsed_seconds
    pymav_count = pymav_res.message_count
    print(f"  Done: {pymav_count:,} messages in {pymav_time:.2f}s")

    # 2. Our Sequential
    print("\n[2/5] Running our Sequential custom parser...")
    our_seq_res = measure_parse_time("Sequential", log_file, "simple")
    our_seq_time = our_seq_res.elapsed_seconds
    our_seq_count = our_seq_res.message_count
    print(f"  Done: {our_seq_count:,} messages in {our_seq_time:.2f}s")

    # 3. Our Threaded
    num_workers = get_optimal_num_workers(log_file)
    print(f"\n[3/5] Running our Threaded custom parser ({num_workers} workers)...")
    our_thread_res = measure_parse_time("Threaded", log_file, "threads", num_workers)
    our_thread_time = our_thread_res.elapsed_seconds
    our_thread_count = our_thread_res.message_count
    print(f"  Done: {our_thread_count:,} messages in {our_thread_time:.2f}s")

    # 4. Our Multiprocessing
    print(f"\n[4/5] Running our Multiprocessing custom parser ({num_workers} workers)...")
    our_mp_res = measure_parse_time("Multiprocessing", log_file, "processes", num_workers)
    our_mp_time = our_mp_res.elapsed_seconds
    our_mp_count = our_mp_res.message_count
    print(f"  Done: {our_mp_count:,} messages in {our_mp_time:.2f}s")

    # 5. Our Asyncio
    print(f"\n[5/5] Running our Asyncio custom parser ({num_workers} workers)...")
    our_async_res = measure_parse_time("Asyncio", log_file, "async", num_workers)
    our_async_time = our_async_res.elapsed_seconds
    our_async_count = our_async_res.message_count
    print(f"  Done: {our_async_count:,} messages in {our_async_time:.2f}s")

    print("\n" + "=" * 100)
    print("  SUMMARY OF RESULTS (Speedup vs pymavlink)")
    print("=" * 100)
    print(f"  {'Method':<25} | {'Time (s)':<10} | {'Speedup':<10}")
    print(f"  {'-' * 25}-+-{'-' * 10}-+-{'-' * 10}")
    print(f"  {'pymavlink (Baseline)':<25} | {pymav_time:<10.2f}s | 1.00x")
    print(f"  {'Sequential':<25} | {our_seq_time:<10.2f}s | {pymav_time / max(our_seq_time, 1e-9):.2f}x")
    print(f"  {'Threaded':<25} | {our_thread_time:<10.2f}s | {pymav_time / max(our_thread_time, 1e-9):.2f}x")
    print(f"  {'Multiprocessing':<25} | {our_mp_time:<10.2f}s | {pymav_time / max(our_mp_time, 1e-9):.2f}x")
    print(f"  {'Asyncio':<25} | {our_async_time:<10.2f}s | {pymav_time / max(our_async_time, 1e-9):.2f}x")
    print("=" * 100 + "\n")

if __name__ == "__main__":
    main()
