# ArduPilot BIN Log Parser

A high-performance binary log (`.BIN`) parser for ArduPilot logs, designed to be a 100% physically accurate drop-in replacement for the official `pymavlink` parser, achieving industry-grade execution speeds.

## 🚀 Key Features

1. **Outstanding Parsing Speed:**
   * **Sequential Mode:** Employs a highly optimized memory-mapped single-pass iteration, bypassing redundant pre-scans, disabling GC overhead during hot loops, and bypassing list conversions for unscaled types (~17 seconds for 7.6M messages, twice as fast as pymavlink!).
   * **Targeted Header Search:** Detects targeted single-type parsing requests (e.g., GPS records only) and performs targeted `find()` calls directly on the mmap buffers, skipping millions of irrelevant IMU messages in microseconds.
   * **Parallel Execution (Multiprocessing & Asyncio):** Automatically chunks binary data ranges and distributes workloads to subprocesses, solving Python's IPC and Pickling bottlenecks, with custom lifecycle recovery for Windows event loops.
2. **100% Data Integrity Verification:**
   * Validated 1:1 equivalence against `pymavlink` output, ensuring correct extraction of raw telemetry data, byte arrays (e.g., `FILE` message types), and special floats (`nan`).

---

## 📂 Repository Structure

* `src/` — Core parser logic:
  * `src/business_logic/ardupilot_bin_parser.py` — Parser coordinator, chunk split logic, and multiprocessing wrappers.
  * `src/business_logic/format_bank.py` — Message format (FMT) scanning and structure dictionary builder.
  * `src/config/worker_config.py` — Dynamic optimal worker count calculation based on RAM and CPU.
  * `src/parsing_methods/shared.py` — Core parsing loop, targeted searches, and multiprocessing workers.
  * `src/services/compare_service.py` — Benchmark execution and summary report printing.
* `test/` — Validation and performance tests:
  1. [test_helpers.py](file:///c:/Users/מתי/PythonProjects/bin_processing_task_02.06.2026/bin_parser_task/test/test_helpers.py) — Utility containing single-message decoder (`decode_message`).
  2. [test_physical_data.py](file:///c:/Users/מתי/PythonProjects/bin_processing_task_02.06.2026/bin_parser_task/test/test_physical_data.py) — Shows a sample comparison table for the first 5,000 decoded messages against pymavlink.
  2. [check_integrity.py](file:///c:/Users/מתי/PythonProjects/bin_processing_task_02.06.2026/bin_parser_task/test/check_integrity.py) — Performs a full 1:1 equivalence verification across all 7.6M messages.
  3. [run_benchmark.py](file:///c:/Users/מתי/PythonProjects/bin_processing_task_02.06.2026/bin_parser_task/test/run_benchmark.py) — Compares execution times across all concurrency modes.
  4. [test_edge_cases.py](file:///c:/Users/מתי/PythonProjects/bin_processing_task_02.06.2026/bin_parser_task/test/test_edge_cases.py) — Unit tests covering empty, corrupted, truncated log files, and invalid GPS states.

---

## ⚙️ Running Tests and Benchmarks

Run scripts from the workspace root directory using the local Python environment:

### 1. Run Sample Data Validation (First 5,000 Messages):
```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe test/test_physical_data.py
```

### 2. Run Comprehensive 1:1 Integrity Check (All 7.6M Messages):
```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe test/check_integrity.py
```

### 3. Run Concurrency Performance Benchmark:
```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe test/run_benchmark.py
```