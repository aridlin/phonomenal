# FT web deployment

The web app is the same FT/C++ frontend (`--ft-web`), with browser I/O added
through FT's HTML widgets. It is served at `/phonomenal/` behind Caddy, while
FT listens on `127.0.0.1:8766`. Caddy preserves the prefix for FT form submissions
and serves generated files from `data/public` under `/phonomenal/files/`.

The web player has the same imported-pack dropdown, chunk planner and STT check.
Audio plays in an HTML audio element on the visitor's device. Upload `.vcpack`
files or a batch of speech recordings and optional matching `.txt` transcripts.
Files are limited to 64 MiB each. Existing filenames are preserved, not overwritten.
The microphone button uses the browser's permission prompt and MediaRecorder,
saving the selected script take and its transcript. FFmpeg decodes browser
WebM/Opus, Ogg/Opus or M4A recordings before alignment.

This is a **shared workspace**, protected by the ProLiant's existing login.
It does not provide separate accounts or private per-visitor jobs. Start a new
recording session for each speaker. Browser users cannot edit server paths or
builder executables; uploads stay in managed application folders. The service
runs as its own unprivileged account and its listener is not exposed publicly.

See `deploy/phonomenal-web.service` and `deploy/Caddy.snippet` for the actual
service and route. Provision the builder with `scripts/setup_builder.sh` as the
service user. The service allows writes to MFA's `Documents/MFA` working directory. Native frontend dependencies on Ubuntu are Cairo and X11; the web
mode does not require a running desktop. FFmpeg and optional eSpeak NG should be
on PATH. The playback side itself does not require Python; the generator and STT
check use the local builder environment.

Background results refresh lazily: a visible browser checks a revision once per
second, receives an empty HTTP 204 when nothing changed, and updates only changed
result regions. It preserves unsent text, the cursor, and an unchanged audio
element. There is no timed page reload. Uploads also update through a response
patch instead of browser navigation. Hidden tabs pause polling.
Generated WAV and built-pack links download through Caddy. Desktop/TUI modes keep
using local microphone/audio devices; the web mode uses the browser instead.

The player checks all selected word, phoneme and splice boundaries on every
render. It reports suspect durations/waveform jumps and automatically runs an
unprompted STT check by default. The audio becomes available before STT completes.
Neither check certifies intelligibility. Optional pitch-band correction raises
low voiced chunks and lowers high ones, retaining the original sample count;
large shifts can sound artificial. Original pitch is the default.

The third tab is the [manual pack editor](EDITOR.md). It works on a separate
editable copy, previews exact sample selections, and validates a new pack before
making it available in the player dropdown and as a download.
