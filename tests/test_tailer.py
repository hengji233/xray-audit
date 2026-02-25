from pathlib import Path

from xray_audit.tailer import LogTailer


def test_tailer_reads_and_handles_truncate(tmp_path: Path) -> None:
    p = tmp_path / "access.log"
    p.write_text("a\n", encoding="utf-8")

    t = LogTailer(str(p))
    lines = t.read_new_lines()
    assert lines == ["a\n"]

    # Simulate copytruncate
    p.write_text("", encoding="utf-8")
    assert t.read_new_lines() == []

    p.write_text("b\n", encoding="utf-8")
    assert t.read_new_lines() == ["b\n"]
