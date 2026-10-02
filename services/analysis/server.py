"""Local readiness service. Model execution is deliberately outside tasks 1–4."""
import argparse
import json
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status = 200 if self.path == '/health' else 404
        payload = {'service': 'fs-elem-analysis', 'status': 'ready',
                   'inferenceAvailable': False, 'python': sys.version.split()[0]}
        body = json.dumps(payload if status == 200 else {'error': 'Not found'}).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    if sys.version_info < (3, 12):
        raise SystemExit('FS_elem requires Python 3.12 or later. Run setup first.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5175)
    args = parser.parse_args()
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        print(json.dumps({'port': server.server_port}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
