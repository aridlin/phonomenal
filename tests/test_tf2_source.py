import tempfile
import unittest
from pathlib import Path

from phonomenal.config import default_layout
from phonomenal.tf2_source import parse_response_page, scan_local_source_merc


HTML_SAMPLE = """
<ul>
  <li>
    <a href="/wiki/File:Scout_positive01.wav" title="File:Scout_positive01.wav">listen</a>
    <a href="/wiki/File:Scout_robot_positive01.wav" title="File:Scout_robot_positive01.wav">robot</a>
    <a href="/wiki/File:Scout_giant_positive01.wav" title="File:Scout_giant_positive01.wav">giant</a>
    "Yeah, that's right!"
  </li>
  <li>
    <a href="/wiki/File:Scout_grunt01.wav" title="File:Scout_grunt01.wav">listen</a>
    (Grunt 1)
  </li>
</ul>
"""


class TF2SourceTests(unittest.TestCase):
    def test_parse_response_page_prefers_human_clip_and_skips_non_speech(self) -> None:
        records = parse_response_page(HTML_SAMPLE, merc="scout", source_page="https://example.com")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["file_title"], "File:Scout_positive01.wav")
        self.assertIn("Yeah", records[0]["source_text"])

    def test_scan_local_source_filters_giant_robot_and_keeps_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            kept = root / "source" / "heavy" / "yes" / "heavy_yes01.mp3"
            skipped = root / "source" / "heavy" / "mvm" / "giant robot" / "heavy_mvm_giant_robot01.mp3"
            kept.parent.mkdir(parents=True, exist_ok=True)
            skipped.parent.mkdir(parents=True, exist_ok=True)
            kept.write_bytes(b"mp3")
            skipped.write_bytes(b"mp3")

            records = scan_local_source_merc("heavy", layout=default_layout(root))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_category, "yes")
        self.assertEqual(records[0].source_path, "source/heavy/yes/heavy_yes01.mp3")


if __name__ == "__main__":
    unittest.main()
