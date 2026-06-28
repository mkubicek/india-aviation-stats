"""Download DGCA source files and refresh the source fingerprint manifest.

Fetches DGCA public Excel workbooks plus documented PDF fallbacks, normalizes
them into aggregate CSVs under data/raw/aviation/aggregated/ for clean.py, and
updates sources_manifest.csv.
"""

import os
import time
from pathlib import Path

from manifest import update_manifest
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
    """Fetch and normalize DGCA source data."""
    if not _time_remaining():
        print("  Soft timeout reached before aviation downloads", flush=True)
        return

    refresh_urls = os.environ.get("DGCA_REFRESH_URLS", "1") != "0"
    ingest_aviation_sources(
        refresh_urls=refresh_urls,
        aggregate=True,
        timeout_started_at=_start_time,
    )


def cleanup_tmp_files() -> None:
    """Remove leftover .tmp files from interrupted downloads."""
    for tmp in RAW_DIR.rglob("*.tmp"):
        print(f"  Removing leftover: {tmp.name}", flush=True)
        tmp.unlink()


def refresh_sources_manifest() -> None:
    """Update the committed fingerprint manifest (commit-on-change)."""
    report = update_manifest()
    note = "changed" if report["written"] else "unchanged"
    print(f"  sources_manifest: {report['sources']} source(s), manifest {note} "
          f"(added={len(report['added'])}, changed={len(report['changed'])}, "
          f"removed={len(report['removed'])})", flush=True)
    for s in report["changed"]:
        print(f"    CHANGED: {s}", flush=True)
    for s in report["added"]:
        print(f"    NEW: {s}", flush=True)


def main() -> None:
    print("=== Downloading Official Aviation Data ===\n", flush=True)
    cleanup_tmp_files()
    try:
        download_aviation_sources()
        refresh_sources_manifest()
    finally:
        write_github_output()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
