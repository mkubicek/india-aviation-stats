"""Tests for downloader CI helpers."""

import download


def test_write_github_output_emits_timeout_flag(tmp_path, monkeypatch):
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(download, "_timed_out", True)

    download.write_github_output()

    assert output.read_text() == "timed_out=true\n"
