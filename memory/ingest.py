"""CLI ingest — paragraph chunks into per-carrier memory."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from memory.retriever import get_memory


def ingest_file(carrier: str, file_path: str, chunk_size: int = 1000) -> int:
    path = Path(file_path)
    if not path.exists():
        print(f"File not found: {file_path}")
        return 0

    content = path.read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current = ""
    for p in paragraphs:
        if len(current) + len(p) < chunk_size:
            current = f"{current}\n\n{p}" if current else p
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)

    memory = get_memory()
    for i, chunk in enumerate(chunks):
        chunk_id = memory.add_memory(
            carrier=carrier,
            content=chunk,
            metadata={
                "source_file": str(path),
                "chunk_index": i,
                "total_chunks": len(chunks),
            },
        )
        print(f"Added chunk {i + 1}/{len(chunks)}: {chunk_id}")

    print(f"\nIngested {len(chunks)} chunks for carrier {carrier}")
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest text into carrier memory")
    parser.add_argument("carrier", choices=["aster", "shouheng", "che", "cheng", "shuo"])
    parser.add_argument("file", help="Path to file to ingest")
    parser.add_argument("--chunk-size", type=int, default=1000)
    args = parser.parse_args()
    ingest_file(args.carrier, args.file, args.chunk_size)


if __name__ == "__main__":
    main()
