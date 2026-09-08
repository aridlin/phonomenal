# Phonomenal test build

Both the **Generator** and **TTS Player** are included. They open separate views
of the same native FT app, using Gruvbox. Extract the whole archive first.

- **Linux x86-64:** run `./generator.sh` or `./tts-player.sh`. Built on Ubuntu
  24.04; requires glibc 2.39 or newer, libstdc++, Cairo and X11/XWayland.
- **Windows x86-64:** double-click `Generator.cmd` or `TTS Player.cmd`.
  The C++ runtime is linked statically. Windows 10/11 is the intended target.
- The CLI is in `bin/`. The Windows vctts overlay is a separate release asset.

## Try the player immediately

No Python or models are needed for playback. Select your `.vcpack`, enter a
sentence, click **Generate**, then **Play** or **Save WAV**. Your voice pack is
self-contained. Heavy is the default if `data/packages/heavy.vcpack` exists.

`examples/demo.vcpack` is a synthetic tone fixture, not human speech. Use the
prompt `hello there friend` to check that a complete phrase uses one chunk:

```sh
./bin/phonomenal_splicer_cli --bank examples/demo.vcpack --text "hello there friend" --plan --output demo.wav
```

On Windows use `bin\phonomenal_splicer_cli.exe`. For real speech, create a pack
from recordings. Game audio and personal recordings are not in these downloads.

## Prepare the generator once

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and
[FFmpeg](https://ffmpeg.org/download.html), available on PATH. Run
`scripts/setup_builder.sh` on Linux or `scripts/setup_builder.ps1` in Windows
PowerShell, then reopen the Generator. Setup downloads several large speech
models into a project-local environment. First transcription also downloads
Whisper. Internet is needed for setup; cached processing runs locally.

Choose **Heavy**, then Medic and Soldier, for local TF2 source folders. Choose
**My own voice** to record the original 124-take script. Record, stop and save
each take with its transcript; then build the pack. Default speech language is
English. One speaker per source folder.

## What has been verified

Linux and Windows CI build the engine and both FT views, and run 51 Python/native
tests. Windows CI also builds and tests vctts. A local automatic Heavy test built
6 MP3 clips into a pack containing 39 words and 121 phonemes, with refinement
actually executed. Linux GUI generation and export are exercised separately.
The Windows GUI and physical microphone capture have not been manually tested.

The aligner evaluates a **1 ms refinement grid** and stores integer sample
boundaries. This is timing resolution, not a measured 1 ms accuracy guarantee.
Human-labelled boundary accuracy and blind listening quality remain unmeasured.
Small corpora can require phoneme approximations; the plan reports these and
strict mode rejects missing coverage. Optional eSpeak NG supplies pronunciation
for words outside the pack lexicon. See README.md for setup and limitations.
