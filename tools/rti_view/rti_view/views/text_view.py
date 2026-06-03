"""Text view — simple scrolling field value display."""

import asyncio
import time
from typing import Callable


async def run_text_view(reader, field_path: str, topic_name: str):
    """Print field values to stdout as they arrive (headless text mode)."""
    print(f"--- rti_view text: {topic_name}.{field_path} ---")
    while True:
        for data, info in reader.take():
            if info.valid:
                value = data[field_path]
                ts = time.time()
                print(f"[{ts:.3f}] {field_path} = {value}")
        await asyncio.sleep(0.05)
