import math
import tempfile
import unittest
import wave
from pathlib import Path

from phonomenal.align import save_alignment_state
from phonomenal.config import default_layout
from phonomenal.models import ClipRecord, PhonemeAlignment, WordAlignment
from phonomenal.splicer import guess_phone_labels, load_voice_bank, synthesize_plan


class StubPronunciationResolver:
    def __init__(self, mapping):
        self.mapping = {key: tuple(value) for key, value in mapping.items()}

    def phones_for_token(self, token: str):
        return self.mapping.get(token, ())


class SplicerTests(unittest.TestCase):
    def test_guess_phone_labels_handles_simple_unknown_word(self) -> None:
        self.assertEqual(guess_phone_labels("piss"), ("P", "IH", "S"))

    def test_plan_prefers_exact_multiword_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            layout = self._build_layout(Path(tmp_dir))
            bank = load_voice_bank(
                layout,
                "scout",
                pronunciation_resolver=StubPronunciationResolver({"go": ("G", "OW")}),
            )

            plan = bank.plan("Need medic")

        self.assertEqual(len(plan.units), 1)
        self.assertEqual(plan.units[0].kind, "exact_chunk")
        self.assertEqual(plan.units[0].text, "need medic")

    def test_plan_splits_word_into_known_word_pieces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            layout = self._build_layout(Path(tmp_dir))
            bank = load_voice_bank(
                layout,
                "scout",
                pronunciation_resolver=StubPronunciationResolver({"go": ("G", "OW")}),
            )

            plan = bank.plan("minigun")

        self.assertEqual([unit.kind for unit in plan.units], ["word_piece", "word_piece"])
        self.assertEqual([unit.text for unit in plan.units], ["mini", "gun"])
        self.assertEqual([unit.word_group for unit in plan.units], [0, 0])

    def test_plan_falls_back_to_phonemes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            layout = self._build_layout(Path(tmp_dir))
            bank = load_voice_bank(
                layout,
                "scout",
                pronunciation_resolver=StubPronunciationResolver({"go": ("G", "OW")}),
            )

            plan = bank.plan("go")

        self.assertEqual([unit.kind for unit in plan.units], ["phoneme"])
        self.assertEqual([unit.phones for unit in plan.units], [("G", "OW")])

    def test_plan_falls_back_to_single_phoneme_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            layout = self._build_layout(Path(tmp_dir))
            bank = load_voice_bank(
                layout,
                "scout",
                pronunciation_resolver=StubPronunciationResolver({"ow": ("OW",)}),
            )

            plan = bank.plan("ow")

        self.assertEqual([unit.kind for unit in plan.units], ["phoneme"])
        self.assertEqual([unit.phones for unit in plan.units], [("OW",)])

    def test_plan_guesses_unknown_word_and_uses_phone_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            layout = self._build_layout(Path(tmp_dir))
            bank = load_voice_bank(layout, "scout")

            plan = bank.plan("piss")

        self.assertEqual([unit.kind for unit in plan.units], ["phoneme", "phoneme", "phoneme"])
        self.assertEqual([unit.phones[0] for unit in plan.units], ["P", "IH", "S"])

    def test_synthesize_plan_returns_wav_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            layout = self._build_layout(Path(tmp_dir))
            bank = load_voice_bank(
                layout,
                "scout",
                pronunciation_resolver=StubPronunciationResolver({"go": ("G", "OW")}),
            )

            plan = bank.plan("minigun")
            wav_bytes = synthesize_plan(plan, crossfade_ms=0)

        self.assertTrue(wav_bytes.startswith(b"RIFF"))
        with wave.open(str(self._write_temp_file(wav_bytes)), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 16000)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getnframes(), 3200)

    def test_synthesize_plan_adds_gap_between_words_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            layout = self._build_layout(Path(tmp_dir))
            bank = load_voice_bank(layout, "scout")

            plan = bank.plan("mini gun")
            wav_bytes = synthesize_plan(plan, crossfade_ms=0, word_gap_ms=20)

        with wave.open(str(self._write_temp_file(wav_bytes)), "rb") as wav_file:
            self.assertEqual(wav_file.getnframes(), 3520)

    def test_plan_prefers_pitch_continuity_over_slightly_higher_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            layout = default_layout(Path(tmp_dir))
            layout.ensure()
            master_path = layout.merc_master_path("scout")
            master_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_sine_master(master_path, [200.0, 200.0, 340.0], frames_per_segment=1600)

            records = [
                self._single_word_record(
                    clip_id="scout_need_pitch",
                    word="need",
                    phone_labels=["N", "IY1", "D"],
                    master_start_sample=0,
                    master_value_duration=1600,
                    confidence=0.9,
                ),
                self._single_word_record(
                    clip_id="scout_hello_low",
                    word="hello",
                    phone_labels=["HH", "AH0", "L", "OW1"],
                    master_start_sample=1600,
                    master_value_duration=1600,
                    confidence=0.82,
                ),
                self._single_word_record(
                    clip_id="scout_hello_high",
                    word="hello",
                    phone_labels=["HH", "AH0", "L", "OW1"],
                    master_start_sample=3200,
                    master_value_duration=1600,
                    confidence=0.9,
                ),
            ]
            save_alignment_state(layout, "scout", records)
            bank = load_voice_bank(layout, "scout")

            plan = bank.plan("need hello")

        self.assertEqual(plan.units[0].clip_id, "scout_need_pitch")
        self.assertEqual(plan.units[1].clip_id, "scout_hello_low")

    def _build_layout(self, root: Path):
        layout = default_layout(root)
        layout.ensure()
        master_path = layout.merc_master_path("scout")
        master_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_master(master_path, [1000, 1500, 2000, 3000, 4000, 4500, 5000], frames_per_segment=1600)

        records = [
            ClipRecord(
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
                    WordAlignment(
                        text="need",
                        start_s=0.0,
                        end_s=0.1,
                        start_sample=0,
                        end_sample=1600,
                        confidence=0.9,
                        master_start_s=0.0,
                        master_end_s=0.1,
                        master_start_sample=0,
                        master_end_sample=1600,
                    ),
                    WordAlignment(
                        text="medic",
                        start_s=0.1,
                        end_s=0.2,
                        start_sample=1600,
                        end_sample=3200,
                        confidence=0.9,
                        master_start_s=0.1,
                        master_end_s=0.2,
                        master_start_sample=1600,
                        master_end_sample=3200,
                    ),
                ],
                phonemes=[
                    PhonemeAlignment("N", 0, 0.0, 0.03, 0, 480, 0.9, 0.0, 0.03, 0, 480),
                    PhonemeAlignment("IY1", 0, 0.03, 0.08, 480, 1280, 0.9, 0.03, 0.08, 480, 1280),
                    PhonemeAlignment("D", 0, 0.08, 0.1, 1280, 1600, 0.9, 0.08, 0.1, 1280, 1600),
                    PhonemeAlignment("M", 1, 0.1, 0.13, 1600, 2080, 0.9, 0.1, 0.13, 1600, 2080),
                    PhonemeAlignment("EH1", 1, 0.13, 0.16, 2080, 2560, 0.9, 0.13, 0.16, 2080, 2560),
                    PhonemeAlignment("D", 1, 0.16, 0.18, 2560, 2880, 0.9, 0.16, 0.18, 2560, 2880),
                    PhonemeAlignment("IH0", 1, 0.18, 0.19, 2880, 3040, 0.9, 0.18, 0.19, 2880, 3040),
                    PhonemeAlignment("K", 1, 0.19, 0.2, 3040, 3200, 0.9, 0.19, 0.2, 3040, 3200),
                ],
            ),
            self._single_word_record(
                clip_id="scout_mini",
                word="mini",
                phone_labels=["M", "IH1", "N", "IY0"],
                master_start_sample=3200,
                master_value_duration=1600,
            ),
            self._single_word_record(
                clip_id="scout_gun",
                word="gun",
                phone_labels=["G", "AH1", "N"],
                master_start_sample=4800,
                master_value_duration=1600,
            ),
            self._single_word_record(
                clip_id="scout_oh",
                word="oh",
                phone_labels=["OW1"],
                master_start_sample=6400,
                master_value_duration=1600,
            ),
            self._single_word_record(
                clip_id="scout_goat",
                word="goat",
                phone_labels=["G", "OW1", "T"],
                master_start_sample=8000,
                master_value_duration=1600,
            ),
            self._single_word_record(
                clip_id="scout_piece",
                word="piece",
                phone_labels=["P", "IY1", "S"],
                master_start_sample=9600,
                master_value_duration=1600,
            ),
        ]

        save_alignment_state(layout, "scout", records)
        return layout

    @staticmethod
    def _single_word_record(
        clip_id: str,
        word: str,
        phone_labels,
        master_start_sample: int,
        master_value_duration: int,
        confidence: float = 0.85,
    ) -> ClipRecord:
        phones = []
        phone_duration = master_value_duration // len(phone_labels)
        cursor = 0
        for index, label in enumerate(phone_labels):
            start = cursor
            end = master_value_duration if index == len(phone_labels) - 1 else cursor + phone_duration
            phones.append(
                PhonemeAlignment(
                    label=label,
                    word_index=0,
                    start_s=start / 16000.0,
                    end_s=end / 16000.0,
                    start_sample=start,
                    end_sample=end,
                    confidence=confidence,
                    master_start_s=(master_start_sample + start) / 16000.0,
                    master_end_s=(master_start_sample + end) / 16000.0,
                    master_start_sample=master_start_sample + start,
                    master_end_sample=master_start_sample + end,
                )
            )
            cursor = end

        return ClipRecord(
            clip_id=clip_id,
            merc="scout",
            source_url=f"source/scout/{word}.mp3",
            raw_path=f"source/scout/{word}.mp3",
            source_path=f"source/scout/{word}.mp3",
            source_category="word",
            audio_path=f"data/wav/scout/{clip_id}.wav",
            master_audio_path="data/master/scout.wav",
            duration_s=master_value_duration / 16000.0,
            sample_rate=16000,
            master_start_s=master_start_sample / 16000.0,
            master_end_s=(master_start_sample + master_value_duration) / 16000.0,
            master_start_sample=master_start_sample,
            master_end_sample=master_start_sample + master_value_duration,
            transcript_raw=word,
            transcript_norm=word,
            asr_confidence=confidence,
            alignment_status="accepted",
            words=[
                WordAlignment(
                    text=word,
                    start_s=0.0,
                    end_s=master_value_duration / 16000.0,
                    start_sample=0,
                    end_sample=master_value_duration,
                    confidence=confidence,
                    master_start_s=master_start_sample / 16000.0,
                    master_end_s=(master_start_sample + master_value_duration) / 16000.0,
                    master_start_sample=master_start_sample,
                    master_end_sample=master_start_sample + master_value_duration,
                )
            ],
            phonemes=phones,
        )

    @staticmethod
    def _write_sine_master(path: Path, frequencies, frames_per_segment: int) -> None:
        sample_rate = 16000
        amplitude = 12000
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            for frequency in frequencies:
                frames = bytearray()
                for index in range(frames_per_segment):
                    sample = int(round(amplitude * math.sin(2.0 * math.pi * frequency * (index / sample_rate))))
                    frames.extend(sample.to_bytes(2, byteorder="little", signed=True))
                wav_file.writeframes(bytes(frames))

    @staticmethod
    def _write_master(path: Path, values, frames_per_segment: int) -> None:
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            for value in values:
                wav_file.writeframes(int(value).to_bytes(2, byteorder="little", signed=True) * frames_per_segment)

    @staticmethod
    def _write_temp_file(payload: bytes) -> Path:
        path = Path(tempfile.gettempdir()) / "phonomenal_splicer_test.wav"
        path.write_bytes(payload)
        return path


if __name__ == "__main__":
    unittest.main()
