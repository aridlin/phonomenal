"""Repair old automatically observed pronunciations without rewriting recordings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from phonomenal.pack_editor import Reader
from phonomenal.vcpack import HEADER, DIRECTORY, inspect_pack, string, _write_sections


def repair_lexicon(source, output, dictionary=None):
    """Explicit migration for English packs; write a new file, retaining evidence.

    Keep valid pronunciation variants and unknown names. Only replace known
    dictionary words whose stored pronunciation matches none of their variants.
    This changes target pronunciation, never forced source labels or boundaries.
    """
    source, output = Path(source), Path(output)
    if output.exists() or source.resolve() == output.resolve():
        raise ValueError('Choose a new output filename; the original pack is preserved')
    inspect_pack(source)
    if dictionary is None:
        import cmudict
        dictionary = cmudict.dict()
    raw = source.read_bytes()
    sections, changes = [], []
    for i in range(HEADER.unpack_from(raw)[2]):
        tag, flags, start, length, _, _ = DIRECTORY.unpack_from(raw, HEADER.size + i * DIRECTORY.size)
        data = raw[start:start + length]
        if tag == b'META':
            meta = Reader(data)
            meta.string()
            if not meta.string().lower().startswith('en'):
                raise ValueError('Canonical pronunciation repair requires an English pack')
        if tag == b'LEXI':
            reader, lexicon = Reader(data), {}
            for _ in range(reader.count()):
                word = reader.string()
                phones = [reader.string() for _ in range(reader.count())]
                variants = dictionary.get(word.lower())
                if variants and phones not in variants:
                    changes.append(dict(word=word, before=phones, after=variants[0]))
                    phones = variants[0]
                lexicon[word] = phones
            reader.done()
            data = struct.pack('<I', len(lexicon)) + b''.join(
                string(w) + struct.pack('<I', len(ps)) + b''.join(string(p) for p in ps)
                for w, ps in lexicon.items())
        sections.append((tag, flags, data))
    # Keep all existing reports and opaque extensions. Add migration provenance
    # to QARE, without recalculating/inventing alignment or recognition scores.
    report = dict(source_sha256=hashlib.sha256(raw).hexdigest(), changes=changes)
    for i, (tag, flags, data) in enumerate(sections):
        if tag == b'QARE':
            quality = json.loads(data)
            quality['canonical_lexicon_repair'] = report
            sections[i] = tag, flags, json.dumps(quality, ensure_ascii=False).encode()
    _write_sections(output, sections)
    inspect_pack(output)
    return report
