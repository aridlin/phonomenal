# VCPACK v1 binary format

The implementation is `src/phonomenal/vcpack.py` and `cpp/src/vcpack_reader.inc`.
All integers and IEEE-754 float32 fields use little-endian byte order. There is
no native struct padding. Samples are signed mono PCM16. Intervals are half-open
`[start_sample, end_sample)` in the embedded audio's sample clock.

Header: `8-byte magic VCPACK\0\0`, `u32 version=1`, `u32 section_count`,
`u64 total_file_bytes`. Each directory entry is 32 bytes:
`4-byte type`, `u32 required_flag`, `u64 offset`, `u64 length`, `u32 CRC32`,
`u32 reserved=0`. Sections follow consecutively in directory order. CRC32 uses
the standard zlib/IEEE polynomial and covers section bytes only. Reject overlaps,
truncation, incompatible versions, duplicate types, unknown required sections,
invalid references and checksum errors. This implementation caps files at 2 GiB.

`string` means `u32 UTF-8 byte_count` followed by those bytes. It must not contain
NUL. A `confidence` is float32 in `[0,1]`, or exactly `-1` for unknown. ASR
confidence must never be substituted for independently measured phone confidence.

| Section | Encoding |
|---|---|
| META (required) | voice string, language string, phone alphabet string (`arpabet`), sample rate u32 |
| RECS (required) | u32 recording count; each record: ID string, raw transcript string, u32 word count + words, u32 phone count + phones |
| Word | label string, u64 start, u64 end, confidence |
| Phone | original label string (including stress), i32 word index within record, u64 start, u64 end, confidence |
| AUDI (required) | Consecutive signed little-endian PCM16 samples, no WAV header |
| LEXI | u32 entry count; each: word string, u32 phone count, phone strings |
| FEAT | u32 hop in samples, u32 dimensions=11, u64 frame count, frame_count × 11 float32 values |
| QARE | UTF-8 JSON diagnostic/provenance report; it is not an executable configuration |

Feature rows contain F0 in Hz (zero when unavailable), voicing confidence, RMS,
and eight centered log spectral-band energies. Default feature hop is 5 ms;
features describe audio and do not establish linguistic boundary precision.

The builder uses 48 kHz playback audio and a time-matched 16 kHz analysis copy.
Sample storage resolution is about 0.021 ms at 48 kHz. MFA fine tuning uses a
1 ms feature grid. Neither fact proves sub-millisecond boundary accuracy.
Recognition and timing require independent evaluation; see `compare-alignments`.

Indexes are currently built in C++ from RECS on load. No external WAV or original
recording is needed. The current reader collapses stress for phone lookup while
retaining stress in RECS; context-dependent pronunciation selection is still a
quality improvement area. `.phbank` remains supported for migration.
