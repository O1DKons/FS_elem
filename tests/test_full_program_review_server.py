import http.client
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from serve_full_program_review import make_handler


class RangeReviewServerTests(unittest.TestCase):
    def test_extra_review_routes_honor_ranges_and_hide_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "review.html").write_text("review", encoding="utf-8")
            (root / "video.mp4").write_bytes(b"main")
            (root / "index.html").write_text("index", encoding="utf-8")
            (root / "second.mp4").write_bytes(b"0123456789")
            (root / "private.txt").write_text("private", encoding="utf-8")
            handler = make_handler(
                root / "review.html", root / "video.mp4",
                extra_files={
                    "/index.html": (root / "index.html", "text/html; charset=utf-8"),
                    "/video/second.mp4": (root / "second.mp4", "video/mp4"),
                },
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/video/second.mp4", headers={"Range": "bytes=3-6"})
                response = connection.getresponse()
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), b"3456")
                connection.request("GET", "/private.txt")
                response = connection.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_video_route_honors_single_byte_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "review.html"
            video = root / "video.mp4"
            review.write_text("review", encoding="utf-8")
            video.write_bytes(b"0123456789")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(review, video))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/video.mp4", headers={"Range": "bytes=2-5"})
                response = connection.getresponse()
                body = response.read()
                self.assertEqual(response.status, 206)
                self.assertEqual(response.getheader("Content-Range"), "bytes 2-5/10")
                self.assertEqual(response.getheader("Accept-Ranges"), "bytes")
                self.assertEqual(body, b"2345")
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_unknown_route_is_not_exposed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "review.html"
            video = root / "video.mp4"
            review.write_text("review", encoding="utf-8")
            video.write_bytes(b"movie")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(review, video))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/data/live/fs-elem.sqlite")
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, 404)
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
