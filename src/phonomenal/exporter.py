from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from phonomenal.align import load_alignment_state
from phonomenal.config import DEFAULT_MASTER_GAP_MS, SCHEMA_VERSION, ProjectLayout
from phonomenal.models import ClipRecord


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_manifest(merc_to_records: Dict[str, Sequence[ClipRecord]]) -> Dict[str, object]:
    masters = {}
    for merc, records in merc_to_records.items():
        master_audio_path = next((record.master_audio_path for record in records if record.master_audio_path), "")
        sample_rate = next((record.sample_rate for record in records if record.sample_rate), 0)
        if master_audio_path:
            masters[merc] = {
                "audio_path": master_audio_path,
                "gap_ms": DEFAULT_MASTER_GAP_MS,
                "sample_rate": sample_rate,
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "masters": masters,
        "mercs": {
            merc: [record.to_export_dict() for record in records]
            for merc, records in merc_to_records.items()
        },
    }


def _validate_interval(interval: Dict[str, object]) -> None:
    required = {"start_s", "end_s", "start_sample", "end_sample", "confidence"}
    missing = required - set(interval)
    if missing:
        raise ValueError(f"Interval missing required keys: {sorted(missing)}")
    if float(interval["end_s"]) < float(interval["start_s"]):
        raise ValueError("Interval end_s must be >= start_s")
    if int(interval["end_sample"]) < int(interval["start_sample"]):
        raise ValueError("Interval end_sample must be >= start_sample")


def validate_manifest_structure(manifest: Dict[str, object]) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {manifest.get('schema_version')}")
    if "generated_at" not in manifest:
        raise ValueError("Manifest missing generated_at")
    masters = manifest.get("masters", {})
    if masters and not isinstance(masters, dict):
        raise ValueError("Manifest masters must be an object when present")
    mercs = manifest.get("mercs")
    if not isinstance(mercs, dict) or not mercs:
        raise ValueError("Manifest mercs must be a non-empty object")

    for merc, master in masters.items():
        if not isinstance(master, dict):
            raise ValueError(f"Manifest master '{merc}' must be an object")
        if "audio_path" not in master or "sample_rate" not in master or "gap_ms" not in master:
            raise ValueError(f"Manifest master '{merc}' is missing required keys")

    for merc, records in mercs.items():
        if not isinstance(records, list):
            raise ValueError(f"Manifest merc '{merc}' must contain a list of records")
        for record in records:
            required = {
                "clip_id",
                "merc",
                "audio_path",
                "source_url",
                "duration_s",
                "sample_rate",
                "transcript_raw",
                "transcript_norm",
                "asr_confidence",
                "alignment_status",
                "reject_reasons",
                "words",
                "phonemes",
            }
            missing = required - set(record)
            if missing:
                raise ValueError(f"Record missing required keys: {sorted(missing)}")
            if record["merc"] != merc:
                raise ValueError(f"Record merc mismatch: expected '{merc}', got '{record['merc']}'")
            if float(record["duration_s"]) < 0:
                raise ValueError("duration_s must be >= 0")
            if int(record["sample_rate"]) <= 0:
                raise ValueError("sample_rate must be > 0")
            if not isinstance(record["reject_reasons"], list):
                raise ValueError("reject_reasons must be a list")
            if not isinstance(record["words"], list):
                raise ValueError("words must be a list")
            if not isinstance(record["phonemes"], list):
                raise ValueError("phonemes must be a list")

            last_word_end = -1
            for word in record["words"]:
                _validate_interval(word)
                if word["end_sample"] < last_word_end:
                    raise ValueError("Word intervals must be monotonic")
                last_word_end = word["end_sample"]

            for phoneme in record["phonemes"]:
                _validate_interval(phoneme)
                if "label" not in phoneme or "word_index" not in phoneme:
                    raise ValueError("Phoneme missing label or word_index")
                word_index = int(phoneme["word_index"])
                if record["words"] and word_index >= 0:
                    try:
                        word = record["words"][word_index]
                    except IndexError as exc:
                        raise ValueError("Phoneme word_index out of range") from exc
                    if float(phoneme["start_s"]) < float(word["start_s"]) - 1e-4:
                        raise ValueError("Phoneme starts before containing word")
                    if float(phoneme["end_s"]) > float(word["end_s"]) + 1e-4:
                        raise ValueError("Phoneme ends after containing word")


def export_manifests(layout: ProjectLayout, mercs: Iterable[str]) -> List[Path]:
    layout.ensure()
    merc_to_records = {merc: load_alignment_state(layout, merc) for merc in mercs}
    written_paths: List[Path] = []

    for merc, records in merc_to_records.items():
        manifest = build_manifest({merc: records})
        validate_manifest_structure(manifest)
        path = layout.merc_export_path(merc)
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        written_paths.append(path)

    merged_manifest = build_manifest(merc_to_records)
    validate_manifest_structure(merged_manifest)
    merged_path = layout.merged_export_path()
    merged_path.write_text(json.dumps(merged_manifest, indent=2), encoding="utf-8")
    written_paths.append(merged_path)
    return written_paths
