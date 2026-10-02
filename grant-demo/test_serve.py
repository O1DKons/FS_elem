"""Narrow HTTP media transport regression; no video decode or models."""
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


class RangeTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        cls.base = f'http://127.0.0.1:{port}/'
        cls.child = subprocess.Popen([sys.executable, str(cls.root/'serve.py'), '--port', str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with urllib.request.urlopen(cls.base+'app.js', timeout=.2):
                    return
            except (OSError, urllib.error.URLError):
                if cls.child.poll() is not None:
                    raise RuntimeError('Demo server exited before readiness')
                time.sleep(.02)
        cls.child.terminate()
        raise RuntimeError('Demo server did not become ready')

    @classmethod
    def tearDownClass(cls):
        cls.child.terminate()
        cls.child.wait(timeout=5)

    def request(self, value, method='GET'):
        return urllib.request.urlopen(urllib.request.Request(self.base+'app.js', headers={'Range':value}, method=method), timeout=2)

    def test_exact_prefix(self):
        data = (self.root/'app.js').read_bytes()
        with self.request('bytes=0-99') as r:
            self.assertEqual(r.status, 206)
            self.assertEqual(r.read(), data[:100])
            self.assertEqual(r.headers['Content-Range'], f'bytes 0-99/{len(data)}')

    def test_suffix_and_head(self):
        data = (self.root/'app.js').read_bytes()
        with self.request('bytes=-20') as r:
            self.assertEqual(r.read(), data[-20:])
        with self.request('bytes=10-29', 'HEAD') as r:
            self.assertEqual(r.status, 206)
            self.assertEqual(r.headers['Content-Length'], '20')
            self.assertEqual(r.read(), b'')

    def test_outside_and_multiple_ranges_rejected(self):
        size = (self.root/'app.js').stat().st_size
        for value in [f'bytes={size}-', 'bytes=0-1,2-3', 'bytes=99-1']:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(value)
            self.assertEqual(error.exception.code, 416)
            self.assertEqual(error.exception.headers['Content-Range'], f'bytes */{size}')


if __name__ == '__main__':
    unittest.main()
