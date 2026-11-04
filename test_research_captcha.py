import struct
import unittest
import zlib

import research_captcha as captcha
from research_captcha import ALPHABET, LENGTH, CaptchaStore, new_code, render_png


def decode_png(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos, chunks = 8, {}
    while pos < len(data):
        size, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + size]
        crc = struct.unpack('>I', data[pos + 8 + size:pos + 12 + size])[0]
        assert zlib.crc32(kind + body) & 0xffffffff == crc
        chunks.setdefault(kind, b'')
        chunks[kind] += body
        pos += 12 + size
    width, height, depth, color = struct.unpack('>IIBB', chunks[b'IHDR'][:10])
    return width, height, depth, color, zlib.decompress(chunks[b'IDAT'])


class CaptchaImageTests(unittest.TestCase):
    def test_codes_are_six_unambiguous_characters(self):
        for _ in range(200):
            code = new_code()
            self.assertEqual(len(code), LENGTH)
            self.assertTrue(set(code) <= set(ALPHABET))
        self.assertFalse(set('0O1IL8B5S9Q') & set(ALPHABET))

    def test_png_is_valid_and_glyphs_add_dark_ink(self):
        width, height, depth, color, raw = decode_png(render_png('AC3K7Z', seed=7))
        self.assertEqual((width, height, depth, color), (captcha.WIDTH, captcha.HEIGHT, 8, 2))
        self.assertEqual(len(raw), height * (1 + width * 3))
        rows = [raw[y * (1 + width * 3) + 1:(y + 1) * (1 + width * 3)] for y in range(height)]
        dark = sum(1 for row in rows for i in range(0, len(row), 3) if sum(row[i:i + 3]) < 300)
        self.assertGreater(dark, width * height * 0.08)

    def test_same_text_never_renders_identically_and_bad_text_is_rejected(self):
        self.assertNotEqual(render_png('AC3K7Z'), render_png('AC3K7Z'))
        for text in ('ab', 'A0', None):
            with self.assertRaises(ValueError):
                render_png(text)


class CaptchaStoreTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.store = CaptchaStore(clock=lambda: self.now, code_factory=lambda: 'AC3K7Z', ttl=300)

    def test_answer_is_case_and_space_insensitive_and_single_use(self):
        challenge = self.store.issue()
        self.assertNotIn('AC3K7Z', repr(challenge))
        self.assertTrue(self.store.verify(challenge['captcha_id'], ' ac3 k7z '))
        self.assertFalse(self.store.verify(challenge['captcha_id'], 'AC3K7Z'))

    def test_any_attempt_consumes_the_challenge(self):
        for answer in ('WRONG1', None, 'x' * 40):
            challenge = self.store.issue()
            self.assertFalse(self.store.verify(challenge['captcha_id'], answer))
            self.assertFalse(self.store.verify(challenge['captcha_id'], 'AC3K7Z'))

    def test_expiry_unknown_ids_and_capacity(self):
        challenge = self.store.issue()
        self.now += 301
        self.assertFalse(self.store.verify(challenge['captcha_id'], 'AC3K7Z'))
        for value in (None, 7, 'missing', 'x' * 100):
            self.assertFalse(self.store.verify(value, 'AC3K7Z'))
        small = CaptchaStore(code_factory=lambda: 'AC3K7Z', max_pending=3)
        issued = [small.issue()['captcha_id'] for _ in range(5)]
        self.assertFalse(small.verify(issued[0], 'AC3K7Z'))
        self.assertTrue(small.verify(issued[-1], 'AC3K7Z'))


if __name__ == '__main__':
    unittest.main()
