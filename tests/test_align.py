import json
import tempfile
import unittest
from pathlib import Path

from phonomenal.align import (
    _is_alignment_complete,
    build_asr_prompt,
    correct_transcript_with_hints,
    is_obviously_non_speech,
    low_quality_transcript_reason,
    merge_catalog_with_alignment_state,
    normalize_transcript,
    parse_mfa_alignment,
    source_category_hint_tokens,
)
from phonomenal.models import ClipRecord, PhonemeAlignment, WordAlignment


class AlignTests(unittest.TestCase):
    def test_normalize_transcript_preserves_apostrophe_slang(self) -> None:
        normalized = normalize_transcript("Y'freakin' unbelievable, chuckleheads!")
        self.assertEqual(normalized, "y'freakin' unbelievable chuckleheads")

    def test_interjection_is_not_marked_non_speech(self) -> None:
        self.assertFalse(is_obviously_non_speech("nope"))
        self.assertTrue(is_obviously_non_speech(""))

    def test_source_category_hint_tokens_use_leaf_segment(self) -> None:
        self.assertEqual(source_category_hint_tokens("domination/medic"), ("medic",))
        self.assertEqual(source_category_hint_tokens("thanks for the heal"), ("thanks", "heal"))

    def test_build_asr_prompt_includes_hint_and_tf2_terms(self) -> None:
        prompt = build_asr_prompt("sentry ahead")
        self.assertIsNotNone(prompt)
        assert prompt is not None
        self.assertIn("sentry", prompt)
        self.assertIn("teleporter", prompt)

    def test_correct_transcript_with_hints_repairs_tf2_term(self) -> None:
        corrected = correct_transcript_with_hints("century ahead", "sentry ahead")
        self.assertEqual(corrected, "sentry ahead")

    def test_low_quality_transcript_reason_flags_long_single_word_without_hint_overlap(self) -> None:
        record = ClipRecord(
            clip_id="scout_bad",
            merc="scout",
            source_url="source/scout/bad.mp3",
            raw_path="source/scout/bad.mp3",
            source_category="being shot invincible",
            transcript_norm="ball",
            duration_s=1.25,
        )
        self.assertEqual(low_quality_transcript_reason(record), "long_single_word_low_context")

    def test_parse_mfa_alignment_extracts_words_and_phones(self) -> None:
        payload = {
            "xmin": 0.0,
            "xmax": 0.64,
            "tiers": [
                {
                    "class": "IntervalTier",
                    "name": "words",
                    "xmin": 0.0,
                    "xmax": 0.64,
                    "entries": [
                        [0.0, 0.2, "hello"],
                        [0.2, 0.64, "world"]
                    ]
                },
                {
                    "class": "IntervalTier",
                    "name": "phones",
                    "xmin": 0.0,
                    "xmax": 0.64,
                    "entries": [
                        [0.0, 0.07, "HH"],
                        [0.07, 0.2, "AH0"],
                        [0.2, 0.35, "W"],
                        [0.35, 0.64, "ER1"]
                    ]
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            alignment_path = Path(tmp_dir) / "clip.json"
            alignment_path.write_text(json.dumps(payload), encoding="utf-8")
            words, phonemes = parse_mfa_alignment(alignment_path, confidence=0.75, sample_rate=16000)

        self.assertEqual([word.text for word in words], ["hello", "world"])
        self.assertEqual([phoneme.word_index for phoneme in phonemes], [0, 0, 1, 1])
        self.assertEqual(phonemes[0].start_sample, 0)
        self.assertEqual(phonemes[-1].end_sample, 10240)

    def test_merge_catalog_with_alignment_state_preserves_finished_clip_state(self) -> None:
        catalog_record = ClipRecord(
            clip_id="scout_deadbeef00",
            merc="scout",
            source_url="source/scout/test.mp3",
            raw_path="source/scout/test.mp3",
            source_path="source/scout/test.mp3",
            source_category="test",
        )
        aligned_record = ClipRecord(
            clip_id="scout_deadbeef00",
            merc="scout",
            source_url="source/scout/test.mp3",
            raw_path="source/scout/test.mp3",
            source_path="source/scout/test.mp3",
            source_category="old-category",
            audio_path="data/wav/scout/scout_deadbeef00.wav",
            transcript_raw="Doc!",
            transcript_norm="doc",
            alignment_status="accepted",
            words=[
                WordAlignment(
                    text="doc",
                    start_s=0.0,
                    end_s=0.2,
                    start_sample=0,
                    end_sample=3200,
                    confidence=0.8,
                )
            ],
            phonemes=[
                PhonemeAlignment(
                    label="D",
                    word_index=0,
                    start_s=0.0,
                    end_s=0.08,
                    start_sample=0,
                    end_sample=1280,
                    confidence=0.8,
                )
            ],
        )

        merged = merge_catalog_with_alignment_state([catalog_record], [aligned_record])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_category, "test")
        self.assertEqual(merged[0].alignment_status, "accepted")
        self.assertEqual(merged[0].transcript_norm, "doc")
        self.assertEqual(merged[0].audio_path, "data/wav/scout/scout_deadbeef00.wav")
        self.assertEqual(merged[0].words[0].text, "doc")

    def test_alignment_complete_only_for_finished_accepts_or_rejects(self) -> None:
        accepted = ClipRecord(
            clip_id="heavy_accepted",
            merc="heavy",
            source_url="source/heavy/accepted.mp3",
            raw_path="source/heavy/accepted.mp3",
            transcript_norm="yes",
            alignment_status="accepted",
            words=[
                WordAlignment(
                    text="yes",
                    start_s=0.0,
                    end_s=0.2,
                    start_sample=0,
                    end_sample=3200,
                )
            ],
            phonemes=[
                PhonemeAlignment(
                    label="Y",
                    word_index=0,
                    start_s=0.0,
                    end_s=0.1,
                    start_sample=0,
                    end_sample=1600,
                )
            ],
        )
        rejected = ClipRecord(
            clip_id="heavy_rejected",
            merc="heavy",
            source_url="source/heavy/rejected.mp3",
            raw_path="source/heavy/rejected.mp3",
            alignment_status="rejected",
            reject_reasons=["empty_lexical_transcript"],
        )
        queued = ClipRecord(
            clip_id="heavy_queued",
            merc="heavy",
            source_url="source/heavy/queued.mp3",
            raw_path="source/heavy/queued.mp3",
            transcript_norm="medic",
            alignment_status="queued",
        )

        self.assertTrue(_is_alignment_complete(accepted))
        self.assertTrue(_is_alignment_complete(rejected))
        self.assertFalse(_is_alignment_complete(queued))


if __name__ == "__main__":
    unittest.main()
