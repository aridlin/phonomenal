import unittest

from phonomenal.exporter import validate_manifest_structure


class ExporterTests(unittest.TestCase):
    def test_validate_manifest_structure_accepts_valid_manifest(self) -> None:
        manifest = {
            "schema_version": "1.0",
            "generated_at": "2026-04-23T00:00:00+00:00",
            "mercs": {
                "scout": [
                    {
                        "clip_id": "scout_deadbeef00",
                        "merc": "scout",
                        "audio_path": "data/wav/scout/scout_deadbeef00.wav",
                        "source_url": "https://example.com/scout.wav",
                        "duration_s": 1.0,
                        "sample_rate": 16000,
                        "transcript_raw": "Nope!",
                        "transcript_norm": "nope",
                        "asr_confidence": 0.75,
                        "alignment_status": "accepted",
                        "reject_reasons": [],
                        "words": [
                            {
                                "text": "nope",
                                "start_s": 0.0,
                                "end_s": 0.3,
                                "start_sample": 0,
                                "end_sample": 4800,
                                "confidence": 0.75
                            }
                        ],
                        "phonemes": [
                            {
                                "label": "N",
                                "word_index": 0,
                                "start_s": 0.0,
                                "end_s": 0.1,
                                "start_sample": 0,
                                "end_sample": 1600,
                                "confidence": 0.75
                            }
                        ]
                    }
                ]
            }
        }

        validate_manifest_structure(manifest)


if __name__ == "__main__":
    unittest.main()
