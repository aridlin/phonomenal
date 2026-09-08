from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class WordAlignment:
    text: str
    start_s: float
    end_s: float
    start_sample: int
    end_sample: int
    confidence: Optional[float] = None
    master_start_s: Optional[float] = None
    master_end_s: Optional[float] = None
    master_start_sample: Optional[int] = None
    master_end_sample: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PhonemeAlignment:
    label: str
    word_index: int
    start_s: float
    end_s: float
    start_sample: int
    end_sample: int
    confidence: Optional[float] = None
    master_start_s: Optional[float] = None
    master_end_s: Optional[float] = None
    master_start_sample: Optional[int] = None
    master_end_sample: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClipRecord:
    clip_id: str
    merc: str
    source_url: str
    raw_path: str
    source_path: str = ""
    source_category: str = ""
    audio_path: str = ""
    master_audio_path: str = ""
    duration_s: float = 0.0
    sample_rate: int = 16000
    master_start_s: float = 0.0
    master_end_s: float = 0.0
    master_start_sample: int = 0
    master_end_sample: int = 0
    transcript_raw: str = ""
    transcript_norm: str = ""
    asr_confidence: Optional[float] = None
    alignment_status: str = "pending"
    reject_reasons: List[str] = field(default_factory=list)
    words: List[WordAlignment] = field(default_factory=list)
    phonemes: List[PhonemeAlignment] = field(default_factory=list)
    source_page: str = ""
    source_text: str = ""
    file_title: str = ""
    avg_logprob: Optional[float] = None
    no_speech_prob: Optional[float] = None

    def to_state_dict(self) -> Dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "merc": self.merc,
            "source_url": self.source_url,
            "raw_path": self.raw_path,
            "source_path": self.source_path,
            "source_category": self.source_category,
            "audio_path": self.audio_path,
            "master_audio_path": self.master_audio_path,
            "duration_s": self.duration_s,
            "sample_rate": self.sample_rate,
            "master_start_s": self.master_start_s,
            "master_end_s": self.master_end_s,
            "master_start_sample": self.master_start_sample,
            "master_end_sample": self.master_end_sample,
            "transcript_raw": self.transcript_raw,
            "transcript_norm": self.transcript_norm,
            "asr_confidence": self.asr_confidence,
            "alignment_status": self.alignment_status,
            "reject_reasons": list(self.reject_reasons),
            "words": [word.to_dict() for word in self.words],
            "phonemes": [phoneme.to_dict() for phoneme in self.phonemes],
            "source_page": self.source_page,
            "source_text": self.source_text,
            "file_title": self.file_title,
            "avg_logprob": self.avg_logprob,
            "no_speech_prob": self.no_speech_prob,
        }

    def to_export_dict(self) -> Dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "merc": self.merc,
            "source_path": self.source_path,
            "source_category": self.source_category,
            "audio_path": self.audio_path,
            "master_audio_path": self.master_audio_path,
            "master_start_s": self.master_start_s,
            "master_end_s": self.master_end_s,
            "master_start_sample": self.master_start_sample,
            "master_end_sample": self.master_end_sample,
            "source_url": self.source_url,
            "duration_s": self.duration_s,
            "sample_rate": self.sample_rate,
            "transcript_raw": self.transcript_raw,
            "transcript_norm": self.transcript_norm,
            "asr_confidence": self.asr_confidence,
            "alignment_status": self.alignment_status,
            "reject_reasons": list(self.reject_reasons),
            "words": [word.to_dict() for word in self.words],
            "phonemes": [phoneme.to_dict() for phoneme in self.phonemes],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ClipRecord":
        return cls(
            clip_id=payload["clip_id"],
            merc=payload["merc"],
            source_url=payload["source_url"],
            raw_path=payload["raw_path"],
            source_path=payload.get("source_path", ""),
            source_category=payload.get("source_category", ""),
            audio_path=payload.get("audio_path", ""),
            master_audio_path=payload.get("master_audio_path", ""),
            duration_s=float(payload.get("duration_s", 0.0)),
            sample_rate=int(payload.get("sample_rate", 16000)),
            master_start_s=float(payload.get("master_start_s", 0.0)),
            master_end_s=float(payload.get("master_end_s", 0.0)),
            master_start_sample=int(payload.get("master_start_sample", 0)),
            master_end_sample=int(payload.get("master_end_sample", 0)),
            transcript_raw=payload.get("transcript_raw", ""),
            transcript_norm=payload.get("transcript_norm", ""),
            asr_confidence=payload.get("asr_confidence"),
            alignment_status=payload.get("alignment_status", "pending"),
            reject_reasons=list(payload.get("reject_reasons", [])),
            words=[WordAlignment(**word) for word in payload.get("words", [])],
            phonemes=[PhonemeAlignment(**phoneme) for phoneme in payload.get("phonemes", [])],
            source_page=payload.get("source_page", ""),
            source_text=payload.get("source_text", ""),
            file_title=payload.get("file_title", ""),
            avg_logprob=payload.get("avg_logprob"),
            no_speech_prob=payload.get("no_speech_prob"),
        )
