import json
from pathlib import Path
import struct
import tempfile
import unittest
from phonomenal.vcpack import DIRECTORY, HEADER, extend_pack, inspect_pack, write_pack
import test_vcpack


def sections(path):
    raw = path.read_bytes()
    count = HEADER.unpack_from(raw)[2]
    result = {}
    for i in range(count):
        tag, flags, offset, length, crc, reserved = DIRECTORY.unpack_from(raw, 24+32*i)
        result[tag] = (flags, raw[offset:offset+length])
    return result


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pack = Path(self.tmp.name)/'voice.vcpack'
        test_vcpack.fixture(self.pack)

    native = test_vcpack.VcpackTests.native

    def test_manual_is_literal_ascii_at_eof(self):
        specification = Path('src/phonomenal/vcpack_spec.txt').read_bytes()
        specification.decode('ascii')
        self.assertTrue(self.pack.read_bytes().endswith(specification))
        self.assertEqual(list(sections(self.pack))[-1], b'SPEC')
        self.assertEqual(sections(self.pack)[b'SPEC'][0], 0)
        self.native('--inspect')

    def test_addition_preserves_every_payload_and_native_plan(self):
        old = sections(self.pack)
        plan = json.loads(self.native('--text', 'alpha beta', '--plan').stdout)
        extend_pack(self.pack, {'XTRA': b'\x00\xfffuture data'})
        current = sections(self.pack)
        for tag, payload in old.items():
            self.assertEqual(current[tag], payload)
        self.assertEqual(current[b'XTRA'], (0, b'\x00\xfffuture data'))
        self.assertEqual(list(current)[-1], b'SPEC')
        self.assertEqual(json.loads(self.native('--text', 'alpha beta', '--plan').stdout), plan)
        inspect_pack(self.pack)
        extend_pack(self.pack, {'NEXT': b'more'})
        self.assertEqual(sections(self.pack)[b'XTRA'], current[b'XTRA'])

    def test_unknown_required_is_rejected_by_both_readers(self):
        extend_pack(self.pack, {'XTRA': b'future data'})
        raw = bytearray(self.pack.read_bytes())
        index = list(sections(self.pack)).index(b'XTRA')
        struct.pack_into('<I', raw, 24+32*index+4, 1)
        self.pack.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'Unknown required'):
            inspect_pack(self.pack)
        self.assertNotEqual(self.native('--inspect', check=False).returncode, 0)

    def test_corrupt_unknown_optional_payload_is_rejected(self):
        extend_pack(self.pack, {'XTRA': b'future data'})
        raw = bytearray(self.pack.read_bytes())
        index = list(sections(self.pack)).index(b'XTRA')
        offset = DIRECTORY.unpack_from(raw, 24+32*index)[2]
        raw[offset] ^= 1
        self.pack.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            inspect_pack(self.pack)
        self.assertNotEqual(self.native('--inspect', check=False).returncode, 0)

    def test_failed_extension_leaves_original_untouched(self):
        original = self.pack.read_bytes()
        for extra in ({'META': b'x'}, {'TOOLONG': b'x'}, {'XTRA': 'not bytes'},
                      {f'{i:04}': b'x' for i in range(26)}):
            with self.assertRaises(ValueError):
                extend_pack(self.pack, extra)
            self.assertEqual(self.pack.read_bytes(), original)
        extend_pack(self.pack, {'XTRA': b'first'})
        extended = self.pack.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            extend_pack(self.pack, {'XTRA': b'second'})
        self.assertEqual(self.pack.read_bytes(), extended)

    def test_new_writer_accepts_optional_extension(self):
        write_pack(self.pack, voice='voice', language='en', rate=48000,
                   pcm=b'\x00\x00'*4800,
                   records=[dict(id='one', words=[dict(label='a', start=0, end=4800)],
                                 phones=[dict(label='AH1', word=0, start=0, end=4800)])],
                   features=False, extra_sections={'XTRA': b'opaque'})
        self.assertEqual(sections(self.pack)[b'XTRA'], (0, b'opaque'))
        self.native('--inspect')
