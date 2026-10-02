"""Tests for Settings behavior that isn't just field defaults."""
from app.config import Settings


def test_ensure_dirs_creates_expected_folders(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    s.ensure_dirs()
    for d in (s.downloads_dir, s.transcripts_dir, s.clips_dir, s.output_dir, s.shorts_dir,
             s.tmp_dir, s.logs_dir):
        assert d.is_dir()


def test_cookies_content_materializes_to_a_file(tmp_path):
    content = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tfoo\tbar\n"
    s = Settings(_env_file=None, data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
                ytdlp_cookies_content=content)
    assert s.ytdlp_cookies_file == ""  # not materialized until ensure_dirs() runs
    s.ensure_dirs()
    assert s.ytdlp_cookies_file != ""
    written = tmp_path / "data" / "cookies.txt"
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == content


def test_cookies_content_does_not_override_an_explicit_file_path(tmp_path):
    existing = tmp_path / "my_cookies.txt"
    existing.write_text("existing content", encoding="utf-8")
    s = Settings(_env_file=None, data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
                ytdlp_cookies_file=str(existing), ytdlp_cookies_content="should be ignored")
    s.ensure_dirs()
    assert s.ytdlp_cookies_file == str(existing)
    assert existing.read_text(encoding="utf-8") == "existing content"


def test_no_cookies_configured_leaves_file_path_empty(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    s.ensure_dirs()
    assert s.ytdlp_cookies_file == ""
