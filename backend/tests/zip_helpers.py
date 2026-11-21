"""Small projects and pictures for the tests of scripts/package.py and scripts/fresh_copy.py. Only the shapes matter: a "JPEG" here has
the segments of a JPEG (so that camera data can be told from none) and no picture in it."""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path


def jpeg(*, exif: bool = False, xmp: bool = False, extra: int = 0) -> bytes:
    """A JPEG-shaped file: only the segments are real. With `exif`, what a phone writes in."""
    out = b'\xff\xd8\xff\xe0' + struct.pack('>H', 16) + b'JFIF\0\x01\x01\0\0\x01\0\x01\0\0'
    if exif:
        body = b'Exif\0\0' + b'MM\0*\0\0\0\x08' + b'GPS' * 5
        out += b'\xff\xe1' + struct.pack('>H', len(body) + 2) + body
    if xmp:
        body = b'http://ns.adobe.com/xap/1.0/\0<x:xmpmeta/>'
        out += b'\xff\xe1' + struct.pack('>H', len(body) + 2) + body
    return out + b'\xff\xda\x00\x02' + b'\x12' * (10 + extra) + b'\xff\xd9'


def png(*, exif: bool = False) -> bytes:
    def chunk(kind: bytes, body: bytes = b'') -> bytes:
        return struct.pack('>I', len(body)) + kind + body + b'\0\0\0\0'

    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', b'\0' * 13) + (chunk(b'eXIf', b'MM\0*') if exif else b'') + chunk(b'IDAT', b'\0\0') + chunk(b'IEND')


def model_bytes(tmp_path: Path) -> bytes:
    """What problem_with accepts as a hand model: a zip that holds two .tflite files."""
    made = tmp_path / 'model.zip'
    with zipfile.ZipFile(made, 'w') as archive:
        archive.writestr('hand_detector.tflite', b'a' * 200)
        archive.writestr('hand_landmarks_detector.tflite', b'b' * 200)
    return made.read_bytes()


SOURCES = {
    'README.md': '# Kiro AI\n',
    'run.bat': b'@echo off\r\nrem run it\r\n',
    '.gitignore': 'debug/\n',
    '.env.example': 'VITE_USE_MOCK=true\n',
    'index.html': '<html></html>\n',
    'package.json': '{"name": "kiro-ai"}\n',
    'package-lock.json': '{}\n',
    'src/App.tsx': 'export default 1\n',
    'public/favicon.svg': '<svg/>\n',
    'backend/requirements.txt': 'fastapi==1.0\n',
    'backend/.env.example': 'GEMINI_API_KEY=paste-your-key-here\n',
    'backend/app/main.py': 'app = 1\n',
    'backend/secrets/.gitkeep': '',
    'backend/models/.gitkeep': 'Downloaded model files go here.\n',
    'backend/tests/test_one.py': 'def test_one():\n    pass\n',
    'scripts/serve.py': 'x = 1\n',
    'scripts/preflight.py': 'x = 1\n',
    'scripts/package.py': 'x = 1\n',
    'docs/API_CONTRACT.md': '# API\n',
    'docs/licenses/Apache-2.0.txt': 'Apache License\n',
}


def write(root: Path, files: dict[str, str | bytes]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())


def build_site(pk, root: Path, *, mock: bool = False) -> None:
    """What `npm run build:server` and then serve.py leave behind."""
    site = root / 'dist-server'
    site.mkdir(exist_ok=True)
    (site / 'index.html').write_text('<html>built</html>')
    (site / 'build-info.json').write_text('{"mock": %s, "mode": "server"}' % ('true' if mock else 'false'))
    (site / 'source.sha256').write_text(pk.serve.source_stamp(root))
