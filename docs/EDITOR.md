# Manual voice-pack editor

Open the **Voice pack editor** FT tab, choose an imported pack and select **Open
a new editable copy**. The original `.vcpack` remains unchanged. GUI, TUI and web
use the same project format and validation code; the web editor adds a waveform
image and browser audio. Gruvbox is the default theme.

Choose a recording or section, then **Load selected section**. The recording JSON
lets you edit its ID, transcript, word/phone labels, confidence, start/end sample
positions and each phone's zero-based `word` index. You can add/remove word and
phone entries, clone a recording to define another sample selection, or delete a
recording from the draft. Keep at least one valid recording. Save draft edits
before switching sections. JSON is the editable source of truth, rather than a
rounded millisecond display.

**Preview edited recording** validates its intervals and plays its selected
audio. Optional start/end sample fields let you audition one boundary or sound.
The web waveform shows word and phone markers; hovering labels reveals sample
and millisecond coordinates. To convert a time, use
`sample = round(milliseconds * sample_rate / 1000)`.

Metadata, the full pronunciation dictionary and optional binary sections are
separate editable JSON documents. Extension values are base64-encoded bytes;
unknown optional sections are preserved. The text widget supports up to 16 MiB
per section. Larger sections can be edited directly in the project directory.
Replace the draft master audio with a mono PCM16 WAV at the same sample rate;
the previous draft WAV is retained. If audio content or length changes, adjust
every affected recording interval yourself before saving.

**Validate and save NEW voice pack** checks sample bounds, interval order,
phone-to-word containment, required data and checksums; audits every boundary;
rebuilds acoustic features; and writes a new pack atomically. Manual edits reset
the accuracy claim to unmeasured. Existing output filenames are rejected. The
new pack appears in the player dropdown; web mode also gives a download link.
The ASCII specification remains the final payload. Derived features and quality
reports are rebuilt rather than carrying forward stale values.

The frontend requires the Python builder environment for editing. A reusable
CLI is available for scripts and editors of your choice:

```sh
.venv-vcpack/bin/python scripts/pack_editor.py open --pack medic.vcpack --project data/editor/medic
# Edit metadata.json, lexicon.json, extensions.json and record-000000.json etc.
.venv-vcpack/bin/python scripts/pack_editor.py preview --project data/editor/medic --record 0 --start 137 --end 9137 --output data/editor/preview.wav
.venv-vcpack/bin/python scripts/pack_editor.py replace-audio --project data/editor/medic --input corrected-master.wav
.venv-vcpack/bin/python scripts/pack_editor.py save --project data/editor/medic --output medic-edited.vcpack
```

Web uploads go through managed pack/audio imports; visitors cannot supply project
paths or server commands. The deployed web editor uses the existing shared
workspace and login, without per-user isolation.
