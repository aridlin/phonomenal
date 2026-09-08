import tempfile
import unittest
import wave
from pathlib import Path

from phonomenal.audio import build_merc_master
from phonomenal.config import default_layout
from phonomenal.models import ClipRecord, PhonemeAlignment, WordAlignment


class MasterAudioTests(unittest.TestCase):
    def test_build_merc_master_projects_clip_and_interval_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            layout = default_layout(root)
            layout.ensure()

            wav_dir = layout.merc_wav_dir("scout")
            wav_dir.mkdir(parents=True, exist_ok=True)

            clip_one = wav_dir / "scout_a.wav"
            clip_two = wav_dir / "scout_b.wav"
            self._write_wav(clip_one, frames=1600)
            self._write_wav(clip_two, frames=3200)

            records = [
                ClipRecord(
                    clip_id="scout_a",
                    merc="scout",
                    source_url="source/scout/a.mp3",
                    raw_path="source/scout/a.mp3",
                    source_path="source/scout/a.mp3",
                    audio_path="data/wav/scout/scout_a.wav",
                    sample_rate=16000,
                    words=[
                        WordAlignment("mini", 0.0, 0.05, 0, 800, 0.9),
                    ],
                    phonemes=[
                        PhonemeAlignment("M", 0, 0.0, 0.02, 0, 320, 0.9),
                    ],
                ),
                ClipRecord(
                    clip_id="scout_b",
                    merc="scout",
                    source_url="source/scout/b.mp3",
                    raw_path="source/scout/b.mp3",
                    source_path="source/scout/b.mp3",
                    audio_path="data/wav/scout/scout_b.wav",
                    sample_rate=16000,
                ),
            ]

            master_path = build_merc_master("scout", records=records, layout=layout, gap_ms=250, force=False)

            self.assertTrue(master_path.exists())
            self.assertEqual(records[0].master_audio_path, "data/master/scout.wav")
            self.assertEqual(records[0].master_start_sample, 0)
            self.assertEqual(records[0].master_end_sample, 1600)
            self.assertEqual(records[1].master_start_sample, 1600 + 4000)
            self.assertEqual(records[1].master_end_sample, 1600 + 4000 + 3200)
            self.assertEqual(records[0].words[0].master_end_sample, 800)
            self.assertEqual(records[0].phonemes[0].master_end_sample, 320)

    @staticmethod
    def _write_wav(path: Path, frames: int) -> None:
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * frames)


if __name__ == "__main__":
    unittest.main()
