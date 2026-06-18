import asyncio
import time
import math
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import List, Tuple
from pymavlink import mavutil
from src.models.bin_messages import BenchmarkResult
from src.services.bin_parser_service import BinParserService

def _parse_chunk_worker_shared(args: Tuple[Path, int, int]) -> int:
    file_path, start_offset, end_offset = args
    parser = BinParserService(file_path)
    with file_path.open('rb') as f:
        f.seek(start_offset)
        chunk_bytes = f.read(end_offset - start_offset)
    return parser.parse_chunk_range_bytes(chunk_bytes, 0, len(chunk_bytes))

def _compute_chunks(offsets: List[Tuple[int, int]], file_size: int, num_workers: int) -> List[Tuple[int, int]]:
    if not offsets: 
        return [(0, file_size)]
        
    chunk_size = math.ceil(len(offsets) / num_workers)
    boundaries = []
    
    for i in range(num_workers):
        start_idx = i * chunk_size
        if start_idx >= len(offsets): 
            break           
        end_idx = min((i + 1) * chunk_size, len(offsets) - 1)        
        start_offset = offsets[start_idx][0]
        end_offset = offsets[end_idx][0] if end_idx < len(offsets) - 1 and i < num_workers - 1 else file_size  
        boundaries.append((start_offset, end_offset))
    return boundaries

def benchmark_pymavlink(file_path: Path) -> BenchmarkResult:
    start = time.perf_counter()
    connection = mavutil.mavlink_connection(str(file_path))
    count = 0
    while connection.recv_match() is not None: count += 1
    return BenchmarkResult('pymavlink (Baseline)', count, time.perf_counter() - start)

def parse_sequential_fast(file_bytes: bytes, parser: BinParserService) -> BenchmarkResult:
    start = time.perf_counter()
    count = parser.parse_chunk_range_bytes(file_bytes, 0, len(file_bytes))
    return BenchmarkResult('Sequential (Custom)', count, time.perf_counter() - start)

def parse_threaded_fast(file_bytes: bytes, parser: BinParserService, offsets: List[Tuple[int, int]], file_size: int, num_workers: int) -> BenchmarkResult:
    boundaries = _compute_chunks(offsets, file_size, num_workers)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        results = executor.map(lambda b: parser.parse_chunk_range_bytes(file_bytes, b[0], b[1]), boundaries)
    return BenchmarkResult(f'ThreadPoolExecutor ({num_workers}w)', sum(results), time.perf_counter() - start)

def parse_multiprocess_fast(file_path: Path, offsets: List[Tuple[int, int]], file_size: int, num_workers: int) -> BenchmarkResult:
    boundaries = _compute_chunks(offsets, file_size, num_workers)
    chunk_args = [(file_path, s, e) for s, e in boundaries]
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        total = sum(executor.map(_parse_chunk_worker_shared, chunk_args))
    return BenchmarkResult(f'ProcessPoolExecutor ({num_workers}w)', total, time.perf_counter() - start)

async def _run_async_chunks_fast(file_bytes: bytes, parser: BinParserService, boundaries: List[Tuple[int, int]]) -> int:
    loop = asyncio.get_running_loop()
    tasks = [loop.run_in_executor(None, parser.parse_chunk_range_bytes, file_bytes, s, e) for s, e in boundaries]
    return sum(await asyncio.gather(*tasks))

def parse_async_fast(file_bytes: bytes, parser: BinParserService, offsets: List[Tuple[int, int]], file_size: int, num_workers: int) -> BenchmarkResult:
    boundaries = _compute_chunks(offsets, file_size, num_workers)
    start = time.perf_counter()
    total = asyncio.run(_run_async_chunks_fast(file_bytes, parser, boundaries))
    return BenchmarkResult(f'Asyncio ({num_workers}w)', total, time.perf_counter() - start)