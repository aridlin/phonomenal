from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from typing import Dict, Sequence

from phonomenal.config import DEFAULT_MASTER_GAP_MS, DEFAULT_SAMPLE_RATE, ProjectLayout, relative_to_root
from phonomenal.models import ClipRecord


def seconds_to_sample(seconds: float, sample_rate: int = DEFAULT_SAMPLE_RATE) -> int:
    return int(round(seconds * sample_rate))


def _ffmpeg_binary() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _trim_filter() -> str:
    return (
        "silenceremove="
        "start_periods=1:start_duration=0.05:start_threshold=-45dB:"
        "stop_periods=1:stop_duration=0.08:stop_threshold=-45dB"
    )


def normalize_audio(
    source_path: Path,
    destination_path: Path,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    force: bool = False,
) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists() and not force:
        return destination_path

    command = [
        _ffmpeg_binary(),
        "-y",
        "-i",
        str(source_path),
        "-af",
        _trim_filter(),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        str(destination_path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return destination_path


def probe_audio(audio_path: Path) -> Dict[str, float | int]:
    with wave.open(str(audio_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        frame_count = wav_file.getnframes()
    duration_s = frame_count / float(sample_rate)
    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "frame_count": frame_count,
        "duration_s": duration_s,
    }


def ensure_normalized_audio(
    record: ClipRecord,
    layout: ProjectLayout,
    force: bool = False,
) -> ClipRecord:
    raw_path = layout.root / record.raw_path
    destination = layout.merc_wav_dir(record.merc) / f"{record.clip_id}.wav"
    normalize_audio(raw_path, destination, force=force)
    metadata = probe_audio(destination)
    record.audio_path = relative_to_root(destination, layout.root)
    record.sample_rate = int(metadata["sample_rate"])
    record.duration_s = round(float(metadata["duration_s"]), 6)
    return record


def _project_master_offsets(record: ClipRecord) -> None:
    for word in record.words:
        word.master_start_sample = record.master_start_sample + word.start_sample
        word.master_end_sample = record.master_start_sample + word.end_sample
        word.master_start_s = round(word.master_start_sample / float(record.sample_rate), 6)
        word.master_end_s = round(word.master_end_sample / float(record.sample_rate), 6)

    for phoneme in record.phonemes:
        phoneme.master_start_sample = record.master_start_sample + phoneme.start_sample
        phoneme.master_end_sample = record.master_start_sample + phoneme.end_sample
        phoneme.master_start_s = round(phoneme.master_start_sample / float(record.sample_rate), 6)
        phoneme.master_end_s = round(phoneme.master_end_sample / float(record.sample_rate), 6)


def build_merc_master(
    merc: str,
    records: Sequence[ClipRecord],
    layout: ProjectLayout,
    gap_ms: int = DEFAULT_MASTER_GAP_MS,
    force: bool = False,
) -> Path:
    if not records:
        raise ValueError(f"No records available to build master for merc '{merc}'")

    for record in records:
        ensure_normalized_audio(record, layout, force=force)

    master_path = layout.merc_master_path(merc)
    master_path.parent.mkdir(parents=True, exist_ok=True)
    if master_path.exists() and force:
        master_path.unlink()

    first_audio_path = layout.root / records[0].audio_path
    with wave.open(str(first_audio_path), "rb") as first_wav:
        channels = first_wav.getnchannels()
        sample_rate = first_wav.getframerate()
        sample_width = first_wav.getsampwidth()

    gap_samples = seconds_to_sample(gap_ms / 1000.0, sample_rate)
    silence_bytes = b"\x00" * gap_samples * channels * sample_width
    cursor_samples = 0

    with wave.open(str(master_path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)

        for index, record in enumerate(records):
            audio_path = layout.root / record.audio_path
            with wave.open(str(audio_path), "rb") as wav_file:
                frame_count = wav_file.getnframes()
                frames = wav_file.readframes(frame_count)

            record.master_audio_path = relative_to_root(master_path, layout.root)
            record.master_start_sample = cursor_samples
            record.master_end_sample = cursor_samples + frame_count
            record.master_start_s = round(record.master_start_sample / float(sample_rate), 6)
            record.master_end_s = round(record.master_end_sample / float(sample_rate), 6)
            _project_master_offsets(record)

            writer.writeframes(frames)
            cursor_samples += frame_count

            if index != len(records) - 1 and gap_samples > 0:
                writer.writeframes(silence_bytes)
                cursor_samples += gap_samples

    return master_path
