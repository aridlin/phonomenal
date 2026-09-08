# Dependencies and provenance

- FT is aridlin's combined frontend library: https://github.com/aridlin/ft .
  `cpp/src/ft.hpp` was copied from the local FT tree at commit
  `33f082f5143f7f4197209acaad40e4d0c51505a6` on 2026-09-08, at the author's request.
  A fresh upstream clone later that day confirmed the same commit and an identical
  `ft.hpp`; the existing local FT checkout and its edits were preserved.
  Phonomenal adds two local response-wrapper changes: HTTP 204 responses send an
  empty body in both FT web transports. The editor uses this vendored FT version's
  FNV-1a widget IDs to consume a pending text edit before switching documents.
- miniaudio is vendored in `cpp/vendor/miniaudio.h` and the bundled vctts tree.
  Its dual public-domain/MIT license appears in the header and
  `vctts/extern/miniaudio/LICENSE` (release copy: `docs/licenses/miniaudio.txt`).
- Dear ImGui, used by vctts, retains `vctts/extern/imgui/LICENSE.txt`
  (release copy: `docs/licenses/imgui.txt`).
- eSpeak NG is optionally loaded at runtime for pronunciation only. It is GPLv3;
  its library/data are not bundled in this repository. See https://github.com/espeak-ng/espeak-ng .
- CMUdict, used for English pronunciations, retains its own license in the installed
  Python distribution. The builder may embed its pronunciation entries; distribute
  the CMUdict license with packs built with that lexicon.
- Faster Whisper, CTranslate2, MFA, Kalpy, their models, and other builder dependencies
  are installed separately with their own licenses. The narrowly detected MFA 3.3.9
  compatibility fixes run in `scripts/mfa_entry.py`; no system package is modified.

The original reading script and synthetic test fixture generator are included
under this project's MIT license. The public examples do not contain TF2 audio
or personal microphone recordings.
