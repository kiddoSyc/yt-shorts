"""Test helper: a local HTTP server with Range support plus generated test media.

It stands in for YouTube's media servers so the low-data pipeline can be tested
offline with real FFmpeg: separate video-only and audio-only files, like DASH.
"""
import http.server
import os
import re
import socketserver
import subprocess
import tempfile
import threading

MEDIA_SECONDS = 240
_media_dir = None


def media_dir() -> str:
    """Generate (once per process) a 4-minute video-only and audio-only file."""
    global _media_dir
    if _media_dir is None:
        d = tempfile.mkdtemp(prefix="testmedia_")
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
             "-t", str(MEDIA_SECONDS), "-c:v", "libx264", "-preset", "veryfast", "-b:v", "300k",
             "-maxrate", "350k", "-bufsize", "600k", "-g", "50", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", os.path.join(d, "video_only.mp4")], check=True)
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100",
             "-t", str(MEDIA_SECONDS), "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart",
             os.path.join(d, "audio_only.m4a")], check=True)
        _media_dir = d
    return _media_dir


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    root = "."

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = os.path.join(self.root, self.path.lstrip("/").split("?")[0])
        if not os.path.isfile(path):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        size = os.path.getsize(path)
        start, end, code = 0, size - 1, 200
        match = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
        if match:
            start = int(match.group(1))
            end = min(int(match.group(2)) if match.group(2) else size - 1, size - 1)
            code = 206
        self.send_response(code)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Type", "video/mp4")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start_server(root: str):
    """Returns (server, base_url). Call server.shutdown() when done."""
    handler = type("Handler", (_Handler,), {"root": root})
    server = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
