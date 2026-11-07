"""Which web folder the site serves, and which of its files need no login.

Two frontends exist while the React rewrite is under way:
  legacy  dist/                 hand-written pages; the cloud edition injects its
                                account scripts into index.html at request time.
  react   web/dist-react/       Vite build output; served as built, no injection.
FUNDPILOT_FRONTEND selects one (empty means legacy until the React pages are accepted).
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

LEGACY, REACT = 'legacy', 'react'
ASSET_SUFFIXES = ('.js', '.css', '.svg', '.png', '.ico', '.webmanifest')
LEGACY_PUBLIC = frozenset({'login.html', 'login.js', 'login.css', 'phone-verification.js',
                           'ai-service.html', 'ai-service.css', 'qq-support.png'})
# Pages a visitor can open before logging in; each one's scripts and styles come along.
PUBLIC_ENTRIES = ('login.html', 'ai-service.html')
# Files copied verbatim from web/public/ (not listed in the manifest). The web app
# manifest and its icons must be public: browsers fetch the manifest without cookies.
PUBLIC_EXTRAS = ('qq-support.png', 'favicon.svg', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png',
                 'apple-touch-icon.png')


@dataclass(frozen=True)
class Frontend:
    kind: str
    folder: Path
    assets: frozenset = field(default_factory=frozenset)
    public: frozenset = field(default_factory=frozenset)

    @property
    def injects_cloud_scripts(self):
        return self.kind == LEGACY


def frontend_kind(environ):
    value = (environ.get('FUNDPILOT_FRONTEND') or LEGACY).strip().lower()
    if value not in (LEGACY, REACT):
        raise RuntimeError('FUNDPILOT_FRONTEND 只能是 legacy 或 react')
    return value


def asset_names(folder):
    """Exact file names directly inside the folder; nothing nested, no symlinks."""
    if not folder.is_dir():
        return frozenset()
    return frozenset(file.name for file in folder.iterdir()
                     if file.is_file() and not file.is_symlink() and file.suffix in ASSET_SUFFIXES)


def manifest_public_files(folder):
    """The public pages plus every chunk and stylesheet they load, from Vite's manifest.

    Hashed names change on every build, so they cannot be written down by hand. The
    login page shares chunks with the main page; those shared chunks are public too,
    which is fine: they hold only code that is already in the login page's bundle."""
    path = folder / '.vite' / 'manifest.json'
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise RuntimeError(f'新版网页缺少构建清单 {path}，请在 web 文件夹运行 npm run build') from error
    if not isinstance(manifest, dict):
        raise RuntimeError(f'新版网页构建清单格式无效：{path}')
    public, seen = set(), set()

    def visit(key):
        if key in seen or key not in manifest:
            return
        seen.add(key)
        chunk = manifest[key]
        for name in [chunk.get('file'), *chunk.get('css', []), *chunk.get('assets', [])]:
            if isinstance(name, str) and '/' not in name:
                public.add(name)
        for child in [*chunk.get('imports', []), *chunk.get('dynamicImports', [])]:
            visit(child)

    for entry in PUBLIC_ENTRIES:
        if entry in manifest:
            public.add(entry)
            visit(entry)
    return public


def resolve_frontend(root, environ):
    root = Path(root)
    kind = frontend_kind(environ)
    if kind == LEGACY:
        folder = root / 'dist'
        return Frontend(kind, folder, asset_names(folder), LEGACY_PUBLIC)
    folder = root / 'web' / 'dist-react'
    if not (folder / 'index.html').is_file():
        raise RuntimeError(f'新版网页尚未构建（缺少 {folder / "index.html"}），请在 web 文件夹运行 npm run build')
    public = manifest_public_files(folder)
    if 'login.html' not in public:
        raise RuntimeError('新版网页构建清单中没有 login.html 入口')
    public.update(name for name in PUBLIC_EXTRAS if (folder / name).is_file())
    return Frontend(kind, folder, asset_names(folder), frozenset(public))
