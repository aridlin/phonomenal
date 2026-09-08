import unittest
from phonomenal.speech_check import compare_words

class SpeechCheckTests(unittest.TestCase):
    def test_case_and_punctuation_do_not_count_as_word_errors(self):
        self.assertTrue(compare_words('I hate getting homework!', 'i hate getting homework.')['words_match'])

    def test_reports_mangled_word(self):
        result=compare_words('I hate getting homework','I hate getting home')
        self.assertEqual(result['word_error_rate'], .25)
        self.assertEqual(result['differences'],[dict(operation='substitution',expected='homework',heard='home')])

    def test_compound_spacing_is_reported_without_hiding_raw_errors(self):
        result=compare_words('I hate getting homework', 'I hate getting home work')
        self.assertTrue(result['spacing_only_difference'])
        self.assertFalse(result['words_match'])
        self.assertEqual(result['word_error_rate'], .5)

    def test_silence_counts_every_missing_word(self):
        result=compare_words('getting homework','')
        self.assertEqual(result['word_error_rate'],1.)
        self.assertEqual(len(result['differences']),2)

    def test_insertions_can_exceed_one_hundred_percent(self):
        self.assertEqual(compare_words('hello','hello a b c')['word_error_rate'],3.)

    def test_recognition_is_not_seeded_with_requested_sentence(self):
        from types import SimpleNamespace
        from phonomenal.speech_check import verify_speech
        class Recognizer:
            def transcribe(self, audio, **options):
                self.options=options
                return iter([SimpleNamespace(text='wrong words',words=[])]),None
        recognizer=Recognizer()
        result=verify_speech('unused.wav','I hate getting homework',recognizer=recognizer)
        self.assertFalse(result['words_match'])
        self.assertEqual(result['recognized'],'wrong words')
        self.assertNotIn('initial_prompt',recognizer.options)
        self.assertNotIn('hotwords',recognizer.options)
