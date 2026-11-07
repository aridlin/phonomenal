"""Attach per-bank rendering preferences without changing recorded speech."""
from pathlib import Path
import math
import struct
from .vcpack import HEADER, DIRECTORY, _write_sections, inspect_pack


def configure_synthesis(path, *, center_join_cost=None, output=None):
    """Set a bank's center splice cost, or remove its override with None.

    Explicit native synthesis options take precedence over this preference.
    Other section payloads are retained; the writer refreshes the ASCII manual.
    """
    if center_join_cost is not None:
        if isinstance(center_join_cost, bool) or not isinstance(center_join_cost, (int, float)):
            raise ValueError('Center join cost must be a number between 0 and 1000')
        if not math.isfinite(center_join_cost) or not 0 <= center_join_cost <= 1000:
            raise ValueError('Center join cost must be finite and between 0 and 1000')
    source=Path(path);inspect_pack(source);raw=source.read_bytes();sections=[]
    for i in range(HEADER.unpack_from(raw)[2]):
        tag,flags,start,size,*_=DIRECTORY.unpack_from(raw,HEADER.size+i*DIRECTORY.size)
        if tag!=b'SOPT':sections.append((tag,flags,raw[start:start+size]))
    if center_join_cost is not None:
        sections.append((b'SOPT',0,struct.pack('<If',1,center_join_cost)))
    destination=Path(output) if output is not None else source
    _write_sections(destination,sections)
    return inspect_pack(destination)
