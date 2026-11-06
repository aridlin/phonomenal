import importlib.util
import io
import json
import struct
from pathlib import Path
import tempfile
import unittest
import wave

import numpy as np
from phonomenal.pitch_analysis import analyse_recording, refine_pack
from phonomenal.vcpack import write_pack, extend_pack, string, _write_sections
from test_vcpack_extensions import sections
import test_vcpack


@unittest.skipUnless(importlib.util.find_spec('parselmouth'), 'Install prosody extra')
class PitchAnalysisTests(unittest.TestCase):
    def test_cli_enrichment_and_pitch_analysis_complete_as_one_new_output(self):
        import contextlib
        from phonomenal.cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root/'source.vcpack', root/'refined.vcpack'
            x = (6000*np.sin(2*np.pi*180*np.arange(16000)/16000)).astype('<i2')
            write_pack(source, voice='test', language='en', rate=16000, pcm=x.tobytes(),
                records=[dict(id='take', words=[dict(label='test', start=0, end=16000)],
                    phones=[dict(label='EH1', word=0, start=0, end=16000)])], features=False)
            original = source.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['enrich-pack', str(source), '--output', str(output), '--refine-pitch']), 0)
            self.assertEqual(source.read_bytes(), original)
            self.assertIn(b'PITC', sections(output))
            self.assertFalse(list(root.glob('.phonomenal-analysis-*')))

    def test_harmonics_do_not_replace_the_fundamental_or_pulse_clock(self):
        rate = 16000
        t = np.arange(rate) / rate
        x = .15*np.sin(2*np.pi*120*t) + .5*np.sin(2*np.pi*240*t) + .3*np.sin(2*np.pi*360*t)
        _, pitch, _, marks = analyse_recording(x, rate)
        self.assertAlmostEqual(float(np.median(pitch[pitch > 0])), 120, delta=1)
        self.assertGreater(len(marks), 80)
        self.assertAlmostEqual(rate / float(np.median(np.diff(marks))), 120, delta=1)

    def test_silence_and_unvoiced_noise_do_not_get_editable_pulses(self):
        for x in [np.zeros(16000), np.random.default_rng(8).normal(0, .08, 16000)]:
            _, _, _, marks = analyse_recording(x, 16000)
            self.assertEqual(len(marks), 0)

    def test_refinement_keeps_source_and_evidence_bytes_and_refreshes_derived_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root/'source.vcpack', root/'pitch.vcpack'
            x = (6000*np.sin(2*np.pi*180*np.arange(16000)/16000)).astype('<i2')
            records = [dict(id='take', words=[dict(label='test', start=0, end=16000)],
                phones=[dict(label='EH1', word=0, start=0, end=16000)])]
            write_pack(source, voice='test', language='en', rate=16000, pcm=x.tobytes(),
                       records=records, extra_sections={'EVID': b'untouched evidence', 'XTRA': b'future'},
                       lexicon={'test': ['EH1']})
            original = source.read_bytes()
            old = sections(source)
            refine_pack(source, output)
            new = sections(output)
            self.assertEqual(source.read_bytes(), original)
            for tag in [b'META', b'RECS', b'AUDI', b'LEXI', b'FEAT', b'ACOU', b'EVID', b'XTRA', b'SPEC']:
                self.assertEqual(old[tag], new[tag])
            before = np.frombuffer(old[b'FEAT'][1], dtype='<f4', offset=16).reshape(-1, 11)
            after = np.frombuffer(new[b'FEAT'][1], dtype='<f4', offset=16).reshape(-1, 11)
            np.testing.assert_array_equal(before[:, 2:], after[:, 2:])
            report = json.loads(new[b'QARE'][1])
            self.assertEqual(report['pitch_analysis']['version'], 1)
            self.assertIn(b'PITC', new)
            with self.assertRaises(ValueError):
                refine_pack(source, output)


class PitchMatchingTests(unittest.TestCase):
    native = test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pack = self.root/'voice.vcpack'
        rate = 16000
        self.audio, self.records = [], []
        rng = np.random.default_rng(2)
        for i, (word, hz) in enumerate([('alpha', 240), ('beta', 270), ('gamma', 240)]):
            start = i*6400
            self.audio.extend([rng.normal(0, 500, 800),
                6000*np.sin(2*np.pi*hz*np.arange(4800)/rate), rng.normal(0, 500, 800)])
            self.records.append(dict(id=word, words=[dict(label=word, start=start, end=start+6400)], phones=[
                dict(label='T', word=0, start=start, end=start+800),
                dict(label='EH1', word=0, start=start+800, end=start+5600),
                dict(label='S', word=0, start=start+5600, end=start+6400)]))
        self.audio = np.concatenate(self.audio).astype('<i2')
        self.write()

    def write(self, features=True):
        write_pack(self.pack, voice='synthetic', language='en', rate=16000,
                   pcm=self.audio.tobytes(), records=self.records, features=features)

    def render(self, text, *args):
        result = self.native('--text', text, '--stdout-wav', *args)
        with wave.open(io.BytesIO(result.stdout), 'rb') as f:
            return np.frombuffer(f.readframes(f.getnframes()), dtype='<i2')

    def test_matching_reduces_known_pitch_jump_without_changing_consonants_or_duration(self):
        report = self.root/'audit.json'
        before = self.render('alpha beta gamma')
        after = self.render('alpha beta gamma', '--match-pitch', '--audit', str(report))
        self.assertEqual(len(before), len(after))
        audit = json.loads(report.read_text())
        edits = audit['pitch_adjustments']
        self.assertGreater(len(edits), 0)
        self.assertTrue(all(e['mode'] == 'match' for e in edits))
        self.assertTrue(all(abs(12*np.log2(e['factor'])) <= 1.5001 for e in edits))
        # Compare the actual output clock, including inserted word pauses.
        starts = [b['output_sample'] for b in audit['boundaries'] if b['kind']=='splice' and b['edge']=='start']
        for start in starts:
            np.testing.assert_array_equal(after[start:start+800], before[start:start+800])
            np.testing.assert_array_equal(after[start+5600:start+6400], before[start+5600:start+6400])
        middle = after[starts[1]+1800:starts[1]+4600]
        measured = np.fft.rfftfreq(len(middle), 1/16000)[np.abs(np.fft.rfft(middle*np.hanning(len(middle)))).argmax()]
        self.assertAlmostEqual(measured, np.sqrt(240*270), delta=6)

    def test_standalone_phrase_and_old_packs_are_not_shifted(self):
        self.assertEqual(self.render('alpha').tobytes(), self.render('alpha', '--match-pitch').tobytes())
        self.write(features=False)
        self.assertEqual(self.render('alpha beta gamma').tobytes(), self.render('alpha beta gamma', '--match-pitch').tobytes())

    def add_editing_evidence(self):
        data = bytearray(struct.pack('<II', 1, len(self.records)))
        for record in self.records:
            data += string(record['id']) + struct.pack('<I', len(record['phones']))
            for _ in record['phones']:
                data += struct.pack('<3fI', 400., 0., 1., 0)
        extend_pack(self.pack, {'PITC': bytes(data)})

    def test_render_evidence_cannot_change_planning_or_plain_audio(self):
        before = self.render('alpha beta gamma')
        plan = self.native('--text', 'alpha beta gamma', '--plan').stdout
        self.add_editing_evidence()
        self.assertEqual(before.tobytes(), self.render('alpha beta gamma').tobytes())
        self.assertEqual(plan, self.native('--text', 'alpha beta gamma', '--plan').stdout)

    def test_known_bad_pitch_section_is_rejected_and_future_version_is_ignored(self):
        self.add_editing_evidence()
        payloads = sections(self.pack)
        pitch = bytearray(payloads[b'PITC'][1])
        struct.pack_into('<f', pitch, 8+4+len('alpha')+4, float('nan'))
        _write_sections(self.pack, [(t, flags, bytes(pitch) if t==b'PITC' else data) for t,(flags,data) in payloads.items()])
        self.assertNotEqual(self.native('--inspect', check=False).returncode, 0)
        struct.pack_into('<I', pitch, 0, 999)
        _write_sections(self.pack, [(t, flags, bytes(pitch) if t==b'PITC' else data) for t,(flags,data) in payloads.items()])
        self.native('--inspect')

    def test_editor_invalidates_pitch_evidence_when_saving_source_edits(self):
        from phonomenal.pack_editor import open_project, save_project
        self.add_editing_evidence()
        project = self.root/'edit'
        open_project(self.pack, project)
        path = project/'record-000000.json'
        record = json.loads(path.read_text())
        record['phones'][1]['label'] = 'AA1'
        path.write_text(json.dumps(record))
        output = self.root/'edited.vcpack'
        save_project(project, output)
        self.assertNotIn(b'PITC', sections(output))


if __name__ == '__main__':
    unittest.main()
