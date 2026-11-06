import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

import numpy as np
from phonomenal.vcpack import write_pack
import test_vcpack


class JoinTimingTests(unittest.TestCase):
    native = test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pack = self.root/'voice.vcpack'
        # A 2 ms consonant followed by a vowel from a different recording.
        self.audio = np.concatenate([np.ones(32)*12000,
            np.sin(np.arange(1600)*2*np.pi*180/16000)*5000]).astype('<i2')
        self.records = [dict(id=name, words=[dict(label=name, start=lo, end=hi)],
            phones=[dict(label=phone, word=0, start=lo, end=hi)])
            for name, phone, lo, hi in [('first', 'K', 0, 32), ('second', 'AA1', 32, 1632)]]
        self.write()

    def write(self):
        write_pack(self.pack, voice='test', language='en', rate=16000,
                   pcm=self.audio.tobytes(), records=self.records, features=False)

    def render(self, *args):
        audit = self.root/'audit.json'
        result = self.native('--phones', 'K AA', '--stdout-wav', '--audit', str(audit), *args)
        with wave.open(io.BytesIO(result.stdout), 'rb') as f:
            audio = np.frombuffer(f.readframes(f.getnframes()), dtype='<i2')
        return audio, json.loads(audit.read_text())

    def test_legacy_overlap_cannot_erase_a_short_previous_consonant(self):
        output, audit = self.render('--legacy-overlap')
        self.assertEqual(len(output), len(self.audio)-8)
        np.testing.assert_array_equal(output[:24], self.audio[:24])
        self.assertEqual(audit['overlap_samples_removed'], 8)

    def test_preserving_join_retains_every_planned_sample_and_boundary_clock(self):
        output, audit = self.render('--preserve-phone-timing')
        self.assertEqual(len(output), len(self.audio))
        np.testing.assert_array_equal(output[:28], self.audio[:28])
        self.assertEqual(audit['overlap_samples_removed'], 0)
        self.assertEqual(audit['duration_preserving_joins'], 1)
        self.assertEqual(audit['contextual_joins'], 0)
        edges = [(b['edge'], b['output_sample']) for b in audit['boundaries'] if b['kind']=='splice']
        self.assertEqual(edges, [('start', 0), ('end', 32), ('start', 32), ('end', 1632)])

    def test_context_join_stays_within_recording_and_does_not_shorten_sound(self):
        self.audio = np.arange(6400, dtype='<i2')
        self.records = [dict(id=name, words=[dict(label=name, start=lo, end=hi)], phones=[
            dict(label='T', word=0, start=lo, end=start),
            dict(label=phone, word=0, start=start, end=end),
            dict(label='S', word=0, start=end, end=hi)])
            for name, phone, lo, start, end, hi in [('first', 'K', 0, 800, 832, 1632),
                                                  ('second', 'AA1', 3200, 4000, 5600, 6400)]]
        self.write()
        output, audit = self.render('--preserve-phone-timing')
        self.assertEqual(len(output), 32+1600)
        self.assertEqual(audit['contextual_joins'], 1)
        np.testing.assert_array_equal(output[:28], self.audio[800:828])
        np.testing.assert_array_equal(output[36:], self.audio[4004:5600])
        self.assertTrue(np.all((output[28:36]>=self.audio[828]) & (output[28:36]<=self.audio[4003])))

    def test_contiguous_audio_is_not_crossfaded_or_changed(self):
        self.records = [dict(id='continuous', words=[dict(label='word', start=0, end=1632)],
                            phones=[dict(label='K', word=0, start=0, end=32),
                                    dict(label='AA1', word=0, start=32, end=1632)])]
        self.write()
        output, audit = self.render('--preserve-phone-timing')
        np.testing.assert_array_equal(output, self.audio)
        self.assertEqual(audit['duration_preserving_joins'], 0)


if __name__ == '__main__':
    unittest.main()
