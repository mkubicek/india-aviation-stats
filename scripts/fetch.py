"""Download and normalize official India aviation source data.

Sources:
  1. DGCA public Excel workbooks for domestic monthly and international
     quarterly aviation traffic.
  2. Optional MoCA daily HTML snapshots from the Internet Archive.

Raw files are cached under data/raw/ and normalized aggregate CSVs are written
under data/raw/aviation/aggregated/ for clean.py.
"""

import os
import time
from pathlib import Path

from normalize import ingest_aviation_sources, was_timed_out

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_TIMEOUT = int(os.environ.get("DOWNLOAD_TIMEOUT", 0))
_start_time = time.monotonic()
_timed_out = False


def _time_remaining() -> bool:
    """Check whether the soft download budget has expired."""
    global _timed_out
    if DOWNLOAD_TIMEOUT <= 0:
        return True
    if (time.monotonic() - _start_time) < DOWNLOAD_TIMEOUT:
        return True
    _timed_out = True
    return False


def write_github_output() -> None:
    """Expose soft-timeout status to GitHub Actions, when running in CI."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    timed_out = "true" if (_timed_out or was_timed_out()) else "false"
    with open(output_path, "a") as handle:
        handle.write(f"timed_out={timed_out}\n")


def download_aviation_sources() -> None:
    """Fetch and normalize DGCA/MoCA source data."""
    if not _time_remaining():
        print("  Soft timeout reached before aviation downloads", flush=True)
        return

    include_daily = os.environ.get("INCLUDE_MCA_DAILY", "0") == "1"
    refresh_urls = os.environ.get("DGCA_REFRESH_URLS", "1") != "0"
    ingest_aviation_sources(
        refresh_urls=refresh_urls,
        include_daily=include_daily,
        aggregate=True,
        timeout_started_at=_start_time,
    )


def cleanup_tmp_files() -> None:
    """Remove leftover .tmp files from interrupted downloads."""
    for tmp in RAW_DIR.rglob("*.tmp"):
        print(f"  Removing leftover: {tmp.name}", flush=True)
        tmp.unlink()


def main() -> None:
    print("=== Downloading Official Aviation Data ===\n", flush=True)
    cleanup_tmp_files()
    try:
        download_aviation_sources()
    finally:
        write_github_output()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
