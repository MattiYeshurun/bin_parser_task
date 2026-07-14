import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from pymavlink import mavutil

from src.business_logic.ardupilot_bin_parser import BinParser
from src.config.logging_config import get_logger
from src.config.worker_config import get_optimal_num_workers
from src.models.bin_messages import BenchmarkResult

logger = get_logger(__name__)


def benchmark_pymavlink(file_path: Path) -> BenchmarkResult:
    """Measures parsing time of pymavlink (Baseline)."""
    start = time.perf_counter()
    connection = mavutil.mavlink_connection(str(file_path))
    count = 0
    while connection.recv_match() is not None:
        count += 1
    return BenchmarkResult("pymavlink (Baseline)", count, time.perf_counter() - start)


def measure_parse_time(
    name: str, file_path: Path, parsing_mode: str, num_workers: Optional[int] = None
) -> BenchmarkResult:
    """Helper function to measure parsing execution time for custom parser execution modes."""
    start = time.perf_counter()
    parser = BinParser(file_path)
    result = parser.parse_all_messages(parsing_mode=parsing_mode, num_workers=num_workers)
    count = sum(len(v) for v in result.values())
    return BenchmarkResult(name, count, time.perf_counter() - start)


def print_comparison_table(all_results: Dict[str, BenchmarkResult]) -> None:
    """Logs a clean ASCII comparison table of all parsing methods."""
    baseline = all_results.get("pymavlink (Baseline)")
    baseline_time = baseline.elapsed_seconds if baseline else None

    table_lines = []
    table_lines.append("+" + "=" * 80 + "+")
    table_lines.append(f"|  {'Method':<30} | {'Messages':>12} | {'Time (s)':>12} | {'Speedup':>12} |")
    table_lines.append("+" + "-" * 80 + "+")

    for name, res in all_results.items():
        speedup = (
            f"{baseline_time / res.elapsed_seconds:.2f}x" if baseline_time and res.elapsed_seconds > 0 else "1.00x"
        )
        table_lines.append(
            f"|  {name:<30} | {res.message_count:>12,} | {res.elapsed_seconds:>12.3f}s | {speedup:>12} |"
        )
    table_lines.append("+" + "=" * 80 + "+")

    logger.info("\n" + "\n".join(table_lines) + "\n")


class CompareService:
    def __init__(self, file_path: Path):
        self.file_path = file_path

    def run_comprehensive_benchmark(self, num_workers: Optional[int] = None) -> Dict[str, BenchmarkResult]:
        if num_workers is None:
            num_workers = get_optimal_num_workers(self.file_path)
        logger.info(f"Starting Benchmark (1 Run, {num_workers} Workers)...")

        methods = {
            "pymavlink (Baseline)": lambda: benchmark_pymavlink(self.file_path),
            "Sequential (Custom)": lambda: measure_parse_time("Sequential (Custom)", self.file_path, "simple"),
            f"ThreadPoolExecutor ({num_workers}w)": lambda: measure_parse_time(
                f"ThreadPoolExecutor ({num_workers}w)", self.file_path, "threads", num_workers
            ),
            f"ProcessPoolExecutor ({num_workers}w)": lambda: measure_parse_time(
                f"ProcessPoolExecutor ({num_workers}w)", self.file_path, "processes", num_workers
            ),
            f"Asyncio ({num_workers}w)": lambda: measure_parse_time(
                f"Asyncio ({num_workers}w)", self.file_path, "async", num_workers
            ),
        }

        all_results: Dict[str, BenchmarkResult] = {}
        for name, func in methods.items():
            logger.info(f"Executing {name}...")
            try:
                all_results[name] = func()
            except Exception as e:
                logger.error(f"Method {name} failed: {e}", exc_info=True)

        print_comparison_table(all_results)
        return all_results



def run_comparison_report(file_path: Path, num_workers: Optional[int] = None) -> None:
    CompareService(file_path).run_comprehensive_benchmark(num_workers=num_workers)
