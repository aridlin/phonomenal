"""Run internal envelope signal checks through the native test binary."""
import subprocess
import unittest
import test_vcpack


class NativeSpectralJoinTests(unittest.TestCase):
    def test_signal_guards_and_envelope_identity(self):
        cli = test_vcpack.CLI
        fixture = cli.with_name('phonomenal_spectral_join_test' + cli.suffix)
        if not fixture.exists():
            self.skipTest('Build with PHONOMENAL_BUILD_TESTS=ON for spectral signal fixtures')
        subprocess.run([str(fixture)], capture_output=True, check=True)


class SpectralPlannerTests(unittest.TestCase):
    native = test_vcpack.VcpackTests.native

    def setUp(self):
        import tempfile
        from pathlib import Path
        import numpy as np
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pack = Path(self.tmp.name) / 'voice.vcpack'
        phase = np.arange(10000) * 2 * np.pi * 200 / 16000
        self.audio = (5000 * (np.sin(phase) + .5*np.sin(3*phase) + .25*np.sin(7*phase))).astype('<i2')
        self.different = (5000 * (.25*np.sin(phase) + .5*np.sin(3*phase) + np.sin(7*phase))).astype('<i2')
        self.records = [dict(id='left', words=[dict(label='leftword',start=0,end=3840)],phones=[
            dict(label='K',word=0,start=0,end=960),dict(label='AA1',word=0,start=960,end=3840)]),
            dict(id='right',words=[dict(label='rightword',start=4800,end=8640)],phones=[
            dict(label='AA1',word=0,start=4800,end=7680),dict(label='T',word=0,start=7680,end=8640)])]
        self.write()

    def write(self):
        from phonomenal.vcpack import write_pack
        write_pack(self.pack,voice='test',language='en',rate=16000,pcm=self.audio.tobytes(),
                   records=self.records,features=False)

    def plan(self, *args):
        import json
        return json.loads(self.native('--phones','K AA1 T','--plan',*args).stdout)

    def test_fine_comparison_distinguishes_same_pitch_different_envelopes(self):
        matching = self.plan('--spectral-joins')
        coarse_matching = self.plan()
        self.audio[4800:8640] = self.different[4800:8640]
        self.write()
        mismatch = self.plan('--spectral-joins')
        coarse_mismatch = self.plan()
        # Isolate spectral evidence from any small RMS/pitch estimator change.
        fine_delta = mismatch['score'] - matching['score']
        old_delta = coarse_mismatch['score'] - coarse_matching['score']
        self.assertGreater(fine_delta - old_delta, 1.)
        self.assertEqual(matching['units'], mismatch['units'])

    def test_full_recorded_word_keeps_identical_plan_and_pcm(self):
        self.assertEqual(self.native('--text','leftword','--plan','--stdout-wav').stdout,
                         self.native('--text','leftword','--plan','--stdout-wav','--spectral-joins').stdout)
        self.assertEqual(self.native('--text','leftword','--plan').stdout,
                         self.native('--text','leftword','--plan','--spectral-joins').stdout)

    def test_noncenter_joins_keep_identical_plan_and_pcm(self):
        self.assertEqual(self.plan('--boundary-phone-joins'),
                         self.plan('--boundary-phone-joins','--spectral-joins'))

    def test_no_window_beyond_short_source_vowel(self):
        self.records[0]['phones'][1]['start'] = 3520
        self.write()
        self.assertEqual(self.plan(), self.plan('--spectral-joins'))
