import tempfile
import unittest
import wave
from pathlib import Path

from phonomenal.audio import probe_audio, seconds_to_sample


class AudioTests(unittest.TestCase):
    def test_seconds_to_sample_rounds_correctly(self) -> None:
        self.assertEqual(seconds_to_sample(0.5, 16000), 8000)
        self.assertEqual(seconds_to_sample(0.00003125, 16000), 0)
        self.assertEqual(seconds_to_sample(0.0000625, 16000), 1)

    def test_probe_audio_reads_wav_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "sample.wav"
            with wave.open(str(wav_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(b"\x00\x00" * 1600)

            metadata = probe_audio(wav_path)
            self.assertEqual(metadata["sample_rate"], 16000)
            self.assertEqual(metadata["channels"], 1)
            self.assertEqual(metadata["frame_count"], 1600)
            self.assertAlmostEqual(metadata["duration_s"], 0.1, places=5)


if __name__ == "__main__":
    unittest.main()

