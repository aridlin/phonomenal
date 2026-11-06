import json
from pathlib import Path
import tempfile
import unittest

import test_vcpack


class TextInputTests(unittest.TestCase):
    native = test_vcpack.VcpackTests.native
    write_phone_choices = test_vcpack.VcpackTests.write_phone_choices

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pack = Path(self.tmp.name)/'voice.vcpack'
        self.write_phone_choices([
            ("don't", ['AA1'], [.15]), ("can't", ['B'], [.08]),
            ('alpha', ['AA1', 'B'], [.15, .08])],
            {'one': ['AA1'], 'two': ['B'], 'and': ['AA1']})

    def plan(self, text):
        return json.loads(self.native('--text', text, '--plan').stdout)

    def test_curly_apostrophes_and_quotes_preserve_contractions(self):
        ascii_plan = self.plan("'don't' ... \"can't\"")
        unicode_plan = self.plan('‘don’t’ … “can’t”')
        self.assertEqual(unicode_plan, ascii_plan)
        self.assertEqual(unicode_plan['normalized_text'], "don't can't")
        self.assertEqual(unicode_plan['units'][1]['pause_before_ms'], 180)

    def test_unicode_bank_output_and_audit_paths(self):
        target = self.pack.with_name('głos-żąółć.vcpack')
        self.pack.rename(target)
        self.pack = target
        output = self.pack.with_name('mowa-Ω.wav')
        audit = self.pack.with_name('granice-ąć.json')
        result = self.native('--text', 'alpha', '--output', str(output), '--audit', str(audit), '--plan')
        self.assertEqual(json.loads(result.stdout)['normalized_text'], 'alpha')
        self.assertTrue(output.read_bytes().startswith(b'RIFF'))
        self.assertGreater(json.loads(audit.read_text())['boundaries_checked'], 0)

    def test_digit_expansion_keeps_the_following_pause_on_the_right_word(self):
        plan = self.plan('12, alpha')
        self.assertEqual(plan['normalized_text'], 'one two alpha')
        pauses = [(u['target_text'], u['pause_before_ms']) for u in plan['units'] if u['pause_before_ms']]
        self.assertEqual(pauses, [('alpha', 90)])

    def test_ampersand_counts_as_a_spoken_word_before_punctuation(self):
        plan = self.plan("don't & can't. alpha")
        self.assertEqual(plan['normalized_text'], "don't and can't alpha")
        pauses = [(u['target_text'], u['pause_before_ms']) for u in plan['units'] if u['pause_before_ms']]
        self.assertEqual(pauses, [('alpha', 180)])

    def test_paragraph_breaks_preserve_one_pause_and_crlf_matches_lf(self):
        for text in ['alpha.\n\nalpha', 'alpha.\r\n\r\nalpha', 'alpha.\n \nalpha']:
            plan = self.plan(text)
            self.assertEqual([u['pause_before_ms'] for u in plan['units']], [0, 300])
        self.assertEqual(self.plan('alpha\nalpha')['units'][-1]['pause_before_ms'], 0)

    def test_typographic_dash_adds_a_pause_and_nonbreaking_hyphen_does_not(self):
        self.assertEqual(self.plan('alpha—alpha')['units'][-1]['pause_before_ms'], 90)
        self.assertEqual(self.plan('alpha‑alpha')['units'][-1]['pause_before_ms'], 0)
        self.assertEqual(self.plan('\ufeffalpha\u00a0alpha'), self.plan('alpha alpha'))


if __name__ == '__main__':
    unittest.main()
