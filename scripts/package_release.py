#!/usr/bin/env python3
"""Package only tracked public source and named CI binaries; never local voices."""
import argparse
import hashlib
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(artifacts: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    results = []
    for platform in ('Linux', 'Windows'):
        name = f'phonomenal-generator-and-player-{platform.lower()}-x86_64'
        stage = destination / name
        stage.mkdir()
        for name_in_repo in tracked:
            if not name_in_repo:
                continue
            path = Path(name_in_repo)
            if path.parts[0] not in ('src', 'scripts', 'examples', 'docs') and name_in_repo not in ('README.md', 'LICENSE', 'pyproject.toml'):
                continue
            if path.suffix == '.pyc' or '__pycache__' in path.parts:
                raise RuntimeError('Unexpected cache in tracked release input')
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, target)
        windows = platform == 'Windows'
        suffix = '.exe' if windows else ''
        build = artifacts / f'phonomenal-{platform}' / 'cpp/build'
        if windows:
            build /= 'Release'
        (stage / 'bin').mkdir()
        for binary in ('phonomenal_splicer_cli', 'phonomenal_splicer_frontend'):
            out = stage / 'bin' / (binary + suffix)
            shutil.copy2(build / (binary + suffix), out)
            out.chmod(0o755)
        for title, mode in (('Generator', 'builder'), ('TTS Player', 'player')):
            if windows:
                (stage / f'{title}.cmd').write_text(f'@echo off\ncd /d "%~dp0"\nstart "" "bin\\phonomenal_splicer_frontend.exe" --{mode} %*\n')
            else:
                launcher = stage / (title.lower().replace(' ', '-') + '.sh')
                launcher.write_text(f'#!/bin/sh\nset -eu\ncd -- "$(dirname -- "$0")"\nexec ./bin/phonomenal_splicer_frontend --{mode} "$@"\n')
                launcher.chmod(0o755)
        shutil.copy2(ROOT / 'docs/TEST_BUILD.md', stage / 'START-HERE.md')
        if windows:
            archive = Path(shutil.make_archive(str(stage), 'zip', destination, stage.name))
        else:
            archive = destination / (stage.name + '.tar.gz')
            with tarfile.open(archive, 'w:gz') as tar:
                tar.add(stage, arcname=stage.name)
        results.append(archive)
    overlay = destination / 'phonomenal-vctts-windows-x86_64'
    overlay.mkdir()
    shutil.copy2(artifacts / 'phonomenal-Windows/vctts/build/Release/tts_overlay.exe', overlay)
    shutil.copy2(ROOT / 'LICENSE', overlay)
    shutil.copy2(ROOT / 'docs/THIRD_PARTY.md', overlay)
    shutil.copytree(ROOT / 'docs/licenses', overlay / 'licenses')
    (overlay / 'START-HERE.txt').write_text('Run tts_overlay.exe. Select the Phonomenal engine and set its package directory to your .vcpack folder. The generator/player are in the companion release download. TF2 voice assets are supplied locally.\n')
    results.append(Path(shutil.make_archive(str(overlay), 'zip', destination, overlay.name)))
    checksum = destination / 'SHA256SUMS.txt'
    checksum.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in results))
    print('\n'.join(str(p) for p in [*results, checksum]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Fresh output directory')
    args = parser.parse_args()
    package(args.artifacts.resolve(), args.output.resolve())
