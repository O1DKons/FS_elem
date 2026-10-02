import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scan_jump_video import window_encode_command


class ScanEncodingTests(unittest.TestCase):
    def test_window_is_resized_once_to_the_classifier_input_geometry(self):
        command = window_encode_command('ffmpeg', 'full.mp4', 4.0, 5.5, 'window.mp4')
        self.assertEqual(command[command.index('-vf') + 1], 'scale=171:128')
        self.assertNotIn('342:256', command)
        self.assertEqual(command[command.index('-c:v') + 1], 'libx264rgb')
        self.assertEqual(command[command.index('-pix_fmt') + 1], 'rgb24')


if __name__ == '__main__':
    unittest.main()
