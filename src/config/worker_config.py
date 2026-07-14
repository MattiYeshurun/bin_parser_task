import os
import psutil
from pathlib import Path
from src.config.logging_config import get_logger

logger = get_logger(__name__)

def get_optimal_num_workers(file_path: Path) -> int:
    """Calculates the optimal number of workers based on physical CPU count, RAM availability, and file size."""
    if not file_path.exists():
        logger.warning(f"File {file_path} does not exist.")
        return 1
    file_size_bytes = file_path.stat().st_size
    if file_size_bytes == 0:
        return 1

    # CPU-bound tasks perform better on physical cores to avoid HT cache thrashing
    try:
        num_cores = psutil.cpu_count(logical=False) or os.cpu_count() or 1
    except Exception:
        num_cores = (os.cpu_count() or 2) // 2

    try:
        available_gb = psutil.virtual_memory().available / (1024 ** 3)
    except Exception:
        available_gb = 4.0

    file_size_gb = max(0.01, file_size_bytes / (1024 ** 3))

    # Base memory ~0.25GB per worker + small growth by file size
    process_memory_gb = 0.25 + 0.20 * file_size_gb

    # Clamp memory requirement to safe thresholds
    process_memory_gb = min(max(process_memory_gb, 0.25), 1.5)

    # Max workers RAM can safely host
    max_by_memory = max(1, int(available_gb // process_memory_gb))

    # File size base limit: 1 worker per 20MB (balanced concurrency vs spawn overhead)
    bytes_per_worker = 20 * 1024 * 1024
    max_by_file_size = max(1, file_size_bytes // bytes_per_worker)

    # Optimal count combines physical CPU, RAM and file scale constraints
    workers = min(num_cores, max_by_memory, max_by_file_size)
    return max(1, min(32, workers))
