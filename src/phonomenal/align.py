from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from phonomenal.audio import ensure_normalized_audio, seconds_to_sample
from phonomenal.config import DEFAULT_SAMPLE_RATE, LIKELY_INTERJECTIONS, ProjectLayout
from phonomenal.models import ClipRecord, PhonemeAlignment, WordAlignment
from phonomenal.tf2_source import load_catalog

TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)*'?")
PHONE_RE = re.compile(r"^[A-Z]{1,3}\d?$")
SILENCE_LABELS = {"", "sp", "sil", "spn"}
HINT_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "the",
    "to",
    "up",
    "with",
}
TF2_PROMPT_TOKENS = (
    "sentry",
    "dispenser",
    "teleporter",
    "medic",
    "spy",
    "scout",
    "soldier",
    "pyro",
    "demoman",
    "heavy",
    "engineer",
    "sniper",
    "uber",
    "bonk",
)


def _load_whisperx():
    try:
        import whisperx  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "whisperx is not installed. Install optional deps with `pip install -e .[align]`."
        ) from exc
    return whisperx


def _load_cmudict():
    try:
        import cmudict  # type: ignore
    except ImportError:
        return None
    return cmudict.dict()


def _load_g2p():
    try:
        import nltk  # type: ignore
    except ImportError:
        nltk = None
    if nltk is not None:
        download_dir = os.environ.get("NLTK_DATA")
        for resource in ("averaged_perceptron_tagger", "averaged_perceptron_tagger_eng", "cmudict"):
            nltk.download(resource, download_dir=download_dir, quiet=True)
    try:
        from g2p_en import G2p  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "g2p_en is not installed. Install optional deps with `pip install -e .[align]`."
        ) from exc
    return G2p()


def normalize_transcript(text: str) -> str:
    lowered = text.lower()
    lowered = lowered.replace("\u2019", "'").replace("`", "'")
    lowered = lowered.replace("-", " ")
    tokens = [match.group(0).lstrip("'") for match in TOKEN_RE.finditer(lowered)]
    tokens = [token for token in tokens if token]
    return " ".join(tokens)


def is_obviously_non_speech(transcript_norm: str) -> bool:
    if not transcript_norm:
        return True
    tokens = transcript_norm.split()
    if len(tokens) == 1 and tokens[0] in LIKELY_INTERJECTIONS:
        return False
    if not any(any(char in "aeiouy" for char in token) for token in tokens):
        return True
    return False


def estimate_asr_confidence(avg_logprob: Optional[float], no_speech_prob: Optional[float]) -> Optional[float]:
    if avg_logprob is None and no_speech_prob is None:
        return None
    speech_score = 1.0 if no_speech_prob is None else max(0.0, min(1.0, 1.0 - no_speech_prob))
    lm_score = 0.5 if avg_logprob is None else max(0.0, min(1.0, math.exp(min(0.0, avg_logprob))))
    return round((speech_score + lm_score) / 2.0, 4)


def configure_runtime_cache(layout: ProjectLayout) -> Path:
    cache_dir = layout.cache_dir.resolve()
    huggingface_dir = cache_dir / "huggingface"
    torch_dir = cache_dir / "torch"
    nltk_dir = cache_dir / "nltk"
    for path in (cache_dir, huggingface_dir, torch_dir, nltk_dir):
        path.mkdir(parents=True, exist_ok=True)

    os.environ["XDG_CACHE_HOME"] = str(cache_dir)
    os.environ["HF_HOME"] = str(huggingface_dir)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(huggingface_dir / "hub")
    os.environ["TRANSFORMERS_CACHE"] = str(huggingface_dir / "transformers")
    os.environ["TORCH_HOME"] = str(torch_dir)
    os.environ["NLTK_DATA"] = str(nltk_dir)
    return cache_dir


class WhisperXTranscriber:
    def __init__(
        self,
        model_name: str = "small.en",
        device: Optional[str] = None,
        batch_size: int = 8,
        download_root: Optional[Path] = None,
    ) -> None:
        whisperx = _load_whisperx()
        self._whisperx = whisperx
        self._device = device or self._default_device()
        self._compute_type = "float16" if self._device == "cuda" else "int8"
        self._download_root = str(download_root) if download_root is not None else None
        self._model = whisperx.load_model(
            model_name,
            self._device,
            compute_type=self._compute_type,
            language="en",
            vad_method="silero",
            download_root=self._download_root,
        )
        self._batch_size = batch_size

    @staticmethod
    def _default_device() -> str:
        try:
            import torch  # type: ignore
        except ImportError:
            return "cpu"
        return "cuda" if torch.cuda.is_available() else "cpu"

    def transcribe(self, audio_path: Path, prompt_text: Optional[str] = None) -> Dict[str, object]:
        audio = self._whisperx.load_audio(str(audio_path))
        kwargs = {
            "batch_size": self._batch_size,
            "language": "en",
            "condition_on_prev_text": False,
            "temperature": 0.0,
        }
        if prompt_text:
            kwargs["initial_prompt"] = prompt_text
        try:
            result = self._model.transcribe(audio, **kwargs)
        except TypeError:
            fallback_attempts = [
                {"batch_size": self._batch_size, "language": "en", "initial_prompt": prompt_text}
                if prompt_text
                else {"batch_size": self._batch_size, "language": "en"},
                {"batch_size": self._batch_size, "language": "en"},
                {"batch_size": self._batch_size},
            ]
            last_error: Optional[TypeError] = None
            for fallback_kwargs in fallback_attempts:
                try:
                    result = self._model.transcribe(audio, **fallback_kwargs)
                    break
                except TypeError as exc:
                    last_error = exc
            else:
                if last_error is not None:
                    raise last_error
                raise RuntimeError("WhisperX transcribe fallback failed without a captured error")
        segments = result.get("segments", [])
        transcript_raw = "".join(segment.get("text", "") for segment in segments).strip()
        avg_logprob_values = [segment.get("avg_logprob") for segment in segments if segment.get("avg_logprob") is not None]
        no_speech_values = [
            segment.get("no_speech_prob") for segment in segments if segment.get("no_speech_prob") is not None
        ]
        avg_logprob = None
        if avg_logprob_values:
            avg_logprob = sum(avg_logprob_values) / len(avg_logprob_values)
        no_speech_prob = None
        if no_speech_values:
            no_speech_prob = max(no_speech_values)
        return {
            "result": result,
            "transcript_raw": transcript_raw,
            "avg_logprob": avg_logprob,
            "no_speech_prob": no_speech_prob,
        }


def source_category_hint_tokens(source_category: str) -> Tuple[str, ...]:
    if not source_category:
        return ()

    segments = [
        normalize_transcript(segment)
        for segment in source_category.replace("\\", "/").split("/")
    ]
    segments = [segment for segment in segments if segment]
    if not segments:
        return ()

    if len(segments) == 1:
        raw_tokens = segments[0].split()
    else:
        raw_tokens = segments[-1].split()

    ordered: List[str] = []
    seen = set()
    for token in raw_tokens:
        if token in HINT_STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return tuple(ordered)


def build_asr_prompt(source_category: str) -> Optional[str]:
    hint_tokens = source_category_hint_tokens(source_category)
    if not hint_tokens:
        return None
    prompt_tokens = list(hint_tokens)
    for token in TF2_PROMPT_TOKENS:
        if token not in prompt_tokens:
            prompt_tokens.append(token)
    return "Possible TF2 voice terms: " + " ".join(prompt_tokens)


def _best_hint_match(token: str, hint_tokens: Sequence[str]) -> Optional[str]:
    best_token: Optional[str] = None
    best_score = 0.0
    for hint in hint_tokens:
        score = SequenceMatcher(None, token, hint).ratio()
        if score > best_score:
            best_score = score
            best_token = hint
    if best_token is None:
        return None
    if best_score >= 0.74 and abs(len(best_token) - len(token)) <= 3:
        return best_token
    return None


def correct_transcript_with_hints(transcript_norm: str, source_category: str) -> str:
    if not transcript_norm:
        return transcript_norm

    hint_tokens = source_category_hint_tokens(source_category)
    if not hint_tokens:
        return transcript_norm

    corrected: List[str] = []
    for token in transcript_norm.split():
        if token in hint_tokens:
            corrected.append(token)
            continue
        hint_match = _best_hint_match(token, hint_tokens)
        corrected.append(hint_match or token)
    return " ".join(corrected)


def low_quality_transcript_reason(record: ClipRecord) -> Optional[str]:
    tokens = record.transcript_norm.split()
    if not tokens:
        return None

    duration_s = float(record.duration_s or 0.0)
    hint_tokens = set(source_category_hint_tokens(record.source_category))
    hint_overlap = len(hint_tokens.intersection(tokens))

    if (
        duration_s >= 1.0
        and len(tokens) == 1
        and tokens[0] not in LIKELY_INTERJECTIONS
        and hint_overlap == 0
    ):
        return "long_single_word_low_context"

    if (
        duration_s >= 1.6
        and len(tokens) <= 2
        and hint_overlap == 0
        and all(len(token) <= 6 for token in tokens)
    ):
        return "undertranscribed_for_duration"

    return None


def _pronunciation_for_token(token: str, cmu_dict, g2p=None) -> List[str]:
    if cmu_dict is not None and token in cmu_dict:
        first = cmu_dict[token][0]
        if isinstance(first, str):
            return first.split()
        return [str(phone) for phone in first]
    if g2p is None:
        raise RuntimeError(f"Missing pronunciation for token '{token}' and g2p_en is unavailable")
    raw = g2p(token)
    phones = [phone for phone in raw if PHONE_RE.match(phone)]
    if not phones:
        raise RuntimeError(f"Could not generate pronunciation for token '{token}'")
    return phones


def _build_dictionary(records: Sequence[ClipRecord], dictionary_path: Path) -> Path:
    tokens = sorted({token for record in records for token in record.transcript_norm.split()})
    cmu_dict = _load_cmudict()
    g2p = None
    lines = []
    for token in tokens:
        if (cmu_dict is None or token not in cmu_dict) and g2p is None:
            g2p = _load_g2p()
        phones = _pronunciation_for_token(token, cmu_dict, g2p)
        lines.append(f"{token} {' '.join(phones)}")
    dictionary_path.parent.mkdir(parents=True, exist_ok=True)
    dictionary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dictionary_path


def _prepare_mfa_corpus(records: Sequence[ClipRecord], corpus_dir: Path, root: Path) -> None:
    if corpus_dir.exists():
        shutil.rmtree(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        wav_source = root / record.audio_path
        wav_destination = corpus_dir / f"{record.clip_id}.wav"
        shutil.copy2(wav_source, wav_destination)
        (corpus_dir / f"{record.clip_id}.lab").write_text(record.transcript_norm, encoding="utf-8")


def _parse_command(command: str) -> List[str]:
    return shlex.split(command, posix=False)


def _run_mfa_align(
    corpus_dir: Path,
    dictionary_path: Path,
    output_dir: Path,
    mfa_command: str,
    acoustic_model: str = "english_us_arpa",
) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = _parse_command(mfa_command) + [
        "align",
        str(corpus_dir),
        str(dictionary_path),
        acoustic_model,
        str(output_dir),
        "--clean",
        "--fine_tune",
        "--output_format",
        "json",
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _load_mfa_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tiers_by_name(payload: Dict[str, object]) -> Dict[str, List[List[object]]]:
    tiers = payload.get("tiers", [])
    mapping: Dict[str, List[List[object]]] = {}
    if isinstance(tiers, dict):
        for name, tier in tiers.items():
            if isinstance(tier, dict):
                mapping[str(name)] = tier.get("entries", [])
        return mapping
    for tier in tiers:
        name = tier.get("name", "")
        entries = tier.get("entries", [])
        mapping[name] = entries
    return mapping


def _intervals_to_words(
    entries: Iterable[Sequence[object]],
    confidence: Optional[float],
    sample_rate: int,
) -> List[WordAlignment]:
    words: List[WordAlignment] = []
    for start_s, end_s, label in entries:
        if str(label).strip().lower() in SILENCE_LABELS:
            continue
        start = float(start_s)
        end = float(end_s)
        words.append(
            WordAlignment(
                text=str(label),
                start_s=round(start, 6),
                end_s=round(end, 6),
                start_sample=seconds_to_sample(start, sample_rate),
                end_sample=seconds_to_sample(end, sample_rate),
                confidence=None,  # ASR confidence is not boundary/phone confidence.
            )
        )
    return words


def _word_index_for_phone(start_s: float, end_s: float, words: Sequence[WordAlignment]) -> int:
    epsilon = 1e-4
    for index, word in enumerate(words):
        if start_s >= word.start_s - epsilon and end_s <= word.end_s + epsilon:
            return index
    return -1


def _intervals_to_phones(
    entries: Iterable[Sequence[object]],
    words: Sequence[WordAlignment],
    confidence: Optional[float],
    sample_rate: int,
) -> List[PhonemeAlignment]:
    phonemes: List[PhonemeAlignment] = []
    for start_s, end_s, label in entries:
        normalized_label = str(label).strip().lower()
        if normalized_label in SILENCE_LABELS:
            continue
        start = float(start_s)
        end = float(end_s)
        phonemes.append(
            PhonemeAlignment(
                label=str(label),
                word_index=_word_index_for_phone(start, end, words),
                start_s=round(start, 6),
                end_s=round(end, 6),
                start_sample=seconds_to_sample(start, sample_rate),
                end_sample=seconds_to_sample(end, sample_rate),
                confidence=None,  # ASR confidence is not boundary/phone confidence.
            )
        )
    return phonemes


def parse_mfa_alignment(path: Path, confidence: Optional[float], sample_rate: int) -> Tuple[List[WordAlignment], List[PhonemeAlignment]]:
    payload = _load_mfa_json(path)
    tiers = _tiers_by_name(payload)
    words = _intervals_to_words(tiers.get("words", []), confidence=confidence, sample_rate=sample_rate)
    phonemes = _intervals_to_phones(
        tiers.get("phones", []),
        words=words,
        confidence=None,  # ASR confidence is not boundary/phone confidence.
        sample_rate=sample_rate,
    )
    return words, phonemes


def save_alignment_state(layout: ProjectLayout, merc: str, records: Sequence[ClipRecord]) -> Path:
    path = layout.merc_aligned_path(merc)
    payload = {
        "merc": merc,
        "clips": [record.to_state_dict() for record in records],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_alignment_state(layout: ProjectLayout, merc: str) -> List[ClipRecord]:
    path = layout.merc_aligned_path(merc)
    if not path.exists():
        raise FileNotFoundError(f"Aligned state not found for merc '{merc}': {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ClipRecord.from_dict(item) for item in payload.get("clips", [])]


def _is_alignment_complete(record: ClipRecord) -> bool:
    if record.alignment_status == "accepted":
        return bool(record.words and record.phonemes and record.transcript_norm)
    if record.alignment_status == "rejected":
        return bool(record.reject_reasons)
    return False


def _merge_record_state(catalog_record: ClipRecord, existing_record: ClipRecord) -> ClipRecord:
    merged = replace(catalog_record)
    merged.audio_path = existing_record.audio_path or merged.audio_path
    merged.master_audio_path = existing_record.master_audio_path or merged.master_audio_path
    merged.duration_s = existing_record.duration_s or merged.duration_s
    merged.sample_rate = existing_record.sample_rate or merged.sample_rate
    merged.master_start_s = existing_record.master_start_s
    merged.master_end_s = existing_record.master_end_s
    merged.master_start_sample = existing_record.master_start_sample
    merged.master_end_sample = existing_record.master_end_sample
    merged.transcript_raw = existing_record.transcript_raw
    merged.transcript_norm = existing_record.transcript_norm
    merged.asr_confidence = existing_record.asr_confidence
    merged.alignment_status = existing_record.alignment_status
    merged.reject_reasons = list(existing_record.reject_reasons)
    merged.words = list(existing_record.words)
    merged.phonemes = list(existing_record.phonemes)
    merged.avg_logprob = existing_record.avg_logprob
    merged.no_speech_prob = existing_record.no_speech_prob
    return merged


def merge_catalog_with_alignment_state(
    catalog_records: Sequence[ClipRecord],
    aligned_records: Sequence[ClipRecord],
) -> List[ClipRecord]:
    aligned_by_id = {record.clip_id: record for record in aligned_records}
    merged_records: List[ClipRecord] = []
    for catalog_record in catalog_records:
        existing = aligned_by_id.get(catalog_record.clip_id)
        if existing is None:
            merged_records.append(catalog_record)
            continue
        merged_records.append(_merge_record_state(catalog_record, existing))
    return merged_records


def align_merc(
    merc: str,
    layout: ProjectLayout,
    whisper_model: str = "medium.en",
    batch_size: int = 8,
    mfa_command: str = "mfa",
    force: bool = False,
) -> List[ClipRecord]:
    configure_runtime_cache(layout)
    catalog_records = load_catalog(layout, merc)
    if force:
        records = list(catalog_records)
    else:
        try:
            aligned_records = load_alignment_state(layout, merc)
        except FileNotFoundError:
            records = list(catalog_records)
        else:
            records = merge_catalog_with_alignment_state(catalog_records, aligned_records)
    model_root = layout.cache_dir / "models" / whisper_model
    model_root.mkdir(parents=True, exist_ok=True)
    transcriber = WhisperXTranscriber(
        model_name=whisper_model,
        batch_size=batch_size,
        download_root=model_root,
    )
    save_alignment_state(layout, merc, records)

    accepted_for_mfa: List[ClipRecord] = []
    for record in records:
        if not force and _is_alignment_complete(record):
            continue
        if not force and record.alignment_status == "queued" and record.transcript_norm and not record.reject_reasons:
            ensure_normalized_audio(record, layout, force=False)
            accepted_for_mfa.append(record)
            continue

        ensure_normalized_audio(record, layout, force=force)
        transcription = transcriber.transcribe(
            layout.root / record.audio_path,
            prompt_text=build_asr_prompt(record.source_category),
        )
        record.transcript_raw = transcription["transcript_raw"]
        record.avg_logprob = transcription["avg_logprob"]
        record.no_speech_prob = transcription["no_speech_prob"]
        record.asr_confidence = estimate_asr_confidence(record.avg_logprob, record.no_speech_prob)
        record.transcript_norm = normalize_transcript(record.transcript_raw)
        record.transcript_norm = correct_transcript_with_hints(record.transcript_norm, record.source_category)
        record.reject_reasons = []

        if not record.transcript_norm:
            record.reject_reasons.append("empty_lexical_transcript")
        if record.no_speech_prob is not None and record.no_speech_prob > 0.5:
            record.reject_reasons.append("no_speech_prob_gt_0_5")
        if record.avg_logprob is not None and record.avg_logprob < -1.0:
            record.reject_reasons.append("avg_logprob_lt_neg_1")
        if is_obviously_non_speech(record.transcript_norm):
            record.reject_reasons.append("obviously_non_speech_output")
        low_quality_reason = low_quality_transcript_reason(record)
        if low_quality_reason is not None:
            record.reject_reasons.append(low_quality_reason)

        if record.reject_reasons:
            record.alignment_status = "rejected"
            save_alignment_state(layout, merc, records)
            continue

        record.alignment_status = "queued"
        accepted_for_mfa.append(record)
        save_alignment_state(layout, merc, records)

    if accepted_for_mfa:
        work_dir = layout.merc_work_dir(merc)
        corpus_dir = work_dir / "corpus"
        output_dir = work_dir / "aligned_json"
        dictionary_path = work_dir / "dictionary.dict"

        _prepare_mfa_corpus(accepted_for_mfa, corpus_dir, layout.root)
        _build_dictionary(accepted_for_mfa, dictionary_path)

        try:
            _run_mfa_align(
                corpus_dir=corpus_dir,
                dictionary_path=dictionary_path,
                output_dir=output_dir,
                mfa_command=mfa_command,
            )
        except subprocess.CalledProcessError:
            for record in accepted_for_mfa:
                record.alignment_status = "rejected"
                record.reject_reasons.append("failed_mfa_alignment")
            save_alignment_state(layout, merc, records)
        else:
            for record in accepted_for_mfa:
                alignment_path = output_dir / f"{record.clip_id}.json"
                if not alignment_path.exists():
                    record.alignment_status = "rejected"
                    record.reject_reasons.append("failed_mfa_alignment")
                    save_alignment_state(layout, merc, records)
                    continue
                words, phonemes = parse_mfa_alignment(
                    alignment_path,
                    confidence=record.asr_confidence,
                    sample_rate=record.sample_rate or DEFAULT_SAMPLE_RATE,
                )
                if not words or not phonemes:
                    record.alignment_status = "rejected"
                    record.reject_reasons.append("empty_alignment_intervals")
                    save_alignment_state(layout, merc, records)
                    continue
                record.words = words
                record.phonemes = phonemes
                record.alignment_status = "accepted"
                save_alignment_state(layout, merc, records)

    save_alignment_state(layout, merc, records)
    return records
