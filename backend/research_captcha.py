"""Six-character image CAPTCHA, Python standard library only.

The usual GitHub libraries (lepture/captcha, wheezy.captcha, claptcha) draw with
Pillow, which the bundled Windows runtime does not ship. This module renders the
same kind of challenge directly: bitmap glyphs, per-glyph rotation/scale/offset,
a whole-image wave warp, interference curves and speckle noise, encoded as PNG
with zlib. Answers are stored only as salted digests and every challenge is
single use: any verification attempt consumes it.
"""
import base64
import hashlib
import hmac
import math
import random
import secrets
import struct
import threading
import time
import zlib

# Look-alikes removed: 0/O/Q, 1/I/L, 8/B, 5/S, 9/G.
ALPHABET = '23467ACDEFGHJKMNPRTUVWXYZ'
LENGTH = 6
WIDTH, HEIGHT = 200, 70
TTL_SECONDS = 300
MAX_PENDING = 20000

_FONT_ROWS = {
    '2': ['.###.', '#...#', '....#', '...#.', '..#..', '.#...', '#####'],
    '3': ['####.', '....#', '....#', '.###.', '....#', '....#', '####.'],
    '4': ['...#.', '..##.', '.#.#.', '#..#.', '#####', '...#.', '...#.'],
    '6': ['..##.', '.#...', '#....', '####.', '#...#', '#...#', '.###.'],
    '7': ['#####', '....#', '...#.', '..#..', '.#...', '.#...', '.#...'],
    'A': ['.###.', '#...#', '#...#', '#####', '#...#', '#...#', '#...#'],
    'C': ['.###.', '#...#', '#....', '#....', '#....', '#...#', '.###.'],
    'D': ['###..', '#..#.', '#...#', '#...#', '#...#', '#..#.', '###..'],
    'E': ['#####', '#....', '#....', '####.', '#....', '#....', '#####'],
    'F': ['#####', '#....', '#....', '####.', '#....', '#....', '#....'],
    'G': ['.###.', '#...#', '#....', '#.###', '#...#', '#...#', '.####'],
    'H': ['#...#', '#...#', '#...#', '#####', '#...#', '#...#', '#...#'],
    'J': ['..###', '...#.', '...#.', '...#.', '...#.', '#..#.', '.##..'],
    'K': ['#...#', '#..#.', '#.#..', '##...', '#.#..', '#..#.', '#...#'],
    'M': ['#...#', '##.##', '#.#.#', '#.#.#', '#...#', '#...#', '#...#'],
    'N': ['#...#', '#...#', '##..#', '#.#.#', '#..##', '#...#', '#...#'],
    'P': ['####.', '#...#', '#...#', '####.', '#....', '#....', '#....'],
    'R': ['####.', '#...#', '#...#', '####.', '#.#..', '#..#.', '#...#'],
    'T': ['#####', '..#..', '..#..', '..#..', '..#..', '..#..', '..#..'],
    'U': ['#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '.###.'],
    'V': ['#...#', '#...#', '#...#', '#...#', '#...#', '.#.#.', '..#..'],
    'W': ['#...#', '#...#', '#...#', '#.#.#', '#.#.#', '#.#.#', '.#.#.'],
    'X': ['#...#', '#...#', '.#.#.', '..#..', '.#.#.', '#...#', '#...#'],
    'Y': ['#...#', '#...#', '.#.#.', '..#..', '..#..', '..#..', '..#..'],
    'Z': ['#####', '....#', '...#.', '..#..', '.#...', '#....', '#####'],
}
FONT = {ch: [[cell == '#' for cell in row] for row in rows] for ch, rows in _FONT_ROWS.items()}
assert set(FONT) == set(ALPHABET) and all(len(r) == 5 for g in FONT.values() for r in g)

_SAMPLES = ((-0.25, -0.25), (0.25, -0.25), (-0.25, 0.25), (0.25, 0.25))


def _inked(glyph, u, v, bold=0.16):
    """True when (u, v) lands on an inked cell, widened slightly for bolder strokes."""
    for du, dv in ((0, 0), (-bold, 0), (bold, 0), (0, -bold), (0, bold)):
        a, b = u + du, v + dv
        if 0 <= a < 5 and 0 <= b < 7 and glyph[int(b)][int(a)]:
            return True
    return False


def new_code(rng=secrets):
    return ''.join(rng.choice(ALPHABET) for _ in range(LENGTH))


def _png(width, height, pixels):
    raw = b''.join(b'\x00' + bytes(pixels[y * width * 3:(y + 1) * width * 3]) for y in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def render_png(code, seed=None):
    """Render ``code`` as PNG bytes. ``seed`` only fixes the visual jitter (tests)."""
    if not isinstance(code, str) or any(ch not in FONT for ch in code):
        raise ValueError('unsupported captcha text')
    rng = random.Random(secrets.randbits(64) if seed is None else seed)
    w, h = WIDTH, HEIGHT
    # Pale noisy background with a gentle horizontal gradient.
    base = [rng.randint(225, 245) for _ in range(3)]
    tilt = [rng.randint(-18, 18) for _ in range(3)]
    px = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 3
            for c in range(3):
                px[i + c] = max(0, min(255, base[c] + tilt[c] * x // w + rng.randint(-10, 10)))

    def blend(x, y, color, alpha):
        if 0 <= x < w and 0 <= y < h and alpha > 0:
            i = (y * w + x) * 3
            for c in range(3):
                px[i + c] = int(px[i + c] * (1 - alpha) + color[c] * alpha)

    # Whole-image wave warp shared by every glyph so letters bend together.
    ax, ay = rng.uniform(1.5, 3.0), rng.uniform(1.5, 3.5)
    fx, fy = rng.uniform(0.05, 0.10), rng.uniform(0.04, 0.08)
    px0, py0 = rng.uniform(0, math.tau), rng.uniform(0, math.tau)

    def warp(x, y):
        return x + ax * math.sin(y * fx + px0), y + ay * math.sin(x * fy + py0)

    slot = (w - 16) / len(code)
    for index, ch in enumerate(code):
        glyph = FONT[ch]
        cell = rng.uniform(4.6, 5.4)
        angle = math.radians(rng.uniform(-20, 20))
        cx = 8 + slot * (index + 0.5) + rng.uniform(-3, 3)
        cy = h / 2 + rng.uniform(-6, 6)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        color = [rng.randint(15, 120) for _ in range(3)]
        reach = int(cell * 5) + 6
        for y in range(int(cy) - reach, int(cy) + reach):
            if not 0 <= y < h:
                continue
            for x in range(int(cx) - reach, int(cx) + reach):
                if not 0 <= x < w:
                    continue
                hits = 0
                for ox, oy in _SAMPLES:
                    sx, sy = warp(x + ox, y + oy)
                    dx, dy = sx - cx, sy - cy
                    # Inverse-rotate into glyph cells (5 x 7, centred).
                    u = (dx * cos_a + dy * sin_a) / cell + 2.5
                    v = (-dx * sin_a + dy * cos_a) / cell + 3.5
                    if _inked(glyph, u, v):
                        hits += 1
                if hits:
                    blend(x, y, color, hits / len(_SAMPLES))

    # Interference curves crossing the text.
    for _ in range(3):
        color = [rng.randint(40, 150) for _ in range(3)]
        amp, freq, phase = rng.uniform(6, 16), rng.uniform(0.02, 0.06), rng.uniform(0, math.tau)
        mid, slope = rng.uniform(h * 0.3, h * 0.7), rng.uniform(-0.15, 0.15)
        for x in range(w):
            y = mid + slope * (x - w / 2) + amp * math.sin(x * freq + phase)
            for t in (-0.6, 0, 0.6):
                blend(x, int(y + t), color, 0.55)
    for _ in range(320):
        blend(rng.randrange(w), rng.randrange(h), [rng.randint(0, 200) for _ in range(3)], rng.uniform(0.4, 0.9))
    return _png(w, h, px)


class CaptchaStore:
    """Thread-safe, in-memory, single-use challenges (a restart simply invalidates them)."""

    def __init__(self, *, ttl=TTL_SECONDS, clock=time.monotonic, code_factory=new_code, max_pending=MAX_PENDING):
        self.ttl, self.clock, self.code_factory, self.max_pending = ttl, clock, code_factory, max_pending
        self._key = secrets.token_bytes(32)
        self._pending = {}
        self._lock = threading.Lock()

    def _digest(self, challenge_id, code):
        normalized = ''.join(str(code).split()).upper()
        return hmac.new(self._key, (challenge_id + ':' + normalized).encode('utf-8'), hashlib.sha256).digest()

    def issue(self):
        code = self.code_factory()
        challenge_id = secrets.token_urlsafe(24)
        image = render_png(code)
        now = self.clock()
        with self._lock:
            for key in [k for k, (_, expires) in self._pending.items() if expires <= now]:
                del self._pending[key]
            while len(self._pending) >= self.max_pending:
                del self._pending[next(iter(self._pending))]
            self._pending[challenge_id] = (self._digest(challenge_id, code), now + self.ttl)
        return {'captcha_id': challenge_id, 'length': LENGTH, 'expires_in': self.ttl,
                'image': 'data:image/png;base64,' + base64.b64encode(image).decode('ascii')}

    def verify(self, challenge_id, code):
        if not isinstance(challenge_id, str) or len(challenge_id) > 64:
            return False
        with self._lock:
            # Consume first: a malformed or missing answer still burns the challenge.
            entry = self._pending.pop(challenge_id, None)
        if entry is None or not isinstance(code, str) or len(code) > 32:
            return False
        digest, expires = entry
        return self.clock() < expires and hmac.compare_digest(digest, self._digest(challenge_id, code))
