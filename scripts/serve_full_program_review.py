"""Loopback-only server for a blind review page and its source video."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def make_handler(review_path, video_path, extra_files=None):
    files = {
        "/review.html": (Path(review_path).resolve(), "text/html; charset=utf-8"),
        "/video.mp4": (Path(video_path).resolve(), "video/mp4"),
    }
    if extra_files:
        if files.keys() & extra_files.keys():
            raise ValueError("Extra review routes cannot replace primary routes")
        files.update({url: (Path(path).resolve(), content_type)
                      for url, (path, content_type) in extra_files.items()})

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self._serve(send_body=True)

        def do_HEAD(self):
            self._serve(send_body=False)

        def _serve(self, *, send_body):
            if self.headers.get("Host") not in (
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            ):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            item = files.get(path)
            if item is None:
                self.send_error(404)
                return
            file_path, content_type = item
            try:
                file = file_path.open("rb")
            except OSError:
                self.send_error(404)
                return
            with file:
                size = file_path.stat().st_size
                start, end, status = 0, size - 1, 200
                requested = self.headers.get("Range")
                if requested:
                    parsed = self._parse_range(requested, size)
                    if parsed is None:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.send_header("Accept-Ranges", "bytes")
                        self.end_headers()
                        return
                    start, end = parsed
                    status = 206
                length = max(0, end - start + 1)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if send_body and length:
                    file.seek(start)
                    remaining = length
                    while remaining:
                        block = file.read(min(1024 * 256, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)

        @staticmethod
        def _parse_range(value, size):
            if not value.startswith("bytes=") or "," in value:
                return None
            spec = value[6:].strip()
            if "-" not in spec or size <= 0:
                return None
            first, last = spec.split("-", 1)
            try:
                if not first:
                    suffix = int(last)
                    if suffix <= 0:
                        return None
                    start, end = max(size - suffix, 0), size - 1
                else:
                    start = int(first)
                    end = size - 1 if not last else int(last)
            except ValueError:
                return None
            if start < 0 or end < start or start >= size:
                return None
            return start, min(end, size - 1)

        def log_message(self, *_args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--port", type=int, default=5197)
    args = parser.parse_args()
    if not args.review.is_file() or not args.video.is_file():
        raise ValueError("Review HTML and source video must exist")
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(args.review, args.video)
    )
    print(f"http://127.0.0.1:{server.server_port}/review.html", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
