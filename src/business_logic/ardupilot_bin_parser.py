from __future__ import annotations

import asyncio
import gc
import math
import mmap
import os
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.business_logic.format_bank import load_message_formats
from src.config.constants import MAX_CHUNK_SIZE_BYTES, MESSAGE_HEADER
from src.config.logging_config import get_logger
from src.config.worker_config import get_optimal_num_workers
from src.models.bin_messages import Message, MessageFormat
from src.parsing_methods.shared import merge_dicts, multiprocessing_byte_worker, parse_bytes_to_dict

logger = get_logger(__name__)


class BinParser:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.formats: Dict[int, MessageFormat] = load_message_formats(file_path)
        self.all_messages: Optional[Dict[str, List[Dict]]] = None

    def parse_all_messages(
        self,
        parsing_mode: str = "simple",
        num_workers: Optional[int] = None,
        wanted_names: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict]]:
        """
        Parses the entire BIN file using simple, threads, processes, or async execution.

        """
        if not self.file_path.exists():
            logger.warning(f"File {self.file_path} does not exist.")
            return {}
        if self.file_path.stat().st_size == 0:
            return {}

        if parsing_mode == "simple":
            with self.file_path.open("rb") as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as file_bytes:
                    self.all_messages = parse_bytes_to_dict(file_bytes, 0, len(file_bytes), self.formats, wanted_names)
        else:
            if num_workers is None:
                num_workers = get_optimal_num_workers(self.file_path)

            file_size = self.file_path.stat().st_size
            chunk_size = min(math.ceil(file_size / num_workers), MAX_CHUNK_SIZE_BYTES)
            num_chunks = math.ceil(file_size / chunk_size)
            chunk_args = [
                (self.file_path, i * chunk_size, min((i + 1) * chunk_size, file_size), wanted_names)
                for i in range(num_chunks)
            ]
            executor: Executor
            if parsing_mode == "threads":
                was_enabled = gc.isenabled()
                if was_enabled:
                    gc.disable()
                try:
                    with ThreadPoolExecutor(max_workers=num_workers) as executor:
                        results = list(executor.map(multiprocessing_byte_worker, chunk_args))
                finally:
                    if was_enabled:
                        gc.enable()
                self.all_messages = merge_dicts(results)

            elif parsing_mode == "processes":
                with ProcessPoolExecutor(max_workers=num_workers) as executor:
                    results = list(executor.map(multiprocessing_byte_worker, chunk_args))
                self.all_messages = merge_dicts(results)

            elif parsing_mode == "async":
                executor = ProcessPoolExecutor(max_workers=num_workers)

                async def _run_async_chunks() -> List[Dict[str, List[Any]]]:
                    loop = asyncio.get_running_loop()
                    tasks = [loop.run_in_executor(executor, multiprocessing_byte_worker, args) for args in chunk_args]
                    return await asyncio.gather(*tasks)

                try:
                    results = asyncio.run(_run_async_chunks())
                    self.all_messages = merge_dicts(results)
                except Exception as e:
                    logger.warning(f"Asyncio parsing failed ({e}), falling back to sync multiprocessing...")
                    results = list(executor.map(multiprocessing_byte_worker, chunk_args))
                    self.all_messages = merge_dicts(results)
                finally:
                    executor.shutdown(wait=True)
            else:
                raise ValueError(f"Unknown parsing mode: {parsing_mode}")

        return self.all_messages

    def get_gps_messages(self) -> List[Message]:
        """Decodes GPS messages quickly using the fast byte parser."""
        gps_dict = self.parse_all_messages(parsing_mode="simple", wanted_names=["GPS"])
        gps_format = next((f for f in self.formats.values() if f.name == "GPS"), None)
        column_names = gps_format.columns if gps_format else []
        messages = []
        for row in gps_dict.get("GPS", []):
            message_columns = column_names
            if len(row) > len(column_names):
                message_columns = list(column_names) + ["timestamp"]
            messages.append(Message(type_id=87, name="GPS", fields=dict(zip(message_columns, row))))
        return messages

    def get_message_type_summary(self) -> Dict[str, int]:
        """Counts instances of each message type inside the log file."""
        parsed = self.parse_all_messages(parsing_mode="simple")
        return {name: len(messages) for name, messages in parsed.items() if messages}

    def describe(self) -> None:
        """Logs a summary description of the file structure."""
        file_size = self.file_path.stat().st_size
        logger.info(f"  File: {self.file_path.name}")
        logger.info(f"  Size: {file_size / (1024 * 1024):.2f} MB ({file_size:,} bytes)")
        logger.info(f"  Message Formats Found: {len(self.formats)}")
        logger.info("")
        logger.info(f"  {'#':<5} {'Type ID':<10} {'Name':<12} {'Length':<10} {'Format':<20} {'Columns'}")
        logger.info(f"  {'-' * 5} {'-' * 10} {'-' * 12} {'-' * 10} {'-' * 20} {'-' * 40}")
        for idx, (type_id, fmt) in enumerate(sorted(self.formats.items()), start=1):
            cols = ", ".join(fmt.columns[:5])
            if len(fmt.columns) > 5:
                cols += f" ... (+{len(fmt.columns) - 5})"
            logger.info(f"  {idx:<5} {type_id:<10} {fmt.name:<12} {fmt.length:<10} {fmt.format_string:<20} {cols}")
