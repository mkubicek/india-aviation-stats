"""Multi-source data downloader for India aviation statistics.

Sources:
  1. World Bank API — GDP per capita PPP, population, air passengers
  2. DGCA/MoCA official sources — raw workbooks/HTML normalized locally
  3. IMF WEO — GDP projections (Excel)

Downloads are cached locally with If-Modified-Since freshness checks.
"""

import json
import os
import time
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path

import requests

from ingest_sources import ingest_aviation_sources, was_timed_out

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_TIMEOUT = int(os.environ.get("DOWNLOAD_TIMEOUT", 0))
_start_time = time.monotonic()
_timed_out = False

# ── World Bank indicators ────────────────────────────────────

WORLD_BANK_INDICATORS = {
    "NY.GDP.PCAP.PP.CD": "gdp_per_capita_ppp",
    "SP.POP.TOTL": "population",
    "IS.AIR.PSGR": "air_passengers",
}

WORLD_BANK_URL = (
    "https://api.worldbank.org/v2/country/IND/indicator/{indicator}"
    "?format=json&per_page=100&date=1990:2025"
)

# ── Helpers ──────────────────────────────────────────────────


def _time_remaining() -> bool:
    """Check if we have time for another download (soft timeout)."""
    global _timed_out
    if DOWNLOAD_TIMEOUT <= 0:
        return True
    elapsed = time.monotonic() - _start_time
    if elapsed < DOWNLOAD_TIMEOUT:
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


def download_file(url: str, dest: Path, force: bool = False) -> bool:
    """Download a file, skipping if local copy is fresh. Returns True if updated."""
    if not _time_remaining():
        print(f"  Soft timeout reached, skipping: {dest.name}", flush=True)
        return False

    headers = {}
    if dest.exists() and not force:
        local_mtime = dest.stat().st_mtime
        headers["If-Modified-Since"] = formatdate(local_mtime, usegmt=True)

        print(f"  Checking freshness: {dest.name}", flush=True)
        try:
            resp = requests.head(url, headers=headers, timeout=30, allow_redirects=True)
            if resp.status_code == 304:
                print(f"  Up to date (cached): {dest.name}", flush=True)
                return False
        except requests.RequestException:
            pass  # Fall through to full download

    print(f"  Downloading: {url}", flush=True)
    try:
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ERROR downloading {dest.name}: {e}", flush=True)
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    downloaded = 0
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
    tmp.rename(dest)

    # Sync local mtime to server's Last-Modified
    if "Last-Modified" in resp.headers:
        try:
            server_dt = parsedate_to_datetime(resp.headers["Last-Modified"])
            server_mtime = server_dt.timestamp()
            os.utime(dest, (server_mtime, server_mtime))
        except Exception:
            pass

    size_kb = dest.stat().st_size / 1024
    print(f"  Saved: {dest.name} ({size_kb:.0f} KB)", flush=True)
    return True


# ── World Bank API ───────────────────────────────────────────


def download_world_bank():
    """Fetch World Bank indicators for India as JSON."""
    print("\n── World Bank API ──", flush=True)
    wb_dir = RAW_DIR / "worldbank"
    wb_dir.mkdir(parents=True, exist_ok=True)

    for indicator, name in WORLD_BANK_INDICATORS.items():
        if not _time_remaining():
            print("  Soft timeout reached, stopping World Bank downloads", flush=True)
            break

        url = WORLD_BANK_URL.format(indicator=indicator)
        dest = wb_dir / f"{name}.json"

        print(f"  Fetching {name} ({indicator})...", flush=True)
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            dest.write_text(json.dumps(data, indent=2))
            print(f"  Saved: {dest.name}", flush=True)
        except requests.RequestException as e:
            print(f"  ERROR fetching {name}: {e}", flush=True)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  ERROR parsing {name}: {e}", flush=True)


# ── Official aviation sources ────────────────────────────────


def download_aviation_sources():
    """Fetch and normalize DGCA/MoCA source data without Vonter."""
    include_daily = os.environ.get("INCLUDE_MCA_DAILY", "0") == "1"
    refresh_urls = os.environ.get("DGCA_REFRESH_URLS", "1") != "0"
    ingest_aviation_sources(
        refresh_urls=refresh_urls,
        include_daily=include_daily,
        aggregate=True,
        timeout_started_at=_start_time,
    )


# ── Cleanup ──────────────────────────────────────────────────


def cleanup_tmp_files():
    """Remove leftover .tmp files from interrupted downloads."""
    for tmp in RAW_DIR.rglob("*.tmp"):
        print(f"  Removing leftover: {tmp.name}", flush=True)
        tmp.unlink()


# ── Main ─────────────────────────────────────────────────────


def main():
    print("=== Downloading Data ===\n", flush=True)
    cleanup_tmp_files()
    try:
        download_world_bank()
        download_aviation_sources()
    finally:
        write_github_output()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
