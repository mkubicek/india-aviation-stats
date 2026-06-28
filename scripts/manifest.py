"""Source-change detection via a committed fingerprint manifest.

``data/sources_manifest.csv`` records one row per raw DGCA workbook:
``source, etag, content_length, sha256``. It is committed and rewritten **only
when a fingerprint actually changes**, so the git history of this one file is a
clean log of real DGCA source changes (no monthly no-op churn). The ``etag`` is
the file's MD5 hex — which equals an S3 single-part object's ETag — so a HEAD
sweep can compare it against the live ETag without transferring the body. The
``sha256`` over the actually-downloaded file is the ground-truth detector;
HEAD/ETag is only the cheap pre-filter (it is incomplete for multipart objects
and hosts without HEAD, where sha256 still catches the change).
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DGCA = ROOT / "data" / "raw" / "aviation" / "dgca" / "xlsx"
MANIFEST_PATH = ROOT / "data" / "sources_manifest.csv"
FIELDS = ["source", "etag", "content_length", "sha256"]


def _hashes(path: Path) -> tuple[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def fingerprint_sources(raw_dir: Path = RAW_DGCA) -> list[dict]:
    """Fingerprint every raw workbook under ``raw_dir`` (sorted, deterministic)."""
    rows = []
    if not raw_dir.exists():
        return rows
    for path in sorted(raw_dir.rglob("*")):
        if path.suffix.lower() not in {".xls", ".xlsx"} or path.name.endswith(".tmp"):
            continue
        etag, sha = _hashes(path)
        rows.append({
            "source": str(path.relative_to(raw_dir)),
            "etag": etag,
            "content_length": str(path.stat().st_size),
            "sha256": sha,
        })
    return rows


def read_manifest(path: Path = MANIFEST_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as fh:
        return list(csv.DictReader(fh))


def diff_manifests(old: list[dict], new: list[dict]) -> dict:
    """Distinguish a content change to a known file from a new workbook appearing."""
    old_by = {r["source"]: r for r in old}
    new_by = {r["source"]: r for r in new}
    added = sorted(set(new_by) - set(old_by))
    removed = sorted(set(old_by) - set(new_by))
    changed = sorted(
        s for s in (set(old_by) & set(new_by))
        if old_by[s]["sha256"] != new_by[s]["sha256"]
    )
    return {"added": added, "removed": removed, "changed": changed}


def write_manifest_if_changed(rows: list[dict], path: Path = MANIFEST_PATH) -> bool:
    """Write the manifest only if it differs from the committed one (commit-on-change).

    Returns True if the file was (re)written.
    """
    if rows == read_manifest(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return True


def update_manifest(raw_dir: Path = RAW_DGCA, path: Path = MANIFEST_PATH) -> dict:
    """Fingerprint sources, diff against the committed manifest, write on change."""
    new = fingerprint_sources(raw_dir)
    old = read_manifest(path)
    diff = diff_manifests(old, new)
    written = write_manifest_if_changed(new, path)
    return {"sources": len(new), "written": written, **diff}


def head_change(url: str, manifest_row: dict | None, session) -> str:
    """Cheap pre-filter: HEAD a URL and compare ETag/Content-Length to the manifest.

    Returns "unchanged" | "changed" | "unknown" (HEAD unsupported / no row);
    "unknown" means fall back to a conditional GET and let sha256 decide.
    """
    if manifest_row is None:
        return "changed"
    try:
        resp = session.head(url, timeout=60, allow_redirects=True)
    except Exception:
        return "unknown"
    if resp.status_code >= 400:
        return "unknown"
    etag = resp.headers.get("ETag", "").strip('"')
    length = resp.headers.get("Content-Length")
    if etag and etag == manifest_row.get("etag"):
        return "unchanged"
    if length and length == manifest_row.get("content_length"):
        return "unchanged"
    if not etag and not length:
        return "unknown"
    return "changed"


if __name__ == "__main__":
    report = update_manifest()
    print(f"sources_manifest: {report['sources']} sources, written={report['written']}, "
          f"added={len(report['added'])}, changed={len(report['changed'])}, "
          f"removed={len(report['removed'])}")
