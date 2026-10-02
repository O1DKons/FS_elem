#!/usr/bin/env python3
"""Serve only the public demo, bound to loopback; no model/decode/network calls."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
parser = argparse.ArgumentParser(description='Локальная демонстрация FS_elem')
parser.add_argument('--port', type=int, default=5210)
args = parser.parse_args()
root = Path(__file__).resolve().parent
print(f'FS_elem: http://127.0.0.1:{args.port}/', flush=True)
try:
    ThreadingHTTPServer(('127.0.0.1', args.port), partial(SimpleHTTPRequestHandler, directory=str(root))).serve_forever()
except KeyboardInterrupt:
    pass
