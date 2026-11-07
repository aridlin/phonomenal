"""Exercise actual C++ conversion fixtures on both native CI platforms."""
import subprocess
import unittest
import test_vcpack


class NativePronunciationTests(unittest.TestCase):
    def test_supported_ipa_stress_and_unknown_phone_handling(self):
        cli=test_vcpack.CLI
        fixture=cli.with_name('phonomenal_pronunciation_test'+cli.suffix)
        if not fixture.exists():
            self.skipTest('Build with PHONOMENAL_BUILD_TESTS=ON to run native parser fixtures')
        subprocess.run([str(fixture)],capture_output=True,check=True)
