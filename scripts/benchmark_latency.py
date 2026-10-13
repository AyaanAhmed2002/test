"""
scripts/benchmark_latency.py
────────────────────────────
Measures per-invoice extraction latency across all PDFs in testdata/.

Usage (from project root, with .venv active):
    python scripts/benchmark_latency.py

Output: per-invoice timing + summary statistics (min, median, p95, max).
Requires: python scripts/generate_test_invoices.py  (to populate testdata/)
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

# Ensure the project root is on the path so `app` is importable.
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.pdf_reader import concatenate_pages, read_pdf  # noqa: E402
from app.pipeline import run_extraction_pipeline        # noqa: E402

TESTDATA = PROJECT_ROOT / "testdata"
COL_W = 14


def _bar(score: float, width: int = 20) -> str:
    filled = round(score * width)
    return "[" + "#" * filled + "." * (width - filled) + f"] {score:.2f}"


def run() -> None:
    pdfs = sorted(TESTDATA.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found in testdata/. Run scripts/generate_test_invoices.py first.")
        sys.exit(1)

    print(f"\nBenchmarking {len(pdfs)} invoice PDFs...\n")
    header = f"{'File':<20} {'Read ms':>9} {'Pipeline ms':>12} {'Total ms':>10}  Vendor"
    print(header)
    print("-" * len(header))

    timings: list[float] = []
    read_timings: list[float] = []
    pipe_timings: list[float] = []

    for pdf_path in pdfs:
        data = pdf_path.read_bytes()

        # Time PDF reading
        t0 = time.perf_counter()
        pages = read_pdf(data)
        full_text = concatenate_pages(pages)
        t1 = time.perf_counter()
        read_ms = (t1 - t0) * 1000

        # Time extraction pipeline
        t2 = time.perf_counter()
        result = run_extraction_pipeline(full_text)
        t3 = time.perf_counter()
        pipe_ms = (t3 - t2) * 1000

        total_ms = read_ms + pipe_ms
        timings.append(total_ms)
        read_timings.append(read_ms)
        pipe_timings.append(pipe_ms)

        print(
            f"{pdf_path.name:<20} {read_ms:>9.2f} {pipe_ms:>12.2f} {total_ms:>10.2f}"
            f"  {result.vendor}"
        )

    print("-" * len(header))

    def stats_line(label: str, data: list[float]) -> str:
        s = sorted(data)
        p95_idx = max(0, int(len(s) * 0.95) - 1)
        return (
            f"{label:<20} {min(s):>9.2f} {'':>12} {max(s):>10.2f}"
            f"  median={statistics.median(s):.2f} ms  p95={s[p95_idx]:.2f} ms"
        )

    print()
    s = sorted(timings)
    p95_idx = max(0, int(len(s) * 0.95) - 1)
    print("Summary (total end-to-end latency per invoice):")
    print(f"  Count   : {len(timings)}")
    print(f"  Min     : {min(timings):.2f} ms")
    print(f"  Median  : {statistics.median(timings):.2f} ms")
    print(f"  p95     : {s[p95_idx]:.2f} ms")
    print(f"  Max     : {max(timings):.2f} ms")
    print(f"  Mean    : {statistics.mean(timings):.2f} ms")
    print()

    over_50 = [t for t in timings if t > 50]
    if over_50:
        print(f"  WARNING: {len(over_50)} invoice(s) exceeded 50 ms SLA.")
    else:
        print("  All invoices processed within 50 ms SLA.")


if __name__ == "__main__":
    run()
