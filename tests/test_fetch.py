"""Tests for fetch CI helpers."""

import fetch


def test_write_github_output_emits_timeout_flag(tmp_path, monkeypatch):
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(fetch, "_timed_out", True)

    fetch.write_github_output()

    assert output.read_text() == "timed_out=true\n"
