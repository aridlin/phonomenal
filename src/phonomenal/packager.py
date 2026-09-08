from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from phonomenal.align import (
    _load_cmudict,
    _load_g2p,
    _pronunciation_for_token,
    load_alignment_state,
    low_quality_transcript_reason,
    normalize_transcript,
    source_category_hint_tokens,
)
from phonomenal.config import ProjectLayout, relative_to_root
from phonomenal.models import ClipRecord

PACKAGE_MAGIC = "PHONOMENAL_BANK"
PACKAGE_VERSION = "2"


def _escape_field(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _confidence_text(value: Optional[float]) -> str:
    if value is None:
        return "na"
    return f"{float(value):.6f}"


def _normalize_phone_label(label: str) -> str:
    return "".join(char for char in label.strip().upper() if not char.isdigit())


def _iter_accepted_records(records: Iterable[ClipRecord]) -> List[ClipRecord]:
    accepted = [
        record
        for record in records
        if (
            record.alignment_status == "accepted"
            and record.master_audio_path
            and record.words
            and record.phonemes
            and low_quality_transcript_reason(record) is None
        )
    ]
    if not accepted:
        raise ValueError("No accepted aligned records available to package")
    return accepted


def _word_phone_candidates(records: Sequence[ClipRecord]) -> Dict[str, Dict[Tuple[str, ...], Tuple[int, float]]]:
    candidates: Dict[str, Dict[Tuple[str, ...], Tuple[int, float]]] = {}
    for record in records:
        phones_by_word: Dict[int, List[Tuple[int, str, Optional[float]]]] = {}
        for phoneme in record.phonemes:
            if phoneme.word_index < 0:
                continue
            normalized = _normalize_phone_label(phoneme.label)
            if not normalized:
                continue
            phones_by_word.setdefault(phoneme.word_index, []).append(
                (phoneme.start_sample, normalized, phoneme.confidence)
            )

        for word_index, word in enumerate(record.words):
            token = normalize_transcript(word.text)
            if not token:
                continue
            phone_entries = sorted(phones_by_word.get(word_index, []), key=lambda item: item[0])
            phone_sequence = tuple(item[1] for item in phone_entries if item[1])
            if not phone_sequence:
                continue
            bucket = candidates.setdefault(token, {})
            count, confidence_sum = bucket.get(phone_sequence, (0, 0.0))
            bucket[phone_sequence] = (count + 1, confidence_sum + float(word.confidence or 0.0))
    return candidates


def _build_lexicon(records: Sequence[ClipRecord]) -> List[Tuple[str, Tuple[str, ...]]]:
    candidates = _word_phone_candidates(records)
    lexicon: Dict[str, Tuple[str, ...]] = {}
    for token, variants in candidates.items():
        best_sequence = max(
            variants.items(),
            key=lambda item: (item[1][0], item[1][1], len(item[0])),
        )[0]
        lexicon[token] = best_sequence

    extra_tokens = set()
    for record in records:
        extra_tokens.update(source_category_hint_tokens(record.source_category))

    cmu_dict = _load_cmudict()
    g2p = None
    g2p_failed = False
    for token in sorted(extra_tokens):
        if token in lexicon:
            continue
        try:
            if (cmu_dict is None or token not in cmu_dict) and g2p is None and not g2p_failed:
                try:
                    g2p = _load_g2p()
                except Exception:
                    g2p_failed = True
                    g2p = None
            phones = _pronunciation_for_token(token, cmu_dict, g2p)
        except Exception:
            continue
        normalized = tuple(
            phone
            for phone in (_normalize_phone_label(phone) for phone in phones)
            if phone
        )
        if normalized:
            lexicon[token] = normalized

    return sorted(lexicon.items())


def pack_voice_bank(
    layout: ProjectLayout,
    merc: str,
    output_path: Optional[Path] = None,
    bundle_master: bool = False,
) -> Path:
    layout.ensure()
    records = _iter_accepted_records(load_alignment_state(layout, merc))
    output_path = (output_path or layout.merc_package_path(merc)).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    master_source = (layout.root / records[0].master_audio_path).resolve()
    if bundle_master:
        master_destination = output_path.with_suffix(master_source.suffix)
        if master_source != master_destination:
            shutil.copy2(master_source, master_destination)
        master_reference = master_destination.name
    else:
        master_reference = master_source.relative_to(layout.root).as_posix()

    lines = [
        "\t".join((PACKAGE_MAGIC, PACKAGE_VERSION)),
        "\t".join(("merc", _escape_field(merc))),
        "\t".join(("sample_rate", str(records[0].sample_rate))),
        "\t".join(("master_audio", _escape_field(master_reference))),
    ]
    for token, phones in _build_lexicon(records):
        lines.append(
            "\t".join(
                (
                    "lexicon",
                    _escape_field(token),
                    _escape_field(" ".join(phones)),
                )
            )
        )

    for record in records:
        lines.append("\t".join(("record", _escape_field(record.clip_id))))
        for word in record.words:
            master_start = word.master_start_sample
            master_end = word.master_end_sample
            if master_start is None or master_end is None:
                master_start = record.master_start_sample + word.start_sample
                master_end = record.master_start_sample + word.end_sample
            lines.append(
                "\t".join(
                    (
                        "word",
                        _escape_field(word.text),
                        str(master_start),
                        str(master_end),
                        _confidence_text(word.confidence),
                    )
                )
            )
        for phoneme in record.phonemes:
            master_start = phoneme.master_start_sample
            master_end = phoneme.master_end_sample
            if master_start is None or master_end is None:
                master_start = record.master_start_sample + phoneme.start_sample
                master_end = record.master_start_sample + phoneme.end_sample
            lines.append(
                "\t".join(
                    (
                        "phoneme",
                        _escape_field(phoneme.label),
                        str(phoneme.word_index),
                        str(master_start),
                        str(master_end),
                        _confidence_text(phoneme.confidence),
                    )
                )
            )
        lines.append("endrecord")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
