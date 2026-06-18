import math
import time
from pathlib import Path
from typing import Dict, List
import matplotlib.pyplot as plt

from src.config.logging_config import get_logger
from src.models.bin_messages import BenchmarkResult
from src.services.bin_parser_service import BinParserService
from src.services.benchmark_service import (
    parse_sequential_fast,
    parse_threaded_fast,
    parse_multiprocess_fast,
    parse_async_fast,
    benchmark_pymavlink
)

logger = get_logger(__name__)

def generate_and_save_chart(all_results: Dict[str, List[BenchmarkResult]], output_path: str = "benchmark_results.png") -> None:
    methods = []
    avg_times = []

    for method_name, results in all_results.items():
        if not results: 
            continue
        methods.append(method_name.split(" (")[0])
        times = [r.elapsed_seconds for r in results]
        avg_times.append(sum(times) / len(times))

    plt.figure(figsize=(10, 6))
    colors = ['#dc3545', '#ffc107', '#17a2b8', '#28a745', '#007bff']
    bars = plt.bar(methods, avg_times, color=colors[:len(methods)], edgecolor='black', width=0.5)
    
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height + (max(avg_times) * 0.01), 
                 f'{height:.3f}s', ha='center', va='bottom', fontweight='bold', fontsize=10)

    plt.title("MAVLink BIN Log Parsing Benchmark — Time Comparison", fontsize=12, fontweight='bold', pad=15)
    plt.ylabel("Average Execution Time (Seconds)", fontsize=11, fontweight='bold')
    plt.xlabel("Concurrency Method", fontsize=11, fontweight='bold')
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    logger.info(f"Successfully updated benchmark chart image at: {output_path}")

def print_comparison_table(all_results: Dict[str, List[BenchmarkResult]]) -> None:
    baseline_average = None
    if 'pymavlink (Baseline)' in all_results and all_results['pymavlink (Baseline)']:
        baseline_runs = all_results['pymavlink (Baseline)']
        baseline_average = sum(r.elapsed_seconds for r in baseline_runs) / len(baseline_runs)

    print("\n+" + "=" * 116 + "+", flush=True)
    print(f"|  {'Method':<35} | {'Messages':>12} | {'Min(s)':>8} | {'Avg(s)':>8} | {'Max(s)':>8} | {'Speedup':>9} |", flush=True)
    print("+" + "-" * 116 + "+", flush=True)
    
    for name, results in all_results.items():
        if not results: 
            continue
        times = [r.elapsed_seconds for r in results]
        avg_t = sum(times) / len(times)
        avg_c = sum([r.message_count for r in results]) / len(results)
        speedup = f"{baseline_average / avg_t:.2f}x" if baseline_average and avg_t > 0 else "1.00x"
        print(f"|  {name:<35} | {int(avg_c):>12,} | {min(times):>8.3f} | {avg_t:>8.3f} | {max(times):>8.3f} | {speedup:>9} |", flush=True)
    print("+" + "=" * 116 + "+\n", flush=True)

class CompareService:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.parser = BinParserService(file_path)

    def run_comprehensive_benchmark(self, runs: int = 1, num_workers: int = 4) -> Dict[str, List[BenchmarkResult]]:
        logger.info("Loading entire file into memory once to perform super-fast RAM parsing...")
        file_size = self.file_path.stat().st_size
        with self.file_path.open('rb') as f:
            file_bytes = f.read()

        logger.info("Scanning file offsets once...")
        offsets = self.parser.scan_message_offsets()
        
        logger.info(f"Starting High-Performance Benchmark ({runs} Run, {num_workers} Workers)...")
        
        methods = {
            "pymavlink (Baseline)": lambda: benchmark_pymavlink(self.file_path),
            "Sequential (Custom)": lambda: parse_sequential_fast(file_bytes, self.parser),
            f"ThreadPoolExecutor ({num_workers}w)": lambda: parse_threaded_fast(file_bytes, self.parser, offsets, file_size, num_workers),
            f"ProcessPoolExecutor ({num_workers}w)": lambda: parse_multiprocess_fast(self.file_path, offsets, file_size, num_workers),
            f"Asyncio ({num_workers}w)": lambda: parse_async_fast(file_bytes, self.parser, offsets, file_size, num_workers)
        }
        
        all_results = {name: [] for name in methods.keys()}
        for name, func in methods.items():
            logger.info(f"Executing {name}...")
            try:
                res = func()
                all_results[name].append(res)
            except Exception as e:
                logger.error(f"Method {name} failed: {e}", exc_info=True)

        print_comparison_table(all_results)
        generate_and_save_chart(all_results, output_path="benchmark_results.png")
        return all_results

def run_comparison_report(file_path: Path, runs: int = 1, num_workers: int = 4) -> None:
    service = CompareService(file_path)
    service.run_comprehensive_benchmark(runs=runs, num_workers=num_workers)