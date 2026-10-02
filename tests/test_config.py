"""Tests for Settings behavior that isn't just field defaults."""
import pathlib
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


# ---- cookie content normalization/repair (handles paste mangling) ----
import http.cookiejar  # noqa: E402

from app.config import normalize_netscape_cookies  # noqa: E402


def _assert_loads_as_cookies(text, expected_count, tmp_path):
    p = tmp_path / "c.txt"
    p.write_text(text, encoding="utf-8")
    jar = http.cookiejar.MozillaCookieJar(str(p))
    jar.load(ignore_discard=True, ignore_expires=True)
    assert len(jar) == expected_count
    return jar


def test_normalize_passes_through_already_correct_file(tmp_path):
    raw = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tabc\n"
    out = normalize_netscape_cookies(raw)
    _assert_loads_as_cookies(out, 1, tmp_path)


def test_normalize_adds_missing_header(tmp_path):
    raw = ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tabc\n"
    out = normalize_netscape_cookies(raw)
    assert out.startswith("# Netscape HTTP Cookie File")
    _assert_loads_as_cookies(out, 1, tmp_path)


def test_normalize_reconstructs_tabs_lost_to_spaces(tmp_path):
    raw = "# Netscape HTTP Cookie File\n.youtube.com TRUE / TRUE 1999999999 SID abc\n"
    out = normalize_netscape_cookies(raw)
    _assert_loads_as_cookies(out, 1, tmp_path)


def test_normalize_converts_json_cookie_export(tmp_path):
    raw = '[{"domain": ".youtube.com", "name": "SID", "value": "abc", "path": "/", ' \
          '"secure": true, "expirationDate": 1999999999}]'
    out = normalize_netscape_cookies(raw)
    _assert_loads_as_cookies(out, 1, tmp_path)


def test_normalize_handles_crlf_line_endings(tmp_path):
    raw = "# Netscape HTTP Cookie File\r\n.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tabc\r\n"
    out = normalize_netscape_cookies(raw)
    assert "\r" not in out
    _assert_loads_as_cookies(out, 1, tmp_path)


def test_normalize_strips_surrounding_quotes_from_paste():
    raw = '"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1\tSID\tabc\n"'
    out = normalize_netscape_cookies(raw)
    assert not out.startswith('"')


def test_normalize_leaves_malformed_line_untouched_rather_than_guessing():
    # Only 5 fields (not 7) - can't be safely reconstructed, so it's left as-is.
    raw = "# Netscape HTTP Cookie File\nnot enough fields here\n"
    out = normalize_netscape_cookies(raw)
    assert "not enough fields here" in out


def test_materialize_cookies_file_applies_normalization(tmp_path):
    from app.config import Settings
    raw = ".youtube.com TRUE / TRUE 1999999999 SID abc"  # header missing, tabs lost
    s = Settings(_env_file=None, data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
                ytdlp_cookies_content=raw)
    s.ensure_dirs()
    written = pathlib.Path(s.ytdlp_cookies_file)
    jar = http.cookiejar.MozillaCookieJar(str(written))
    jar.load(ignore_discard=True, ignore_expires=True)
    assert len(jar) == 1
