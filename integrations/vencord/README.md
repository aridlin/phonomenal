# Phonomenal channel reader

Copy `phonomenalReader` into Vencord or Equicord's `src/userplugins`, build the
client mod, restart Discord/Vesktop, and enable **PhonomenalReader** in Plugins.
The speaker button beside the message box toggles the currently selected channel.
It starts off, reads only new incoming messages, and stops on channel changes.
Speech plays locally; the plugin sends no messages and uploads no message text.

Set the Phonomenal project/release directory in plugin settings. It must contain
`data/packages/*.vcpack` and the C++ player in `bin`, `cpp/build-vcpack`, `cpp/build`,
or its root. A blank path checks `PHONOMENAL_HOME`, then
`~/dev/codexp/phonomenal`. Desktop native helpers are required; browser-only
Vencord cannot launch a local binary.

Set `USER_ID=medic.vcpack`, one entry per line, for overrides. Otherwise a stable
hash of user ID and pack filename chooses a voice. The optional comma-separated
voice pool limits these automatic choices. Volume is configurable. Playback is
sequential, long messages split into bounded parts, history/reconnect replays are
ignored, and a full queue produces a visible notice. Disabling stops both queued
speech and the running native process.

The integration is GPL-3.0-or-later, matching Vencord's plugin ecosystem.
