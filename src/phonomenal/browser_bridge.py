"""Authenticated loopback bridge for the browser channel reader.

The browser can select a pack and submit speech, but cannot select executables,
read arbitrary files or upload audio. Message text is passed through stdin.
"""
from __future__ import annotations
import argparse
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import threading


class Bridge:
    def __init__(self, root, token, userscript=None):
        self.root = Path(root).resolve()
        self.token = token
        self.userscript = Path(userscript) if userscript else None
        self.packs = self.root / 'data/packages'
        name = 'phonomenal_splicer_cli' + ('.exe' if os.name == 'nt' else '')
        candidates = [self.root / p / name for p in ('cpp/build-vcpack',
                      'cpp/build', 'cpp/build/Release', 'bin', '.')]
        self.cli = next((p for p in candidates if p.is_file()), None)
        if not self.cli:
            raise ValueError('Build the Phonomenal C++ player first.')
        self.lock = threading.Lock()
        self.jobs = {}
        self.versions = {}
        self.slots = threading.BoundedSemaphore(4)

    def voices(self):
        return sorted(p.name for p in self.packs.glob('*.vcpack')
                      if p.is_file() and not any(s in p.stem.lower() for s in ('legacy', '-test', '-core', '-refined')))

    def cancel(self, client):
        with self.lock:
            self.versions[client] = self.versions.get(client, 0) + 1
            child = self.jobs.pop(client, None)
            if child and child.poll() is None:
                child.terminate()

    def synthesize(self, client, voice, text):
        with self.lock:
            version = self.versions.get(client, 0)
        if not isinstance(voice, str) or voice not in self.voices():
            raise ValueError('Unknown voice pack.')
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError('Speech must contain 1–2000 characters.')
        if not self.slots.acquire(blocking=False):
            raise ValueError('The local player is busy. Try again shortly.')
        child = None
        try:
            with tempfile.TemporaryDirectory(prefix='phonomenal-browser-') as directory:
                output = Path(directory) / 'speech.wav'
                with (Path(directory) / 'error.log').open('w+b') as errors:
                    with self.lock:
                        if version != self.versions.get(client, 0):
                            raise ValueError('Speech generation cancelled.')
                        previous = self.jobs.pop(client, None)
                        if previous and previous.poll() is None:
                            previous.terminate()
                        child = subprocess.Popen([str(self.cli), '--bank', str(self.packs / voice),
                            '--stdin', '--output', str(output)], stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=errors)
                        self.jobs[client] = child
                    try:
                        child.communicate((text + '\n').encode(), timeout=60)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait()
                        raise ValueError('Speech generation timed out.')
                    if child.returncode:
                        errors.seek(0, 2); errors.seek(max(0, errors.tell() - 2000))
                        raise ValueError(errors.read().decode(errors='replace') or 'Speech generation cancelled.')
                if output.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError('Generated audio exceeds 32 MiB.')
                wav = output.read_bytes()
                if wav[:4] != b'RIFF' or wav[8:12] != b'WAVE':
                    raise ValueError('Invalid player output.')
                return base64.b64encode(wav).decode('ascii')
        finally:
            with self.lock:
                if child is not None and self.jobs.get(client) is child:
                    del self.jobs[client]
            self.slots.release()


def handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass  # Do not log messages, pairing URLs, or authorization headers.

        def reply(self, status, value, mime='application/json'):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            origin = self.headers.get('Origin', '')
            if origin in ('https://discord.com', 'https://ptb.discord.com', 'https://canary.discord.com'):
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, X-Phonomenal-Client')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            host = self.headers.get('Host', '').split(':')[0]
            if host not in ('127.0.0.1', 'localhost'):
                self.reply(403, {'error': 'Loopback host required.'}); return False
            expected = 'Bearer ' + bridge.token
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected.encode()):
                self.reply(401, {'error': 'Pair this browser with the local Phonomenal bridge.'}); return False
            return True

        def do_OPTIONS(self):
            self.reply(204, b'')

        def do_GET(self):
            # This unguessable URL is used only for the local userscript install.
            # It is never published or included in the public repository.
            install = '/' + bridge.token + '/Phonomenal.user.js'
            if bridge.userscript and hmac.compare_digest(self.path.encode(), install.encode()):
                if self.headers.get('Host', '').split(':')[0] not in ('127.0.0.1', 'localhost'):
                    self.reply(403, {'error': 'Loopback host required.'}); return
                self.reply(200, bridge.userscript.read_bytes(), 'text/javascript; charset=utf-8'); return
            if not self.authorized(): return
            if self.path == '/voices': self.reply(200, bridge.voices())
            else: self.reply(404, {'error': 'Unknown endpoint.'})

        def do_POST(self):
            if not self.authorized(): return
            client = self.headers.get('X-Phonomenal-Client', '')
            if not re.fullmatch(r'[a-f0-9]{32}', client):
                self.reply(400, {'error': 'Invalid client identifier.'}); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384: raise ValueError('Invalid request size.')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict): raise ValueError('Expected a JSON object.')
                if self.path == '/cancel':
                    bridge.cancel(client); self.reply(200, {'cancelled': True})
                elif self.path == '/synthesize':
                    self.reply(200, {'wav': bridge.synthesize(client, body.get('voice'), body.get('text'))})
                else: self.reply(404, {'error': 'Unknown endpoint.'})
            except (ValueError, OSError) as error:
                self.reply(400, {'error': str(error)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18774)
    parser.add_argument('--token-file', type=Path, default=Path.home()/'.config/phonomenal/browser-token')
    parser.add_argument('--userscript', type=Path)
    args = parser.parse_args()
    args.token_file.parent.mkdir(parents=True, exist_ok=True)
    if not args.token_file.exists():
        with os.fdopen(os.open(args.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
            file.write(secrets.token_hex(32) + '\n')
    token = args.token_file.read_text().strip()
    if not re.fullmatch('[a-f0-9]{64}', token): raise ValueError('Invalid bridge token file.')
    bridge = Bridge(args.root, token, args.userscript)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(bridge))
    print(f'Phonomenal browser bridge listening on 127.0.0.1:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__': main()
