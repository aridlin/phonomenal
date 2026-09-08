# Phonomenal channel reader

Copy `phonomenalReader` into Vencord or Equicord's `src/userplugins`, build the
client mod, restart Discord/Vesktop, and enable **PhonomenalReader** in Plugins.
The speaker button beside the message box toggles the currently selected channel.
It starts off, reads only new incoming messages, and stops on channel changes.
Speech plays locally; the plugin sends no messages and uploads no message text.

Set the Phonomenal project/release directory in plugin settings. It must contain
`data/packages/*.vcpack` and the C++ player in `bin`, `cpp/build-vcpack`, `cpp/build`,
or its root. A blank path checks `PHONOMENAL_HOME`, then
`~/dev/codexp/phonomenal`.

## Firefox

Vencord's current supported Firefox route is the signed Tampermonkey extension
and a userscript: https://vencord.dev/download/. Build `pnpm buildWeb` after
copying this plugin into `src/userplugins`, and add `// @connect 127.0.0.1` to
`browser/userscript.meta.js` before building. The plugin is available by default
in browser builds; channel reading still starts off.

Run the local player bridge with Python 3 (no speech-recognition models needed):

```sh
PYTHONPATH=src python3 -m phonomenal.browser_bridge --root "$PWD"
```

It binds only `127.0.0.1:18774` and creates a private pairing key at
`~/.config/phonomenal/browser-token`. Install your custom `dist/Vencord.user.js`
in Tampermonkey and copy this key into PhonomenalReader's Firefox pairing setting.
Keep paired userscripts and keys local. A local paired installer may set that
setting automatically; it must not be published with the public source.

The bridge accepts only available pack basenames and bounded speech text, passes
text to the C++ player's stdin, and returns a WAV. It does not accept arbitrary
executables or filesystem paths. Browser tabs have separate cancellation IDs.
Tampermonkey's privileged local request avoids Discord's page CSP; no message
text or generated audio is sent to a remote speech service. Keep the bridge
running while using the browser reader.

Set `USER_ID=medic.vcpack`, one entry per line, for overrides. Otherwise a stable
hash of user ID and pack filename chooses a voice. The optional comma-separated
voice pool limits these automatic choices. Volume is configurable. Playback is
sequential, long messages split into bounded parts, history/reconnect replays are
ignored, and a full queue produces a visible notice. Disabling stops both queued
speech and the running native process.

The integration is GPL-3.0-or-later, matching Vencord's plugin ecosystem.
