import tempfile
import unittest
from pathlib import Path

from phonomenal.align import save_alignment_state
from phonomenal.config import default_layout
from phonomenal.models import ClipRecord, PhonemeAlignment, WordAlignment
from phonomenal.packager import pack_voice_bank


class PackagerTests(unittest.TestCase):
    def test_pack_voice_bank_writes_native_bank_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            layout = default_layout(root)
            layout.ensure()

            master_path = layout.merc_master_path("scout")
            master_path.parent.mkdir(parents=True, exist_ok=True)
            master_path.write_bytes(b"RIFFfake")

            record = ClipRecord(
                clip_id="scout_need_medic",
                merc="scout",
                source_url="source/scout/need_medic.mp3",
                raw_path="source/scout/need_medic.mp3",
                source_path="source/scout/need_medic.mp3",
                source_category="callout",
                audio_path="data/wav/scout/scout_need_medic.wav",
                master_audio_path="data/master/scout.wav",
                duration_s=0.2,
                sample_rate=16000,
                master_start_s=0.0,
                master_end_s=0.2,
                master_start_sample=0,
                master_end_sample=3200,
                transcript_raw="Need Medic",
                transcript_norm="need medic",
                asr_confidence=0.9,
                alignment_status="accepted",
                words=[
                    WordAlignment("need", 0.0, 0.1, 0, 1600, 0.9, 0.0, 0.1, 0, 1600),
                    WordAlignment("medic", 0.1, 0.2, 1600, 3200, 0.9, 0.1, 0.2, 1600, 3200),
                ],
                phonemes=[
                    PhonemeAlignment("N", 0, 0.0, 0.03, 0, 480, 0.9, 0.0, 0.03, 0, 480),
                    PhonemeAlignment("M", 1, 0.1, 0.13, 1600, 2080, 0.9, 0.1, 0.13, 1600, 2080),
                ],
            )
            save_alignment_state(layout, "scout", [record])

            package_path = pack_voice_bank(layout, "scout", bundle_master=True)
            payload = package_path.read_text(encoding="utf-8")

        self.assertIn("PHONOMENAL_BANK\t2", payload)
        self.assertIn("merc\tscout", payload)
        self.assertIn("master_audio\tscout.wav", payload)
        self.assertIn("lexicon\tmedic\tM", payload)
        self.assertIn("record\tscout_need_medic", payload)
        self.assertIn("word\tneed\t0\t1600\t0.900000", payload)
        self.assertIn("phoneme\tM\t1\t1600\t2080\t0.900000", payload)


if __name__ == "__main__":
    unittest.main()
