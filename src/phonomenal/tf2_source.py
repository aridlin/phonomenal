from __future__ import annotations

import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from phonomenal.config import (
    AUDIO_EXTENSIONS,
    MERC_PAGES,
    NON_SPEECH_MARKERS,
    ROBOT_MARKERS,
    ProjectLayout,
    relative_to_root,
)
from phonomenal.models import ClipRecord

MEDIAWIKI_API = "https://wiki.teamfortress.com/w/api.php"
USER_AGENT = "phonomenal/0.1 (+https://openai.com)"
WHITESPACE_RE = re.compile(r"\s+")


def _looks_like_cloudflare_challenge(payload: str) -> bool:
    lowered = payload.lower()
    return "making sure you're not a bot" in lowered or "cf-browser-verification" in lowered


def _http_get_with_cloudscraper(url: str, binary: bool = False) -> bytes | str | None:
    try:
        import cloudscraper  # type: ignore
    except ImportError:
        return None

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    response = scraper.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    if binary:
        return response.content
    return response.text


def _http_get(url: str, binary: bool = False) -> bytes | str:
    cloudscraper_payload = _http_get_with_cloudscraper(url, binary=binary)
    if cloudscraper_payload is not None:
        return cloudscraper_payload

    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        payload = response.read()
    if binary:
        return payload
    decoded = payload.decode("utf-8", errors="replace")
    if _looks_like_cloudflare_challenge(decoded):
        raise RuntimeError(
            "The TF2 wiki returned a Cloudflare bot challenge. "
            "Install the project dependency `cloudscraper` to fetch source pages."
        )
    return decoded


def _http_get_json(url: str) -> Dict[str, object]:
    return json.loads(_http_get(url))


def _normalize_text(text: str) -> str:
    normalized = html.unescape(text).replace("\xa0", " ")
    normalized = WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def _extract_file_title(href: str, title: str) -> str:
    if title.startswith("File:"):
        return title
    parsed = urlparse(href)
    path = parsed.path or ""
    if "/wiki/File:" in path:
        return path.split("/wiki/", 1)[1]
    candidate = path.rsplit("/", 1)[-1]
    if candidate.lower().startswith("file:"):
        return candidate
    return title


def _is_audio_anchor(href: str, title: str) -> bool:
    lowered = f"{href} {title}".lower()
    return any(ext in lowered for ext in AUDIO_EXTENSIONS)


def _is_robot_asset(file_title: str) -> bool:
    lowered = file_title.lower()
    return any(marker in lowered for marker in ROBOT_MARKERS)


def _looks_like_non_speech(source_text: str) -> bool:
    lowered = source_text.lower().strip()
    if not lowered:
        return True
    if lowered.startswith("("):
        return any(marker in lowered for marker in NON_SPEECH_MARKERS)
    if any(marker in lowered for marker in NON_SPEECH_MARKERS) and '"' not in lowered and "'" not in lowered:
        return True
    return False


class ResponsePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: List[Dict[str, object]] = []
        self._li_depth = 0
        self._current: Optional[Dict[str, object]] = None

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attributes = {key: (value or "") for key, value in attrs}
        if tag == "li":
            self._li_depth += 1
            if self._li_depth == 1:
                self._current = {"text_parts": [], "audio_links": []}
            return

        if self._li_depth and tag == "a" and self._current is not None:
            href = attributes.get("href", "")
            title = attributes.get("title", "")
            if _is_audio_anchor(href, title):
                cast_links = self._current["audio_links"]
                assert isinstance(cast_links, list)
                cast_links.append({"href": href, "title": title})

    def handle_endtag(self, tag: str) -> None:
        if tag != "li" or not self._li_depth:
            return
        self._li_depth -= 1
        if self._li_depth == 0 and self._current is not None:
            self.items.append(self._current)
            self._current = None

    def handle_data(self, data: str) -> None:
        if not self._li_depth or self._current is None:
            return
        cast_parts = self._current["text_parts"]
        assert isinstance(cast_parts, list)
        cast_parts.append(data)


def parse_response_page(html_text: str, merc: str, source_page: str) -> List[Dict[str, str]]:
    parser = ResponsePageParser()
    parser.feed(html_text)
    records: List[Dict[str, str]] = []
    seen_titles: set[str] = set()

    for item in parser.items:
        audio_links = item["audio_links"]
        text_parts = item["text_parts"]
        if not audio_links:
            continue

        source_text = _normalize_text(" ".join(text_parts))
        if _looks_like_non_speech(source_text):
            continue

        file_title = ""
        for link in audio_links:
            candidate_title = _extract_file_title(link["href"], link["title"])
            if candidate_title and not _is_robot_asset(candidate_title):
                file_title = candidate_title
                break
        if not file_title or file_title in seen_titles:
            continue

        seen_titles.add(file_title)
        records.append(
            {
                "merc": merc,
                "source_page": source_page,
                "source_text": source_text,
                "file_title": file_title,
            }
        )

    return records


def fetch_page_candidates(merc: str) -> List[Dict[str, str]]:
    page_url = MERC_PAGES[merc]
    html_text = _http_get(page_url)
    return parse_response_page(html_text, merc=merc, source_page=page_url)


def resolve_download_url(file_title: str) -> str:
    query = urlencode(
        {
            "action": "query",
            "prop": "imageinfo",
            "iiprop": "url",
            "titles": file_title,
            "format": "json",
            "formatversion": "2",
        }
    )
    payload = _http_get_json(f"{MEDIAWIKI_API}?{query}")
    pages = payload.get("query", {}).get("pages", [])
    if not pages:
        raise RuntimeError(f"No MediaWiki file metadata returned for {file_title}")
    page = pages[0]
    imageinfo = page.get("imageinfo", [])
    if not imageinfo:
        raise RuntimeError(f"No download URL returned for {file_title}")
    return imageinfo[0]["url"]


def clip_id_for_url(merc: str, source_url: str) -> str:
    digest = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:10]
    return f"{merc}_{digest}"


def clip_id_for_source_path(merc: str, source_path: str) -> str:
    digest = hashlib.sha1(source_path.lower().encode("utf-8")).hexdigest()[:10]
    return f"{merc}_{digest}"


def _download_file(source_url: str, destination: Path, force: bool = False) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        return
    payload = _http_get(source_url, binary=True)
    destination.write_bytes(payload)


def _is_local_source_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS


def _should_skip_local_source(path: Path, merc_root: Path) -> bool:
    relative = path.relative_to(merc_root)
    parts = [part.lower() for part in relative.parts]
    stem = path.stem.lower()
    if stem.startswith("test_"):
        return True
    if any("giant robot" == part for part in parts):
        return True
    if "_giant_robot" in stem:
        return True
    return False


def scan_local_source_merc(
    merc: str,
    layout: ProjectLayout,
    limit: Optional[int] = None,
) -> List[ClipRecord]:
    merc_dir = layout.merc_source_dir(merc)
    if not merc_dir.exists():
        raise FileNotFoundError(f"Local source directory not found for merc '{merc}': {merc_dir}")

    source_files = [
        path
        for path in merc_dir.rglob("*")
        if _is_local_source_audio(path) and not _should_skip_local_source(path, merc_dir)
    ]
    source_files.sort(key=lambda item: item.relative_to(layout.root).as_posix().lower())
    if limit is not None:
        source_files = source_files[:limit]

    records: List[ClipRecord] = []
    for path in source_files:
        source_rel = relative_to_root(path, layout.root)
        category_rel = path.parent.relative_to(merc_dir)
        source_category = "" if str(category_rel) == "." else category_rel.as_posix()
        clip_id = clip_id_for_source_path(merc, source_rel)
        records.append(
            ClipRecord(
                clip_id=clip_id,
                merc=merc,
                source_url=source_rel,
                raw_path=source_rel,
                source_path=source_rel,
                source_category=source_category,
                source_page="local_source",
                source_text=source_category.replace("/", " "),
                file_title=path.name,
            )
        )

    save_catalog(layout, merc, records)
    return records


def fetch_merc(
    merc: str,
    layout: ProjectLayout,
    limit: Optional[int] = None,
    force: bool = False,
) -> List[ClipRecord]:
    layout.ensure()
    candidates = fetch_page_candidates(merc)
    if limit is not None:
        candidates = candidates[:limit]

    records: List[ClipRecord] = []
    for candidate in candidates:
        source_url = resolve_download_url(candidate["file_title"])
        suffix = Path(urlparse(source_url).path).suffix or ".wav"
        clip_id = clip_id_for_url(merc, source_url)
        raw_path = layout.merc_raw_dir(merc) / f"{clip_id}{suffix}"
        _download_file(source_url, raw_path, force=force)

        records.append(
            ClipRecord(
                clip_id=clip_id,
                merc=merc,
                source_url=source_url,
                raw_path=relative_to_root(raw_path, layout.root),
                source_page=candidate["source_page"],
                source_text=candidate["source_text"],
                file_title=candidate["file_title"],
            )
        )

    save_catalog(layout, merc, records)
    return records


def save_catalog(layout: ProjectLayout, merc: str, records: Iterable[ClipRecord]) -> Path:
    layout.ensure()
    path = layout.merc_catalog_path(merc)
    payload = {
        "merc": merc,
        "clips": [record.to_state_dict() for record in records],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_catalog(layout: ProjectLayout, merc: str) -> List[ClipRecord]:
    path = layout.merc_catalog_path(merc)
    if not path.exists():
        raise FileNotFoundError(f"Catalog not found for merc '{merc}': {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ClipRecord.from_dict(item) for item in payload.get("clips", [])]
