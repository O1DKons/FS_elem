#!/usr/bin/env python3
"""Serve only the public demo, bound to loopback; no model/decode/network calls."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import re
parser = argparse.ArgumentParser(description='Локальная демонстрация FS_elem')
parser.add_argument('--port', type=int, default=5210)
args = parser.parse_args()
root = Path(__file__).resolve().parent
class VideoHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        self.range_left = None
        path = Path(self.translate_path(self.path))
        requested = self.headers.get('Range')
        if not requested or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
        start, end = 0, size - 1
        if match:
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            elif last:
                start = max(0, size - int(last))
            else:
                match = None
        if not match or start > end or start >= size:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        stream = path.open('rb')
        stream.seek(start)
        self.range_left = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(self.range_left))
        self.end_headers()
        return stream

    def copyfile(self, source, outputfile):
        if self.range_left is None:
            return super().copyfile(source, outputfile)
        while self.range_left:
            block = source.read(min(65536, self.range_left))
            if not block:
                break
            outputfile.write(block)
            self.range_left -= len(block)

print(f'FS_elem: http://127.0.0.1:{args.port}/', flush=True)
try:
    ThreadingHTTPServer(('127.0.0.1', args.port), partial(VideoHandler, directory=str(root))).serve_forever()
except KeyboardInterrupt:
    pass
