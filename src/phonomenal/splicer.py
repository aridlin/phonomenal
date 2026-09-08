from __future__ import annotations

import io
import json
import math
import re
import sys
import wave
from array import array
from dataclasses import dataclass
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from phonomenal.align import (
    _load_cmudict,
    _load_g2p,
    low_quality_transcript_reason,
    _pronunciation_for_token,
    load_alignment_state,
    normalize_transcript,
)
from phonomenal.config import DEFAULT_SAMPLE_RATE, ProjectLayout, all_mercs
from phonomenal.models import ClipRecord

PHONE_STRIP_RE = re.compile(r"\d+$")


def normalize_phone_label(label: str) -> str:
    return PHONE_STRIP_RE.sub("", label.strip().upper())


def guess_phone_labels(token: str) -> Tuple[str, ...]:
    letters = "".join(char for char in token.lower() if char.isalpha() or char == "'")
    if not letters:
        return ()

    phones: List[str] = []
    index = 0
    while index < len(letters):
        if letters[index] == "'":
            index += 1
            continue

        if letters.startswith("tion", index):
            phones.extend(("SH", "AH", "N"))
            index += 4
            continue
        if letters.startswith("sion", index):
            phones.extend(("ZH", "AH", "N"))
            index += 4
            continue
        if letters.startswith("tch", index):
            phones.append("CH")
            index += 3
            continue
        if letters.startswith("dge", index):
            phones.append("JH")
            index += 3
            continue
        if letters.startswith("igh", index):
            phones.append("AY")
            index += 3
            continue
        if letters.startswith("eigh", index):
            phones.append("EY")
            index += 4
            continue

        for pattern, labels in (
            ("sh", ("SH",)),
            ("ch", ("CH",)),
            ("th", ("TH",)),
            ("ph", ("F",)),
            ("ng", ("NG",)),
            ("qu", ("K", "W")),
            ("ck", ("K",)),
            ("wh", ("W",)),
            ("ee", ("IY",)),
            ("ea", ("IY",)),
            ("ei", ("IY",)),
            ("oo", ("UW",)),
            ("oa", ("OW",)),
            ("oe", ("OW",)),
            ("ow", ("OW",)),
            ("ou", ("AW",)),
            ("oi", ("OY",)),
            ("oy", ("OY",)),
            ("ai", ("EY",)),
            ("ay", ("EY",)),
            ("au", ("AO",)),
            ("aw", ("AO",)),
            ("er", ("ER",)),
            ("ir", ("ER",)),
            ("ur", ("ER",)),
            ("ar", ("AA", "R")),
            ("or", ("AO", "R")),
        ):
            if letters.startswith(pattern, index):
                phones.extend(labels)
                index += len(pattern)
                break
        else:
            if index == 0 and letters.startswith("wr", index):
                phones.append("R")
                index += 2
                continue
            if index == 0 and letters.startswith("kn", index):
                phones.append("N")
                index += 2
                continue
            if index == 0 and letters.startswith("ps", index):
                phones.append("S")
                index += 2
                continue

            ch = letters[index]
            if (
                index + 1 < len(letters)
                and letters[index + 1] == ch
                and ch not in "aeiouy"
                and ch != "r"
            ):
                doubled = {
                    "s": "S",
                    "l": "L",
                    "m": "M",
                    "n": "N",
                    "p": "P",
                    "t": "T",
                    "f": "F",
                    "g": "G",
                }.get(ch)
                if doubled:
                    phones.append(doubled)
                    index += 2
                    continue

            if ch == "a":
                phones.append("EY" if len(letters) == 1 else "AE")
            elif ch == "e":
                if not (index == len(letters) - 1 and len(letters) > 1):
                    phones.append("EH")
            elif ch == "i":
                phones.append("IY" if index == len(letters) - 1 else "IH")
            elif ch == "o":
                if index == len(letters) - 1 or (index + 2 == len(letters) and letters[index + 1] not in "aeiouy"):
                    phones.append("OW")
                else:
                    phones.append("AA")
            elif ch == "u":
                phones.append("UW" if index == len(letters) - 1 else "AH")
            elif ch == "y":
                phones.append("IY" if index == len(letters) - 1 else "Y")
            else:
                phones.extend(
                    {
                        "b": ("B",),
                        "c": ("S",) if index + 1 < len(letters) and letters[index + 1] in "eiy" else ("K",),
                        "d": ("D",),
                        "f": ("F",),
                        "g": ("JH",) if index + 1 < len(letters) and letters[index + 1] in "eiy" else ("G",),
                        "h": ("HH",),
                        "j": ("JH",),
                        "k": ("K",),
                        "l": ("L",),
                        "m": ("M",),
                        "n": ("N",),
                        "p": ("P",),
                        "q": ("K",),
                        "r": ("R",),
                        "s": ("S",),
                        "t": ("T",),
                        "v": ("V",),
                        "w": ("W",),
                        "x": ("K", "S"),
                        "z": ("Z",),
                    }.get(ch, ())
                )
            index += 1

    return tuple(normalize_phone_label(phone) for phone in phones if normalize_phone_label(phone))


def phone_label_alternatives(label: str) -> Tuple[str, ...]:
    normalized = normalize_phone_label(label)
    if normalized == "IH":
        return ("IH", "IY", "EH")
    if normalized == "IY":
        return ("IY", "IH", "EH")
    if normalized == "EH":
        return ("EH", "IH", "IY", "AE")
    if normalized == "AE":
        return ("AE", "EH", "AH")
    if normalized == "AH":
        return ("AH", "UH", "AA", "AE")
    if normalized == "AA":
        return ("AA", "AH", "AO")
    if normalized == "AO":
        return ("AO", "AA", "OW")
    if normalized == "UH":
        return ("UH", "AH", "UW")
    if normalized == "UW":
        return ("UW", "UH", "OW")
    if normalized == "OW":
        return ("OW", "AO", "UW")
    if normalized == "EY":
        return ("EY", "EH", "IY")
    if normalized == "AY":
        return ("AY", "EY", "IH")
    return (normalized,) if normalized else ()


def _confidence_penalty(confidence: Optional[float]) -> float:
    if confidence is None:
        return 0.2
    return max(0.0, 1.0 - confidence) * 0.35


def _mean_confidence(values: Sequence[Optional[float]]) -> Optional[float]:
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return round(sum(filtered) / len(filtered), 4)


def _clamp_i16(value: float) -> int:
    return max(-32768, min(32767, int(round(value))))


@dataclass(frozen=True)
class BankWord:
    text: str
    start_sample: int
    end_sample: int
    master_start_sample: int
    master_end_sample: int
    confidence: Optional[float]


@dataclass(frozen=True)
class BankPhoneme:
    label: str
    normalized_label: str
    word_index: int
    start_sample: int
    end_sample: int
    master_start_sample: int
    master_end_sample: int
    confidence: Optional[float]


@dataclass(frozen=True)
class BankRecord:
    clip_id: str
    merc: str
    sample_rate: int
    master_audio_path: str
    words: Tuple[BankWord, ...]
    phonemes: Tuple[BankPhoneme, ...]


@dataclass(frozen=True)
class ChunkOccurrence:
    text: str
    tokens: Tuple[str, ...]
    clip_id: str
    start_sample: int
    end_sample: int
    confidence: Optional[float]
    source_kind: str

    @property
    def duration_samples(self) -> int:
        return max(0, self.end_sample - self.start_sample)


@dataclass(frozen=True)
class PhoneOccurrence:
    labels: Tuple[str, ...]
    clip_id: str
    start_sample: int
    end_sample: int
    confidence: Optional[float]
    source_word: str

    @property
    def duration_samples(self) -> int:
        return max(0, self.end_sample - self.start_sample)


@dataclass(frozen=True)
class PlannedUnit:
    kind: str
    target_text: str
    text: str
    phones: Tuple[str, ...]
    clip_id: str
    start_sample: int
    end_sample: int
    word_group: int
    confidence: Optional[float]

    @property
    def duration_samples(self) -> int:
        return max(0, self.end_sample - self.start_sample)

    def to_dict(self, sample_rate: int) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "target_text": self.target_text,
            "text": self.text,
            "phones": list(self.phones),
            "clip_id": self.clip_id,
            "start_sample": self.start_sample,
            "end_sample": self.end_sample,
            "word_group": self.word_group,
            "start_s": round(self.start_sample / float(sample_rate), 6),
            "end_s": round(self.end_sample / float(sample_rate), 6),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class AcousticProfile:
    pitch_hz: Optional[float]
    rms: float


@dataclass(frozen=True)
class PlanResult:
    merc: str
    input_text: str
    normalized_text: str
    units: Tuple[PlannedUnit, ...]
    sample_rate: int
    master_audio_path: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "merc": self.merc,
            "input_text": self.input_text,
            "normalized_text": self.normalized_text,
            "sample_rate": self.sample_rate,
            "master_audio_path": self.master_audio_path,
            "units": [unit.to_dict(self.sample_rate) for unit in self.units],
        }


@dataclass
class BankLoadResult:
    merc: str
    master_audio_path: Path
    sample_rate: int
    records: List[BankRecord]


class PronunciationResolver:
    def __init__(self) -> None:
        self._cmu_dict = None
        self._g2p = None

    @lru_cache(maxsize=4096)
    def phones_for_token(self, token: str) -> Tuple[str, ...]:
        if not token:
            return ()
        normalized = normalize_transcript(token)
        if not normalized or " " in normalized:
            return ()

        if self._cmu_dict is None:
            try:
                self._cmu_dict = _load_cmudict()
            except Exception:
                self._cmu_dict = None

        try:
            phones = _pronunciation_for_token(normalized, self._cmu_dict, self._g2p)
        except Exception:
            if self._g2p is None:
                try:
                    self._g2p = _load_g2p()
                except Exception:
                    return guess_phone_labels(normalized)
            try:
                phones = _pronunciation_for_token(normalized, self._cmu_dict, self._g2p)
            except Exception:
                return guess_phone_labels(normalized)

        normalized_phones = tuple(normalize_phone_label(phone) for phone in phones if normalize_phone_label(phone))
        return normalized_phones or guess_phone_labels(normalized)


class VoiceBank:
    def __init__(
        self,
        merc: str,
        master_audio_path: Path,
        sample_rate: int,
        records: Sequence[BankRecord],
        pronunciation_resolver: PronunciationResolver,
        max_chunk_words: int = 4,
        max_phone_ngram: int = 6,
    ) -> None:
        self.merc = merc
        self.master_audio_path = master_audio_path
        self.sample_rate = sample_rate or DEFAULT_SAMPLE_RATE
        self.records = list(records)
        self.max_chunk_words = max_chunk_words
        self.max_phone_ngram = max_phone_ngram
        self._pronunciation_resolver = pronunciation_resolver
        self.chunk_index: Dict[Tuple[str, ...], List[ChunkOccurrence]] = {}
        self.word_index: Dict[str, List[ChunkOccurrence]] = {}
        self.phone_index: Dict[Tuple[str, ...], List[PhoneOccurrence]] = {}
        self._profile_cache: Dict[Tuple[int, int], AcousticProfile] = {}
        self._build_indexes()

    def _build_indexes(self) -> None:
        for record in self.records:
            for start in range(len(record.words)):
                for length in range(1, min(self.max_chunk_words, len(record.words) - start) + 1):
                    chunk_words = record.words[start : start + length]
                    tokens = tuple(word.text for word in chunk_words)
                    occurrence = ChunkOccurrence(
                        text=" ".join(tokens),
                        tokens=tokens,
                        clip_id=record.clip_id,
                        start_sample=chunk_words[0].master_start_sample,
                        end_sample=chunk_words[-1].master_end_sample,
                        confidence=_mean_confidence([word.confidence for word in chunk_words]),
                        source_kind="chunk" if length > 1 else "word",
                    )
                    self.chunk_index.setdefault(tokens, []).append(occurrence)
                    if length == 1:
                        self.word_index.setdefault(tokens[0], []).append(occurrence)

            phones_by_word: Dict[int, List[BankPhoneme]] = {}
            for phoneme in record.phonemes:
                if phoneme.word_index < 0:
                    continue
                phones_by_word.setdefault(phoneme.word_index, []).append(phoneme)

            for word_index, phonemes in phones_by_word.items():
                if word_index >= len(record.words):
                    continue
                phonemes = sorted(phonemes, key=lambda item: item.master_start_sample)
                labels = tuple(phoneme.normalized_label for phoneme in phonemes if phoneme.normalized_label)
                if not labels:
                    continue
                for start in range(len(labels)):
                    for length in range(1, min(self.max_phone_ngram, len(labels) - start) + 1):
                        source_slice = phonemes[start : start + length]
                        occurrence = PhoneOccurrence(
                            labels=labels[start : start + length],
                            clip_id=record.clip_id,
                            start_sample=source_slice[0].master_start_sample,
                            end_sample=source_slice[-1].master_end_sample,
                            confidence=_mean_confidence([item.confidence for item in source_slice]),
                            source_word=record.words[word_index].text,
                        )
                        self.phone_index.setdefault(occurrence.labels, []).append(occurrence)

    def _profile_for_range(self, start_sample: int, end_sample: int) -> AcousticProfile:
        key = (start_sample, end_sample)
        if key not in self._profile_cache:
            sample_rate, master_samples = _load_master_samples(str(self.master_audio_path))
            self._profile_cache[key] = _estimate_acoustic_profile(
                master_samples,
                sample_rate,
                start_sample,
                end_sample,
            )
        return self._profile_cache[key]

    def _occurrence_score(
        self,
        occurrence: Union[ChunkOccurrence, PhoneOccurrence],
        previous_unit: Optional[PlannedUnit],
        word_group: int,
    ) -> float:
        score = float(occurrence.confidence or 0.0) * 4.0
        score += min(occurrence.duration_samples / float(self.sample_rate), 0.35) * 0.15
        if previous_unit is None:
            return score

        same_word = previous_unit.word_group >= 0 and previous_unit.word_group == word_group
        if occurrence.clip_id == previous_unit.clip_id:
            score += 0.45 if same_word else 0.2
            gap_seconds = abs(occurrence.start_sample - previous_unit.end_sample) / float(self.sample_rate)
            score += max(0.0, (0.35 if same_word else 0.18) - gap_seconds * (0.9 if same_word else 0.45))

        previous_profile = self._profile_for_range(previous_unit.start_sample, previous_unit.end_sample)
        current_profile = self._profile_for_range(occurrence.start_sample, occurrence.end_sample)
        if (
            previous_profile.pitch_hz is not None
            and current_profile.pitch_hz is not None
            and previous_profile.pitch_hz > 0.0
            and current_profile.pitch_hz > 0.0
        ):
            semitone_delta = abs(12.0 * math.log(current_profile.pitch_hz / previous_profile.pitch_hz, 2.0))
            score -= semitone_delta * (0.09 if same_word else 0.06)

        if previous_profile.rms > 1e-4 and current_profile.rms > 1e-4:
            rms_delta_db = abs(20.0 * math.log10(current_profile.rms / previous_profile.rms))
            score -= rms_delta_db * (0.025 if same_word else 0.015)

        return score

    def _pick_best_chunk(
        self,
        occurrences: Sequence[ChunkOccurrence],
        previous_unit: Optional[PlannedUnit],
        word_group: int,
    ) -> ChunkOccurrence:
        return max(
            occurrences,
            key=lambda occurrence: (
                self._occurrence_score(occurrence, previous_unit, word_group),
                float(occurrence.confidence or 0.0),
                occurrence.duration_samples,
            ),
        )

    def _pick_best_phone(
        self,
        occurrences: Sequence[PhoneOccurrence],
        previous_unit: Optional[PlannedUnit],
        word_group: int,
    ) -> PhoneOccurrence:
        return max(
            occurrences,
            key=lambda occurrence: (
                self._occurrence_score(occurrence, previous_unit, word_group),
                float(occurrence.confidence or 0.0),
                occurrence.duration_samples,
            ),
        )

    def _plan_word_pieces(
        self,
        token: str,
        word_group: int,
        previous_unit: Optional[PlannedUnit],
    ) -> Optional[Tuple[PlannedUnit, ...]]:
        units: List[PlannedUnit] = []
        current_previous = previous_unit
        piece_index = 0
        while piece_index < len(token):
            matched = False
            for end in range(len(token), piece_index, -1):
                piece = token[piece_index:end]
                occurrences = self.word_index.get(piece)
                if not occurrences:
                    continue
                occurrence = self._pick_best_chunk(occurrences, current_previous, word_group)
                planned = PlannedUnit(
                    kind="word_piece",
                    target_text=token,
                    text=piece,
                    phones=(),
                    clip_id=occurrence.clip_id,
                    start_sample=occurrence.start_sample,
                    end_sample=occurrence.end_sample,
                    word_group=word_group,
                    confidence=occurrence.confidence,
                )
                units.append(planned)
                current_previous = planned
                piece_index = end
                matched = True
                break
            if not matched:
                return None

        if len(units) <= 1:
            return None
        return tuple(units)

    def _plan_phone_fallback(
        self,
        token: str,
        word_group: int,
        previous_unit: Optional[PlannedUnit],
    ) -> Optional[Tuple[PlannedUnit, ...]]:
        target_phones = self._pronunciation_resolver.phones_for_token(token)
        if not target_phones:
            return None

        units: List[PlannedUnit] = []
        current_previous = previous_unit
        index = 0
        while index < len(target_phones):
            matched = False
            max_length = min(self.max_phone_ngram, len(target_phones) - index)
            for length in range(max_length, 0, -1):
                key = target_phones[index : index + length]
                occurrences = self.phone_index.get(key)
                if not occurrences and length == 1:
                    for alternative in phone_label_alternatives(target_phones[index]):
                        occurrences = self.phone_index.get((alternative,))
                        if occurrences:
                            break
                if not occurrences:
                    continue
                occurrence = self._pick_best_phone(occurrences, current_previous, word_group)
                planned = PlannedUnit(
                    kind="phoneme",
                    target_text=token,
                    text=occurrence.source_word,
                    phones=occurrence.labels,
                    clip_id=occurrence.clip_id,
                    start_sample=occurrence.start_sample,
                    end_sample=occurrence.end_sample,
                    word_group=word_group,
                    confidence=occurrence.confidence,
                )
                units.append(planned)
                current_previous = planned
                index += length
                matched = True
                break
            if not matched:
                return None

        return tuple(units)

    def plan(self, text: str) -> PlanResult:
        normalized_text = normalize_transcript(text)
        tokens = tuple(normalized_text.split())
        if not tokens:
            raise ValueError("Cannot synthesize empty text after normalization")

        units: List[PlannedUnit] = []
        index = 0
        while index < len(tokens):
            previous_unit = units[-1] if units else None
            matched_exact = False
            max_words = min(self.max_chunk_words, len(tokens) - index)
            for length in range(max_words, 0, -1):
                key = tokens[index : index + length]
                occurrences = self.chunk_index.get(key)
                if not occurrences:
                    continue
                occurrence = self._pick_best_chunk(occurrences, previous_unit, index)
                units.append(
                    PlannedUnit(
                        kind="exact_chunk" if length > 1 else "exact_word",
                        target_text=" ".join(key),
                        text=occurrence.text,
                        phones=(),
                        clip_id=occurrence.clip_id,
                        start_sample=occurrence.start_sample,
                        end_sample=occurrence.end_sample,
                        word_group=index,
                        confidence=occurrence.confidence,
                    )
                )
                index += length
                matched_exact = True
                break

            if matched_exact:
                continue

            token = tokens[index]
            piece_plan = self._plan_word_pieces(token, index, previous_unit)
            if piece_plan is not None:
                units.extend(piece_plan)
                index += 1
                continue

            phone_plan = self._plan_phone_fallback(token, index, previous_unit)
            if phone_plan is not None:
                units.extend(phone_plan)
                index += 1
                continue

            raise ValueError(f"Could not synthesize '{token}' inside '{normalized_text}' with current inventory")

        return PlanResult(
            merc=self.merc,
            input_text=text,
            normalized_text=normalized_text,
            units=tuple(units),
            sample_rate=self.sample_rate,
            master_audio_path=str(self.master_audio_path),
        )


def _record_from_clip(record: ClipRecord) -> Optional[BankRecord]:
    if record.alignment_status != "accepted" or not record.master_audio_path:
        return None
    if low_quality_transcript_reason(record) is not None:
        return None
    if not record.words or not record.phonemes:
        return None

    words = tuple(
        BankWord(
            text=normalize_transcript(word.text),
            start_sample=word.start_sample,
            end_sample=word.end_sample,
            master_start_sample=word.master_start_sample if word.master_start_sample is not None else record.master_start_sample + word.start_sample,
            master_end_sample=word.master_end_sample if word.master_end_sample is not None else record.master_start_sample + word.end_sample,
            confidence=word.confidence,
        )
        for word in record.words
        if normalize_transcript(word.text)
    )
    if not words:
        return None

    phonemes = tuple(
        BankPhoneme(
            label=phoneme.label,
            normalized_label=normalize_phone_label(phoneme.label),
            word_index=phoneme.word_index,
            start_sample=phoneme.start_sample,
            end_sample=phoneme.end_sample,
            master_start_sample=phoneme.master_start_sample if phoneme.master_start_sample is not None else record.master_start_sample + phoneme.start_sample,
            master_end_sample=phoneme.master_end_sample if phoneme.master_end_sample is not None else record.master_start_sample + phoneme.end_sample,
            confidence=phoneme.confidence,
        )
        for phoneme in record.phonemes
        if normalize_phone_label(phoneme.label)
    )
    if not phonemes:
        return None

    return BankRecord(
        clip_id=record.clip_id,
        merc=record.merc,
        sample_rate=record.sample_rate,
        master_audio_path=record.master_audio_path,
        words=words,
        phonemes=phonemes,
    )


def _records_from_manifest_payload(payload: Dict[str, object], merc: str) -> BankLoadResult:
    mercs = payload.get("mercs", {})
    if merc not in mercs:
        raise FileNotFoundError(f"Merc '{merc}' not found in manifest payload")

    masters = payload.get("masters", {})
    master_entry = masters.get(merc, {}) if isinstance(masters, dict) else {}
    master_audio_path = master_entry.get("audio_path", "") if isinstance(master_entry, dict) else ""
    sample_rate = int(master_entry.get("sample_rate", DEFAULT_SAMPLE_RATE)) if isinstance(master_entry, dict) else DEFAULT_SAMPLE_RATE
    records: List[BankRecord] = []

    for record in mercs.get(merc, []):
        if record.get("alignment_status") != "accepted":
            continue
        words_payload = record.get("words", [])
        phonemes_payload = record.get("phonemes", [])
        if not words_payload or not phonemes_payload:
            continue

        record_master_start = int(record.get("master_start_sample", 0))
        words = []
        for word in words_payload:
            text = normalize_transcript(str(word.get("text", "")))
            if not text:
                continue
            words.append(
                BankWord(
                    text=text,
                    start_sample=int(word["start_sample"]),
                    end_sample=int(word["end_sample"]),
                    master_start_sample=int(word.get("master_start_sample", record_master_start + int(word["start_sample"]))),
                    master_end_sample=int(word.get("master_end_sample", record_master_start + int(word["end_sample"]))),
                    confidence=word.get("confidence"),
                )
            )
        if not words:
            continue

        phonemes = []
        for phoneme in phonemes_payload:
            normalized_label = normalize_phone_label(str(phoneme.get("label", "")))
            if not normalized_label:
                continue
            phonemes.append(
                BankPhoneme(
                    label=str(phoneme["label"]),
                    normalized_label=normalized_label,
                    word_index=int(phoneme.get("word_index", -1)),
                    start_sample=int(phoneme["start_sample"]),
                    end_sample=int(phoneme["end_sample"]),
                    master_start_sample=int(phoneme.get("master_start_sample", record_master_start + int(phoneme["start_sample"]))),
                    master_end_sample=int(phoneme.get("master_end_sample", record_master_start + int(phoneme["end_sample"]))),
                    confidence=phoneme.get("confidence"),
                )
            )
        if not phonemes:
            continue

        records.append(
            BankRecord(
                clip_id=str(record["clip_id"]),
                merc=merc,
                sample_rate=int(record.get("sample_rate", sample_rate or DEFAULT_SAMPLE_RATE)),
                master_audio_path=str(record.get("master_audio_path") or master_audio_path),
                words=tuple(words),
                phonemes=tuple(phonemes),
            )
        )

    if not records:
        raise FileNotFoundError(f"No accepted records found for merc '{merc}' in manifest payload")

    resolved_master_path = records[0].master_audio_path or str(master_audio_path)
    return BankLoadResult(
        merc=merc,
        master_audio_path=Path(resolved_master_path),
        sample_rate=records[0].sample_rate or sample_rate or DEFAULT_SAMPLE_RATE,
        records=records,
    )


def load_voice_bank(
    layout: ProjectLayout,
    merc: str,
    pronunciation_resolver: Optional[PronunciationResolver] = None,
    manifest_path: Optional[Path] = None,
) -> VoiceBank:
    resolver = pronunciation_resolver or PronunciationResolver()

    if manifest_path is not None:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        loaded = _records_from_manifest_payload(payload, merc)
        master_audio_path = loaded.master_audio_path
        if not master_audio_path.is_absolute():
            master_audio_path = (layout.root / master_audio_path).resolve()
        return VoiceBank(
            merc=loaded.merc,
            master_audio_path=master_audio_path,
            sample_rate=loaded.sample_rate,
            records=loaded.records,
            pronunciation_resolver=resolver,
        )

    aligned_records = load_alignment_state(layout, merc)
    records = [converted for record in aligned_records if (converted := _record_from_clip(record)) is not None]
    if not records:
        raise FileNotFoundError(f"No accepted aligned records found for merc '{merc}'")
    master_audio_path = (layout.root / records[0].master_audio_path).resolve()
    return VoiceBank(
        merc=merc,
        master_audio_path=master_audio_path,
        sample_rate=records[0].sample_rate or DEFAULT_SAMPLE_RATE,
        records=records,
        pronunciation_resolver=resolver,
    )


@lru_cache(maxsize=32)
def _load_master_samples(master_audio_path: str) -> Tuple[int, Tuple[int, ...]]:
    path = Path(master_audio_path)
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        if channels != 1:
            raise ValueError(f"Expected mono master WAV, got {channels} channels: {path}")
        if sample_width != 2:
            raise ValueError(f"Expected 16-bit PCM master WAV, got sample width {sample_width}: {path}")
        frames = wav_file.readframes(wav_file.getnframes())
    samples = array("h")
    samples.frombytes(frames)
    return sample_rate, tuple(samples)


def _slice_samples(samples: Sequence[int], start_sample: int, end_sample: int) -> array:
    start = max(0, start_sample)
    end = max(start, end_sample)
    return array("h", samples[start:end])


def _append_with_crossfade(output: array, segment: array, overlap_samples: int) -> array:
    if not segment:
        return output
    if not output:
        return array("h", segment)

    overlap = min(overlap_samples, len(output), len(segment))
    if overlap <= 0:
        output.extend(segment)
        return output

    merged = array("h", output[:-overlap])
    left_tail = output[-overlap:]
    right_head = segment[:overlap]
    if overlap == 1:
        merged.append(_clamp_i16((left_tail[0] + right_head[0]) / 2.0))
    else:
        for index in range(overlap):
            blend = index / float(overlap - 1)
            left_gain = math.sqrt(max(0.0, 1.0 - blend))
            right_gain = math.sqrt(blend)
            merged.append(_clamp_i16(left_tail[index] * left_gain + right_head[index] * right_gain))
    merged.extend(segment[overlap:])
    return merged


def _needs_word_gap(previous: Optional[PlannedUnit], current: PlannedUnit) -> bool:
    if previous is None:
        return False
    if previous.word_group < 0 or current.word_group < 0:
        return False
    return previous.word_group != current.word_group


def _wav_bytes_from_samples(samples: Sequence[int], sample_rate: int) -> bytes:
    pcm = array("h", samples)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _estimate_acoustic_profile(
    samples: Sequence[int],
    sample_rate: int,
    start_sample: int,
    end_sample: int,
) -> AcousticProfile:
    start = max(0, start_sample)
    end = min(max(start, end_sample), len(samples))
    if end - start < 64:
        return AcousticProfile(pitch_hz=None, rms=0.0)

    max_window = max(256, sample_rate // 8)
    if end - start > max_window:
        trim = ((end - start) - max_window) // 2
        start += trim
        end = start + max_window

    window = [samples[index] / 32768.0 for index in range(start, end)]
    mean = sum(window) / float(len(window))
    centered = [value - mean for value in window]
    rms = math.sqrt(sum(value * value for value in centered) / float(len(centered)))
    if rms < 0.01 or len(centered) < 128:
        return AcousticProfile(pitch_hz=None, rms=rms)

    min_lag = max(1, int(sample_rate / 420.0))
    max_lag = min(len(centered) // 2, int(sample_rate / 70.0))
    if max_lag <= min_lag:
        return AcousticProfile(pitch_hz=None, rms=rms)

    best_correlation = 0.0
    best_lag = 0
    for lag in range(min_lag, max_lag + 1):
        numerator = 0.0
        left_energy = 0.0
        right_energy = 0.0
        for index in range(len(centered) - lag):
            left = centered[index]
            right = centered[index + lag]
            numerator += left * right
            left_energy += left * left
            right_energy += right * right
        if left_energy <= 1e-9 or right_energy <= 1e-9:
            continue
        correlation = numerator / math.sqrt(left_energy * right_energy)
        if correlation > best_correlation:
            best_correlation = correlation
            best_lag = lag

    pitch_hz = None
    if best_lag and best_correlation >= 0.18:
        pitch_hz = sample_rate / float(best_lag)
    return AcousticProfile(pitch_hz=pitch_hz, rms=rms)


def synthesize_plan(plan: PlanResult, crossfade_ms: int = 12, word_gap_ms: int = 24) -> bytes:
    sample_rate, master_samples = _load_master_samples(plan.master_audio_path)
    if sample_rate != plan.sample_rate:
        raise ValueError(
            f"Plan sample rate {plan.sample_rate} does not match master sample rate {sample_rate}: {plan.master_audio_path}"
        )

    overlap = int(round(sample_rate * (crossfade_ms / 1000.0)))
    word_gap = int(round(sample_rate * (word_gap_ms / 1000.0)))
    output = array("h")
    previous_unit: Optional[PlannedUnit] = None
    for unit in plan.units:
        segment = _slice_samples(master_samples, unit.start_sample, unit.end_sample)
        if word_gap > 0 and _needs_word_gap(previous_unit, unit):
            output.extend([0] * word_gap)
        output = _append_with_crossfade(output, segment, overlap)
        if segment:
            previous_unit = unit
    return _wav_bytes_from_samples(output, sample_rate)


class SplicerService:
    def __init__(self, layout: ProjectLayout) -> None:
        self.layout = layout
        self._resolver = PronunciationResolver()
        self._bank_cache: Dict[Tuple[str, str], VoiceBank] = {}

    def available_mercs(self) -> List[str]:
        mercs = []
        for merc in all_mercs():
            if self.layout.merc_aligned_path(merc).exists() or self.layout.merc_export_path(merc).exists():
                mercs.append(merc)
        return mercs

    def get_bank(self, merc: str, manifest_path: Optional[Path] = None) -> VoiceBank:
        cache_key = (merc, str(manifest_path.resolve()) if manifest_path is not None else "")
        if cache_key not in self._bank_cache:
            self._bank_cache[cache_key] = load_voice_bank(
                self.layout,
                merc,
                pronunciation_resolver=self._resolver,
                manifest_path=manifest_path,
            )
        return self._bank_cache[cache_key]

    def plan(self, merc: str, text: str, manifest_path: Optional[Path] = None) -> PlanResult:
        return self.get_bank(merc, manifest_path=manifest_path).plan(text)

    def synthesize(
        self,
        merc: str,
        text: str,
        manifest_path: Optional[Path] = None,
        crossfade_ms: int = 12,
        word_gap_ms: int = 24,
    ) -> Tuple[PlanResult, bytes]:
        plan = self.plan(merc, text, manifest_path=manifest_path)
        return plan, synthesize_plan(plan, crossfade_ms=crossfade_ms, word_gap_ms=word_gap_ms)


def run_splicer_server(layout: ProjectLayout, host: str = "127.0.0.1", port: int = 8768) -> None:
    service = SplicerService(layout)

    class Handler(BaseHTTPRequestHandler):
        server_version = "phonomenal-splicer/0.1"

        def _read_json(self) -> Dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length) if length else b"{}"
            if not payload:
                return {}
            return json.loads(payload.decode("utf-8"))

        def _write_json(self, status: int, payload: Dict[str, object]) -> None:
            encoded = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._write_json(HTTPStatus.OK, {"ok": True})
                return
            if self.path == "/mercs":
                self._write_json(HTTPStatus.OK, {"mercs": service.available_mercs()})
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                body = self._read_json()
                merc = str(body["merc"])
                text = str(body["text"])
                manifest_value = body.get("manifest")
                manifest_path = Path(str(manifest_value)) if manifest_value else None
                crossfade_ms = int(body.get("crossfade_ms", 12))
                if manifest_path is not None and not manifest_path.is_absolute():
                    manifest_path = (layout.root / manifest_path).resolve()

                if self.path == "/plan":
                    plan = service.plan(merc, text, manifest_path=manifest_path)
                    self._write_json(HTTPStatus.OK, {"ok": True, "plan": plan.to_dict()})
                    return

                if self.path == "/synthesize":
                    plan, wav_bytes = service.synthesize(
                        merc,
                        text,
                        manifest_path=manifest_path,
                        crossfade_ms=crossfade_ms,
                    )
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(len(wav_bytes)))
                    self.send_header("X-Phonomenal-Merc", plan.merc)
                    self.send_header("X-Phonomenal-Units", str(len(plan.units)))
                    self.end_headers()
                    self.wfile.write(wav_bytes)
                    return

                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            except Exception as exc:  # pragma: no cover - defensive handler path
                self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def write_splice_result(
    layout: ProjectLayout,
    merc: str,
    text: str,
    output_path: Optional[Path] = None,
    stdout_wav: bool = False,
    manifest_path: Optional[Path] = None,
    crossfade_ms: int = 12,
) -> PlanResult:
    service = SplicerService(layout)
    plan, wav_bytes = service.synthesize(
        merc,
        text,
        manifest_path=manifest_path,
        crossfade_ms=crossfade_ms,
    )

    if stdout_wav:
        sys.stdout.buffer.write(wav_bytes)
        sys.stdout.flush()
    elif output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(wav_bytes)
    else:
        raise ValueError("Expected either stdout_wav=True or an output_path")

    return plan
