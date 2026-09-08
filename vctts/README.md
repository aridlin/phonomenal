# VOICECHAT TTS

A lightweight Windows overlay that lets you type a short message and play it over **two output devices at once**.  
Designed for games and voice chat where you need **fast TTS** without touching your microphone.

---

## Features

- **Offline Windows TTS** using system voices (WinRT / SAPI).
  - Uses installed Windows voices (e.g. *Adam, Zira, David*, etc.).
  - Voice selectable from the config menu.
- **Native Phonomenal engine** for TF2 merc voice splicing.
  - Exposes **Scout, Soldier, Pyro, Demoman, Heavy, Engineer, Medic, Sniper, and Spy** as voices.
  - Uses packaged `.phbank` voice banks directly with no Python runtime in the app.
- **Optional online keyless TTS fallback** (StreamElements).
- **Dual output device playback** (play to two speakers / virtual cables simultaneously).
- **Reliable keyboard input** (proper layout + dead-key handling via `WM_CHAR`).
- **Global hotkeys** for quick start/stop while in-game.
- **No microphone interference** – pure playback.

---

## Requirements

- **Windows 10 / 11**
- **Visual Studio 2022** or newer (Desktop C++ workload)
- **CMake 3.20+**
- A C++20-compatible compiler (MSVC or clang-cl)

---

## Dependencies

All required third-party libraries are **already included** in the repository:

```
extern/
imgui/
miniaudio/
```

No external downloads or package managers required.

---

## Build (Windows)

### Using CMake + Ninja (recommended)

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

### Phonomenal Engine Notes

- In this workspace integration, `vctts` builds against the native splicer source from the sibling `phonomenal/cpp` directory.
- The app auto-detects merc banks from nearby `data/packages` folders when possible.
- You can also set the bank directory manually in the config UI and point it at a folder containing:

```text
scout.phbank
soldier.phbank
pyro.phbank
demoman.phbank
heavy.phbank
engineer.phbank
medic.phbank
sniper.phbank
spy.phbank
```

- Select `Phonomenal` in the engine picker, choose a merc voice, then press `Test TTS` or start the overlay normally.
