from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config.constants import DEFAULT_LOG_FILE
from src.services.benchmark_service import run_full_benchmark
from src.services.bin_parser_service import BinParserService, print_gps_summary
from src.services.compare_service import run_comparison_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='ArduPilot BIN File Parser & Benchmark Tool'
    )
    parser.add_argument(
        'file',
        nargs='?',
        default=str(DEFAULT_LOG_FILE),
        help='Path to the BIN log file',
    )
    parser.add_argument('--describe', action='store_true', help='Show file structure and message summaries')
    parser.add_argument('--gps', action='store_true', help='Show GPS records')
    parser.add_argument('--benchmark', action='store_true', help='Run benchmark comparison')
    parser.add_argument('--compare', action='store_true', help='Run custom parser vs pymavlink comparison')
    parser.add_argument('--runs', type=int, default=3, help='Benchmark runs per method')
    parser.add_argument('--workers', type=int, default=None, help='Worker count for parallel benchmarks')
    return parser


def main() -> None:
    args = build_parser().parse_args()
    file_path = Path(args.file)

    if not file_path.exists():
        print(f'Error: File not found: {file_path}')
        sys.exit(1)

    run_all = not (args.describe or args.gps or args.benchmark or args.compare)

    if args.describe or run_all:
        print(f"\n{'=' * 80}")
        print('  STEP 1 — File Structure Analysis')
        print(f"{'=' * 80}\n")
        parser = BinParserService(file_path)
        parser.describe()
        print('\n--- Message Type Counts ---\n')
        counts = parser.get_message_type_summary()
        total = 0
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            print(f'  {name:<8} {count:>8,}')
            total += count
        print(f"  {'TOTAL':<8} {total:>8,}")

    if args.gps or run_all:
        print(f"\n{'=' * 80}")
        print('  STEP 2 — GPS Message Reading')
        print(f"{'=' * 80}\n")
        print_gps_summary(file_path, max_display=15)

    if args.compare or run_all:
        print(f"\n{'=' * 80}")
        print('  STEP 3 — Custom Parser vs pymavlink Comparison')
        print(f"{'=' * 80}")
        run_comparison_report(file_path)

    if args.benchmark or run_all:
        print(f"\n{'=' * 80}")
        print('  STEP 4 — Benchmark Comparison (Timer)')
        print(f"{'=' * 80}\n")
        run_full_benchmark(
            file_path,
            runs=args.runs,
            include_pymavlink=True,
            num_workers=args.workers,
        )


if __name__ == '__main__':
    main()
