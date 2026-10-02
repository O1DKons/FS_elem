import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_full_program_review import render_review


class FullProgramReviewTests(unittest.TestCase):
    def test_page_is_blind_and_exports_source_bound_annotation_contract(self):
        html = render_review(
            video_url="../../data/live/media/comp-20.mp4",
            review_id="competition-20-full-program",
            duration=188.23,
            fps=50.0,
            source_sha256="a" * 64,
        )

        self.assertIn('src="../../data/live/media/comp-20.mp4"', html)
        self.assertIn('id="export-json"', html)
        self.assertIn('"sourceSha256":"' + "a" * 64 + '"', html)
        self.assertIn('coverageReviewed:true', html)
        self.assertIn('value="other_jump"', html)
        self.assertIn('value="axel"', html)
        self.assertNotIn("uncalibratedMargin", html)
        self.assertNotIn("elementProposal", html)
        self.assertFalse("uncalibratedMargin" in html, "scan scores must stay hidden")
        self.assertFalse("34.5-36.0" in html, "candidate timestamps must stay hidden")

    def test_renderer_rejects_invalid_video_metadata(self):
        with self.assertRaises(ValueError):
            render_review(
                video_url="video.mp4",
                review_id="bad",
                duration=0,
                fps=50,
                source_sha256="x",
            )

    def test_empty_annotation_rows_are_safe_until_contacts_are_marked(self):
        html = render_review(
            video_url="video.mp4",
            review_id="review",
            duration=10,
            fps=50,
            source_sha256="b" * 64,
        )
        self.assertIn("!field || field.value === '' ? null", html)

    def test_new_event_requires_an_explicit_class_choice(self):
        html = render_review(
            video_url="video.mp4",
            review_id="review",
            duration=10,
            fps=50,
            source_sha256="c" * 64,
        )
        self.assertIn('<option value="" selected disabled>Выберите тип</option>', html)
        self.assertIn("value.eventClass || ''", html)
        self.assertIn("if (!e.eventClass) return setStatus", html)

    def test_instructions_require_all_jumps_and_separate_combo_elements(self):
        html = render_review(
            video_url="video.mp4",
            review_id="review",
            duration=10,
            fps=50,
            source_sha256="d" * 64,
        ).lower()

        self.assertIn("все прыжки, не только аксели", html)
        self.assertIn("каждый прыжок в комбинации отмечайте отдельно", html)
        self.assertIn("другой прыжок", html)

    def test_header_displays_configured_frame_rate(self):
        html = render_review(
            video_url="video.mp4",
            review_id="review-30fps",
            duration=10,
            fps=30,
            source_sha256="e" * 64,
        )
        self.assertIn("30 fps · исходник SHA-256", html)
        self.assertNotIn("50 fps · исходник SHA-256", html)


if __name__ == "__main__":
    unittest.main()
