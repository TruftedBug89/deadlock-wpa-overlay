"""Windowed print output cannot grow the local debug file without bound."""

from app_logging import SafeLogStream


def test_large_write_is_bounded_and_rotated(tmp_path):
    path = tmp_path / "debug.log"
    stream = SafeLogStream(path, max_bytes=512, backup_count=2)
    text = "x" * 10000
    assert stream.write(text) == len(text)
    stream.close()
    files = list(tmp_path.glob("debug.log*"))
    assert len(files) == 3
    assert all(file.stat().st_size <= 512 for file in files)


def test_unwritable_stream_is_harmless(tmp_path):
    parent = tmp_path / "file"
    parent.touch()
    stream = SafeLogStream(parent / "debug.log")
    assert stream.write("hello") == 5
    stream.flush()
