import json
from pathlib import Path
import struct
import tempfile
import unittest

from phonomenal.repair_lexicon import repair_lexicon
from phonomenal.pack_editor import read_pack
from phonomenal.vcpack import write_pack, string
import test_vcpack
from test_vcpack_extensions import sections


class IntelligibilityTests(unittest.TestCase):
    native = test_vcpack.VcpackTests.native

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pack = Path(self.tmp.name) / 'original.vcpack'

    def write(self, records, **kwargs):
        write_pack(self.pack, voice='test', language='en-us', rate=16000,
                   pcm=struct.pack('<h', 1000) * 20000, records=records,
                   features=False, **kwargs)

    def test_short_internal_vowel_does_not_destroy_an_intact_word(self):
        # A plausible fast vowel may have an uncertain internal boundary.
        # Copying the intact word exposes none of those internal cuts.
        records = [dict(id='intact', words=[dict(label='cat', start=0, end=2400)], phones=[
            dict(label='K', word=0, start=0, end=800),
            dict(label='AE1', word=0, start=800, end=1360),
            dict(label='T', word=0, start=1360, end=2400)])]
        cursor = 4000
        for i, label in enumerate(['K', 'AE1', 'T']):
            records.append(dict(id=f'piece-{i}', words=[dict(label=f'other{i}', start=cursor, end=cursor+2000)],
                phones=[dict(label=label, word=0, start=cursor, end=cursor+2000)]))
            cursor += 3000
        self.write(records, lexicon={'cat': ['K', 'AE1', 'T']})
        plan = json.loads(self.native('--text', 'cat', '--plan').stdout)
        self.assertEqual([u['clip_id'] for u in plan['units']], ['intact'])
        # Strict mode still enforces the original duration rejection.
        strict = json.loads(self.native('--text', 'cat', '--strict', '--plan').stdout)
        self.assertNotIn('intact', [u['clip_id'] for u in strict['units']])

    def test_independently_disputed_source_does_not_beat_supported_sound(self):
        records = [dict(id=name, words=[dict(label='same', start=start, end=start+2000)],
                        phones=[dict(label='AH1', word=0, start=start, end=start+2000)])
                   for name, start in [('wrong-label', 0), ('supported', 4000)]]
        trust = struct.pack('<II', 1, 2)
        # A phone recognizer's disagreement must not outweigh both word
        # recognizers rejecting the other source's transcript entirely.
        for name, support, dispute, phone_dispute in [('wrong-label', 0, 2, 0), ('supported', 2, 0, 2)]:
            trust += string(name) + struct.pack('<I5I', 1, 0, phone_dispute, support, dispute, 0)
        self.write(records, lexicon={'unseen': ['AH1']}, extra_sections={'TRST': trust})
        plan = json.loads(self.native('--text', 'unseen', '--plan').stdout)
        self.assertEqual([u['clip_id'] for u in plan['units']], ['supported'])

    def test_repair_preserves_source_evidence_unknown_names_and_valid_variants(self):
        records = [dict(id='take', words=[dict(label='hate', start=0, end=2000)],
                        phones=[dict(label='EY1', word=0, start=0, end=2000)])]
        self.write(records, lexicon={'hate': ['HH', 'EY1'], 'either': ['IY1', 'DH', 'ER0'],
                                    'username': ['Z', 'UW1']}, extra_sections={'XTRA': b'opaque'})
        original = self.pack.read_bytes()
        old = sections(self.pack)
        target = self.pack.with_name('repaired.vcpack')
        report = repair_lexicon(self.pack, target, dictionary={
            'hate': [['HH', 'EY1', 'T']],
            'either': [['AY1', 'DH', 'ER0'], ['IY1', 'DH', 'ER0']]})
        self.assertEqual([c['word'] for c in report['changes']], ['hate'])
        lex = read_pack(target)[2]
        self.assertEqual(lex['hate'], ['HH', 'EY1', 'T'])
        self.assertEqual(lex['either'], ['IY1', 'DH', 'ER0'])
        self.assertEqual(lex['username'], ['Z', 'UW1'])
        self.assertEqual(self.pack.read_bytes(), original)
        updated = sections(target)
        for tag in [b'META', b'RECS', b'AUDI', b'XTRA', b'SPEC']:
            self.assertEqual(updated[tag], old[tag])
        self.pack = target
        self.native('--inspect')
        with self.assertRaises(ValueError):
            repair_lexicon(target, target)


if __name__ == '__main__':
    unittest.main()
