# Phonomenal

Turn speech recordings into a portable voice pack, then mix new sentences from
that recorded voice. **Python builds the pack; C++ plans and renders speech.**
The desktop/terminal frontend uses [FT](https://github.com/aridlin/ft) with
**Gruvbox by default**, with a builder/recorder view and a separate TTS/player view.

Default target: **TF2 mercs**, starting with **Heavy**, then **Medic**, then
**Soldier**. The builder opens on Heavy; choose **My own voice** for the microphone
script. Existing local speech dumps go under `source/<merc>/`.

```sh
.venv-vcpack/bin/python scripts/builder.py build-mercs --merc heavy
.venv-vcpack/bin/python scripts/builder.py build-mercs --merc all
```

`all` processes Heavy, Medic, Soldier, Scout, Demoman, Engineer, Sniper, Spy, Pyro
in that order. TF2 recordings are supplied locally and are not included here.

## What works

- Speech MP3/WAV/OGG/FLAC/M4A folder import, automatic transcription, MFA word and
  phoneme alignment, and an explicitly verified boundary-refinement stage.
- 48 kHz playback audio with integer sample offsets, independently resampled
  analysis audio, resume checkpoints, and inspectable alignment/build reports.
- One binary `.vcpack` containing audio, words, phonemes, pronunciations, acoustic
  features and provenance, with section checksums and strict native validation.
- C++ phrase/word/phone planning that prefers long continuous recordings and
  compares candidate joins using boundary pitch, energy and spectral features.
- New words assembled from recorded phone sequences. A bundled pack lexicon and
  optional native eSpeak NG pronunciation supply sounds for unseen text.
- A 124-take reading script, microphone selection, recording meter, per-take WAV
  and transcript saving, background builds, cancel/resume, playback and WAV export.
- Native vctts integration under `vctts/`: dynamic pack discovery, cached engine,
  and chunk/approximation status.

The builder can be implemented in any language; Python is the current choice.
The current **spoken-language profile is English/ARPABET**. A finite recording
collection cannot accurately supply a phoneme that never occurs in it. Best-effort
mode reports approximations; `--strict` rejects missing coverage. The library does
not silently omit failed words. The bounded planner returns its best explored path.

## Build the C++ engine and FT frontend

Use a C++20 compiler and CMake. Linux GUI dependencies are Cairo and X11 development
libraries; audio uses the included miniaudio. On Windows use Visual Studio 2022.

```sh
cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build cpp/build --config Release -j 4
```

Linux executables are in `cpp/build/`; MSVC executables are in `cpp/build/Release/`.
Pass `-DPHONOMENAL_BUILD_FRONTEND=OFF` for just the native library and CLI.

```sh
./cpp/build/phonomenal_splicer_frontend --builder
./cpp/build/phonomenal_splicer_frontend --player
```

Both views are tabs in the same FT application. FT also accepts `--ft-gui`,
`--ft-tui`, and `--ft-web`. Web mode binds to localhost. The recorder captures
**the host computer's microphone**, including when its controls are viewed in a browser.
The TTS/player view requires no Python installation.

## Set up automatic pack generation

Install `uv` and FFmpeg, then run the appropriate project-local setup:

```sh
./scripts/setup_builder.sh
# Windows PowerShell:
# ./scripts/setup_builder.ps1
```

This creates `.venv-vcpack` and an isolated MFA environment under `.tools/`, and
fetches English acoustic/dictionary/G2P models. Initial downloads and alignment
can take time. Whisper downloads its selected model on first use. After models
are cached, processing is local. CPU is the default; `--device cuda` is optional.

```sh
.venv-vcpack/bin/python scripts/builder.py build-pack ./speech \
  --voice my-voice --output ./my-voice.vcpack
.venv-vcpack/bin/python scripts/builder.py inspect-pack ./my-voice.vcpack
```

On Windows substitute `.venv-vcpack/Scripts/python.exe`. The FT builder exposes
source/output paths and builder executable settings. Put one speaker in each
source folder. Optional `clip.txt` beside `clip.wav` supplies the exact transcript.
The built-in recorder creates those pairs automatically. Repeat the build command
to resume. Reports and raw alignments live next to the output in `*.build/`.

## Record a voice

Use **Voice pack builder → Record this take → Stop recording → Save take + transcript**.
Read naturally and keep microphone distance steady. Each take is saved separately.
Use a fresh folder for a new session. Existing takes are not overwritten silently.

The [original reading script](examples/recording-script/script.txt) contains about
1,500 words, all 39 CMU/ARPABET phonemes, and 768 adjacent phone pairs according
to the pronunciation dictionary. It is greedily ordered to cover useful rare
combinations early. This is measured script coverage, not a guarantee that every
speaker will pronounce every transition identically. Finish the full script for
more usable words and longer continuous chunks.

```sh
.venv-vcpack/bin/python scripts/builder.py recording-script --output ./my-script
```

## Generate speech

```sh
./cpp/build/phonomenal_splicer_cli --bank my-voice.vcpack \
  --text "Hello there. I need a little more time." --output message.wav --plan
printf 'Please open the door.' | ./cpp/build/phonomenal_splicer_cli \
  --bank my-voice.vcpack --stdin --stdout-wav > message.wav
./cpp/build/phonomenal_splicer_cli --bank my-voice.vcpack --phones "HH AH L OW" --plan
```

`--plan` emits JSON with exact sample spans and approximation warnings. If WAV is
sent to stdout, plan JSON goes to stderr, keeping audio bytes clean. Install
`espeak-ng` for native pronunciation of words beyond the pack lexicon. On Windows
its DLL and voice data must be available to the process. Without it, best-effort
uses a labelled heuristic fallback; strict mode fails rather than pretending it
has a reliable pronunciation. Digits are currently spoken individually.

The included [synthetic fixture example](examples/README.md) runs without downloading
speech models. It demonstrates container validation and chunk planning; it is not
an example of natural human voice quality.

## Boundary accuracy

Sentence mixing needs trustworthy **word and phoneme onsets/offsets**, not subtitles
rounded to seconds. MFA's refinement evaluates a 1 ms grid; the pack stores sample
positions. Actual linguistic accuracy is a separate measurement. Coarticulation,
wrong transcripts, noise and short consonants can still produce bad boundaries.

The isolated launcher repairs several specifically detected MFA 3.3.9 refinement
bugs and the builder rejects runs that did not execute fine tuning. It does not
assign whole-clip ASR confidence to individual phonemes. Source and aligned transcript
disagreements are rejected, and unusual phone durations are reported for inspection.

```sh
.venv-vcpack/bin/python scripts/builder.py compare-alignments \
  reference.json predicted.json --tolerance-ms 10
```

This reports word/phone boundary median, p95/p99, maximum error and label mismatches.
Use independently labelled references. No measured human-boundary accuracy or
blind naturalness score is claimed yet. Current synthesis uses conservative
crossfades; full pitch/time modification and contextual homograph/stress selection
remain quality work described in the [design plan](docs/vcpack_plan.md).

## Tests and integration

```sh
PYTHONPATH=src .venv-vcpack/bin/python -m unittest discover -s tests -v
```

Set `PHONOMENAL_TEST_CLI` to the built CLI to enable the Python/native compatibility
and synthesis tests. CI builds the core/frontend on Linux and Windows and builds
the bundled vctts integration on Windows. `vctts/` discovers `.vcpack` files in
its configured bank directory and plays them through its existing output routing.

See [binary format](docs/vcpack_format.md), [design plan](docs/vcpack_plan.md), and
[third-party notices](docs/THIRD_PARTY.md). MIT for project code; dependencies and
voice recordings retain their own licenses.
