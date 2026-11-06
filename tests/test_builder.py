import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from phonomenal.builder import build_pack


class BuilderTranscriptTests(unittest.TestCase):
    def test_supplied_typography_reaches_alignment_without_losing_contractions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            audio = source / 'take.wav'
            with wave.open(str(audio), 'wb') as wav:
                wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                wav.writeframes(bytes(48000 * 2 * 4))
            (source / 'take.txt').write_text("I’m sure you’re Y'freakin' well-known!", encoding='utf-8')

            def fake_run(command, log_path=None):
                if command[-1] == 'version':
                    return 'test-aligner'
                if 'align' in command:
                    labs = list((root / 'work').rglob('*.lab'))
                    self.assertEqual(len(labs), 1)
                    self.assertEqual(labs[0].read_text(), "i'm sure you're y'freakin' well known")
                    raise RuntimeError('alignment reached')
                self.fail(f'Unexpected command: {command}')

            with patch('phonomenal.builder.run', side_effect=fake_run), \
                 patch('phonomenal.builder.shutil.which', return_value='/fake/mfa'), \
                 patch('phonomenal.builder.decode', side_effect=lambda src, dst, rate: shutil.copyfile(src, dst)):
                with self.assertRaisesRegex(RuntimeError, 'alignment reached'):
                    build_pack(source, root / 'voice.vcpack', 'test', mfa_command='test-mfa', work=root / 'work')
