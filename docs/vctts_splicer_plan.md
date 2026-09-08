# VCTTS Splicer Plan

> Historical notes. The current proposed architecture and implementation sequence are in [the automatic builder and `.vcpack` plan](vcpack_plan.md), based on source inspection on 2026-09-08. Implementation claims below may be stale.

## Status

The runtime direction is now native C++, not Python.

Implemented pieces in this repo:

- offline Python packer: `python -m phonomenal pack-bank`
- native C++ library: [cpp/include/phonomenal_splicer/splicer.h](C:/Users/aridlin/code/codexp/phonomenal/cpp/include/phonomenal_splicer/splicer.h)
- native C++ implementation: [cpp/src/splicer.cpp](C:/Users/aridlin/code/codexp/phonomenal/cpp/src/splicer.cpp)
- native C++ CLI: [cpp/src/main.cpp](C:/Users/aridlin/code/codexp/phonomenal/cpp/src/main.cpp)
- separate FTUI frontend: [cpp/src/gui_main.cpp](C:/Users/aridlin/code/codexp/phonomenal/cpp/src/gui_main.cpp)

The native path already supports:

- exact multi-word and whole-word reuse
- word-piece fallback using smaller known words
- phoneme n-gram planning when phonemes are supplied explicitly
- WAV output to file today, and easy stdout wiring if we want the CLI to behave exactly like `vctts` Custom mode

## Integration Shape

Build the voice splicer as a native Windows static library plus optional CLI, and keep any GUI as a separate frontend binary layered on top of that library.

That fits the current repo well because:

- `main.cpp` routes the `Custom` voice through `custom_tts::SpeakCustomCommand(...)`
- `custom_tts.cpp` substitutes `{text}` into a command string and reads audio bytes from stdout
- `audio_playback` already plays the returned WAV buffer without needing microphone capture

Recommended packaged assets per merc:

```text
scout.phbank
scout.wav
```

Recommended command shape for the standalone CLI:

```text
phonomenal_splicer_cli.exe --bank C:\path\to\scout.phbank --stdout-wav --text "{text}"
```

Offline packaging command:

```text
python -m phonomenal pack-bank --merc scout --bundle-master
```

## Inputs

- `text`: UTF-8 text to speak
- `merc`: target voice bank
- `bank`: packaged `.phbank` bank file
- `master_audio`: resolved from the packaged bank metadata

## Core Synthesis Strategy

Use a longest-match, lowest-cost assembly search over the aligned inventory.

Priority ladder for each span:

1. exact whole-word match
2. multi-word chunk match
3. subword chunk match
4. phoneme sequence match
5. last-resort grapheme-to-phoneme expansion, then phoneme sequence match

Example:

- `minigun` -> try `minigun`
- if missing, try chunkings like `mini + gun`
- if `mini` is missing, try `mi + ni + gun`
- if chunk text is unavailable, fall back to phoneme-level assembly

## Inventory Build

At load time, build these indexes from the packaged bank:

- `word -> list<occurrence>`
- `normalized chunk token sequence -> list<occurrence>`
- `phoneme ngram -> list<occurrence>`

Each occurrence should carry:

- `master_start_sample`, `master_end_sample`
- `clip_id`
- `confidence`
- neighboring word/phoneme context

## Search and Cost Model

For a target text, normalize it the same way as the Python pipeline, then run dynamic programming over token positions.

Score candidates by:

- fewer chunks
- whole words over subwords
- longer chunks over shorter chunks
- higher alignment confidence
- fewer joins
- better neighboring-context continuity

For phoneme fallback, run the same DP over the phoneme sequence instead of tokens.

## Audio Assembly

Read all snippets from the master WAV, not from individual clip files.

For each join:

- trim leading/trailing silence lightly
- match RMS level between neighbors
- apply short equal-power crossfades
- keep time-stretching off by default
- allow tiny join smoothing only when needed

Output one PCM WAV stream to stdout so `vctts` can play it immediately.

The implemented version already does this.

## VCTTS Changes

Initial version:

- no `vctts` code changes are required if we use the CLI through the existing Custom command path
- cleaner long-term integration is to compile the static library into `vctts` directly and bypass process launch entirely
- the FTUI frontend in this repo is for local bank inspection and synthesis testing only; it is not part of the splicer core

Both paths fit the current repo because [`custom_tts.cpp`](https://github.com/aridlin/vctts/blob/master/custom_tts.cpp) already reads stdout bytes, while the direct-link path would avoid spawning a subprocess per utterance.

Nice next steps inside `vctts`:

- add a preset for `TF2 Splicer`
- store selected merc in UI state
- generate the command automatically instead of asking the user to type it

## Recommended Implementation Order

1. `tf2_splicer.exe` that loads one merc manifest and returns exact whole-word matches only
2. add DP chunking for multi-word and subword matches
3. add phoneme fallback
4. add join smoothing and loudness matching
5. add built-in text-to-phoneme fallback in C++ for unseen words
6. add `vctts` UI preset for merc selection and packaged bank discovery

## Current Limitation

The native `PlanText(...)` path already handles:

- exact chunk reuse
- exact word reuse
- recursive word-piece reuse

For phoneme-only fallback, the current native core already has `PlanPhonemes(...)`, but it does not yet ship with a built-in G2P or full lexicon for arbitrary new words. That is the next native feature to add, not a packaging blocker.

## Relevant VCTTS Files

- [README](https://github.com/aridlin/vctts/blob/master/README.md)
- [CMakeLists.txt](https://github.com/aridlin/vctts/blob/master/CMakeLists.txt)
- [main.cpp](https://github.com/aridlin/vctts/blob/master/main.cpp)
- [custom_tts.cpp](https://github.com/aridlin/vctts/blob/master/custom_tts.cpp)
- [custom_tts.h](https://github.com/aridlin/vctts/blob/master/custom_tts.h)
- [imgui_ui.cpp](https://github.com/aridlin/vctts/blob/master/imgui_ui.cpp)
- [app_state.h](https://github.com/aridlin/vctts/blob/master/app_state.h)
