"""Tests for the source-change fingerprint manifest."""

from manifest import (
    diff_manifests,
    fingerprint_sources,
    read_manifest,
    write_manifest_if_changed,
)


def _wb(path, content):
    path.write_bytes(content)


def test_fingerprint_is_deterministic_and_content_addressed(tmp_path):
    (tmp_path / "domestic").mkdir()
    (tmp_path / "international").mkdir()
    _wb(tmp_path / "domestic" / "a.xlsx", b"hello")
    _wb(tmp_path / "domestic" / "b.xls", b"world")
    _wb(tmp_path / "international" / "26Q1_4.pdf", b"pdf")
    rows = fingerprint_sources(tmp_path)
    assert [r["source"] for r in rows] == [
        "domestic/a.xlsx",
        "domestic/b.xls",
        "international/26Q1_4.pdf",
    ]
    assert all(len(r["sha256"]) == 64 and len(r["etag"]) == 32 for r in rows)
    assert rows[0]["source_type"] == "excel"
    assert rows[2]["source_type"] == "pdf"
    assert "temporary PDF fallback" in rows[2]["note"]
    # same content -> same fingerprint
    assert fingerprint_sources(tmp_path) == rows


def test_diff_distinguishes_added_changed_removed():
    old = [{"source": "a", "sha256": "1"}, {"source": "b", "sha256": "2"}]
    new = [{"source": "a", "sha256": "1"}, {"source": "b", "sha256": "X"},
           {"source": "c", "sha256": "3"}]
    d = diff_manifests(old, new)
    assert d == {"added": ["c"], "removed": [], "changed": ["b"]}


def test_write_only_on_change(tmp_path):
    manifest = tmp_path / "m.csv"
    rows = [
        {
            "source": "a.xlsx",
            "source_type": "excel",
            "note": "",
            "etag": "e",
            "content_length": "5",
            "sha256": "s",
        }
    ]
    assert write_manifest_if_changed(rows, manifest) is True       # first write
    assert write_manifest_if_changed(rows, manifest) is False      # identical -> no rewrite
    assert read_manifest(manifest) == rows
    rows2 = [
        {
            "source": "a.xlsx",
            "source_type": "excel",
            "note": "",
            "etag": "e2",
            "content_length": "6",
            "sha256": "s2",
        }
    ]
    assert write_manifest_if_changed(rows2, manifest) is True      # changed -> rewrite
