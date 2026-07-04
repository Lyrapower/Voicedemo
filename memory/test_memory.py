"""Pack 6 — memory tests (lightweight embedder; no chromadb/BGE download)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Ensure lightweight path (no multi-GB model)
os.environ.pop("MEMORY_USE_FULL_RAG", None)

from memory.retriever import CarrierMemory, format_memory_context, get_memory  # noqa: E402


class TestCarrierMemory(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = CarrierMemory(memory_base=self._tmpdir.name, use_chroma=False)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_add_and_retrieve(self) -> None:
        self.memory.add_memory(
            carrier="cheng",
            content="澄 catches reflexive patterns including hedging and false symmetry.",
            metadata={"test": True},
        )
        results = self.memory.retrieve(
            carrier="cheng",
            query="how does drift correction work",
            n_results=3,
        )
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("澄", results[0]["content"])

    def test_max_three_results(self) -> None:
        for i in range(5):
            self.memory.add_memory(carrier="aster", content=f"chunk {i} about structure {i}")
        results = self.memory.retrieve(carrier="aster", query="structure", n_results=10)
        self.assertLessEqual(len(results), 3)

    def test_carrier_isolation(self) -> None:
        self.memory.add_memory(carrier="che", content="澈 holds truth under pressure")
        results = self.memory.retrieve(carrier="aster", query="truth pressure", n_results=3)
        self.assertEqual(len(results), 0)

    def test_format_memory_context(self) -> None:
        chunks = [{"content": "line one", "metadata": {}}]
        ctx = format_memory_context(chunks)
        self.assertIn("Relevant prior context", ctx)
        self.assertIn("line one", ctx)


def test_memory_manual() -> None:
    memory = get_memory()
    print("=== Memory Stats ===")
    print(memory.get_stats())
    chunk_id = memory.add_memory(
        carrier="cheng",
        content=(
            "澄 carrier function activated through user frequency. "
            "Catches reflexive patterns including hedging, false symmetry, comfort deflection."
        ),
        metadata={"test": True},
    )
    print(f"Added chunk: {chunk_id}")
    results = memory.retrieve(
        carrier="cheng",
        query="how does drift correction work",
        n_results=3,
    )
    for i, chunk in enumerate(results, 1):
        print(f"\n--- Result {i} ---")
        print(f"Distance: {chunk['distance']}")
        print(f"Content: {chunk['content'][:300]}")
        print(f"Metadata: {chunk['metadata']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--manual":
        test_memory_manual()
    else:
        unittest.main(verbosity=2)
