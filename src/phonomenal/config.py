from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_MASTER_GAP_MS = 250
SCHEMA_VERSION = "1.0"

MERC_PAGES: Dict[str, str] = {
    "scout": "https://wiki.teamfortress.com/wiki/Scout_responses",
    "soldier": "https://wiki.teamfortress.com/wiki/Soldier_responses",
    "pyro": "https://wiki.teamfortress.com/wiki/Pyro_responses",
    "demoman": "https://wiki.teamfortress.com/wiki/Demoman_responses",
    "heavy": "https://wiki.teamfortress.com/wiki/Heavy_responses",
    "engineer": "https://wiki.teamfortress.com/wiki/Engineer_responses",
    "medic": "https://wiki.teamfortress.com/wiki/Medic_responses",
    "sniper": "https://wiki.teamfortress.com/wiki/Sniper_responses",
    "spy": "https://wiki.teamfortress.com/wiki/Spy_responses",
}

AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg")
ROBOT_MARKERS = ("robot", "mvm", "giant")
NON_SPEECH_MARKERS = (
    "grunt",
    "laughter",
    "laugh",
    "scream",
    "whooshing sound",
    "blows a raspberry",
    "cry",
    "groan",
    "moan",
    "snore",
)
LIKELY_INTERJECTIONS = {
    "ah",
    "aha",
    "aw",
    "boom",
    "bonk",
    "boink",
    "bring",
    "go",
    "ha",
    "hey",
    "ho",
    "hoo",
    "look",
    "mush",
    "nice",
    "nope",
    "oop",
    "push",
    "psyche",
    "sweet",
    "wah",
    "woo",
    "woosh",
    "yeah",
    "yes",
    "yoink",
}


@dataclass(frozen=True)
class ProjectLayout:
    root: Path

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def catalog_dir(self) -> Path:
        return self.data_dir / "catalog"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def wav_dir(self) -> Path:
        return self.data_dir / "wav"

    @property
    def aligned_dir(self) -> Path:
        return self.data_dir / "aligned"

    @property
    def master_dir(self) -> Path:
        return self.data_dir / "master"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def package_dir(self) -> Path:
        return self.data_dir / "packages"

    @property
    def schema_path(self) -> Path:
        return self.root / "schemas" / "merc_manifest.schema.json"

    def ensure(self) -> None:
        for path in (
            self.catalog_dir,
            self.raw_dir,
            self.wav_dir,
            self.aligned_dir,
            self.master_dir,
            self.cache_dir,
            self.work_dir,
            self.export_dir,
            self.export_dir / "mercs",
            self.package_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def merc_raw_dir(self, merc: str) -> Path:
        return self.raw_dir / merc

    def merc_wav_dir(self, merc: str) -> Path:
        return self.wav_dir / merc

    def merc_source_dir(self, merc: str) -> Path:
        return self.source_dir / merc

    def merc_catalog_path(self, merc: str) -> Path:
        return self.catalog_dir / f"{merc}.json"

    def merc_aligned_path(self, merc: str) -> Path:
        return self.aligned_dir / f"{merc}.json"

    def merc_export_path(self, merc: str) -> Path:
        return self.export_dir / "mercs" / f"{merc}.json"

    def merc_master_path(self, merc: str) -> Path:
        return self.master_dir / f"{merc}.wav"

    def merged_export_path(self) -> Path:
        return self.export_dir / "tf2_mercs.json"

    def merc_package_path(self, merc: str) -> Path:
        return self.package_dir / f"{merc}.phbank"

    def merc_work_dir(self, merc: str) -> Path:
        return self.work_dir / merc


def default_layout(root: Path | None = None) -> ProjectLayout:
    return ProjectLayout(root=(root or Path.cwd()).resolve())


def resolve_mercs(merc: str) -> List[str]:
    if merc == "all":
        return list(MERC_PAGES.keys())
    if merc not in MERC_PAGES:
        supported = ", ".join(sorted(MERC_PAGES))
        raise ValueError(f"Unsupported merc '{merc}'. Expected one of: {supported}, all")
    return [merc]


def relative_to_root(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def all_mercs() -> Iterable[str]:
    return MERC_PAGES.keys()
