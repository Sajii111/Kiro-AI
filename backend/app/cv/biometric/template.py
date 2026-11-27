"""Step 5: the template. What is kept of a locked palm: the features of the enrolment photos, never the photos.

A template is packed into a NumPy archive (no Python objects inside, so reading one can never run code) and sealed with
Fernet (AES in CBC mode with an HMAC: anyone without the key can neither read nor change it). Only the sealed bytes are
stored. The key lives with the server's settings, never with the data.

A template remembers the engine version and settings hash it was made with. One made by different settings is refused
(`TemplateOutdated`) instead of being compared unfairly: the person is asked to set the lock up again.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
from cryptography.fernet import Fernet, InvalidToken

from .compcode import CompCodeFeature
from .config import DEFAULT, ENGINE_VERSION, EngineSettings, config_hash
from .crease import CreaseFeature
from .match import Features

FORMAT = 1


class TemplateError(Exception):
    """The sealed template could not be opened: the wrong key, or the bytes were changed."""


class TemplateOutdated(TemplateError):
    """The template was made by a different engine version or different settings."""


@dataclass
class Template:
    side: str
    samples: list[Features]
    engine_version: str = ENGINE_VERSION
    config_hash: str = field(default_factory=lambda: config_hash(DEFAULT))
    created: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec='seconds'))


def to_bytes(template: Template) -> bytes:
    meta = {
        'format': FORMAT,
        'side': template.side,
        'count': len(template.samples),
        'engine_version': template.engine_version,
        'config_hash': template.config_hash,
        'created': template.created,
    }
    arrays: dict[str, np.ndarray] = {'meta': np.frombuffer(json.dumps(meta).encode(), np.uint8)}
    for i, s in enumerate(template.samples):
        arrays[f'crease_map_{i}'] = s.crease.map.astype(np.float16)
        arrays[f'crease_grid_{i}'] = s.crease.grid.astype(np.float16)
        arrays[f'code_{i}'] = s.compcode.code.astype(np.uint8)
        arrays[f'valid_{i}'] = s.compcode.valid.astype(np.bool_)
        arrays[f'lbp_{i}'] = s.lbp.astype(np.float16)
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)  # type: ignore[arg-type]
    return buf.getvalue()


def from_bytes(data: bytes, settings: EngineSettings = DEFAULT) -> Template:
    try:
        with np.load(io.BytesIO(data), allow_pickle=False) as z:
            meta = json.loads(bytes(z['meta']).decode())
            if meta.get('format') != FORMAT:
                raise TemplateOutdated('the template was saved in a different format')
            samples = [
                Features(
                    crease=CreaseFeature(map=z[f'crease_map_{i}'].astype(np.float32), grid=z[f'crease_grid_{i}'].astype(np.float32)),
                    compcode=CompCodeFeature(code=z[f'code_{i}'].astype(np.uint8), valid=z[f'valid_{i}'].astype(bool)),
                    lbp=z[f'lbp_{i}'].astype(np.float32),
                )
                for i in range(int(meta['count']))
            ]
    except TemplateError:
        raise
    except (OSError, ValueError, KeyError) as e:
        raise TemplateError(f'the template could not be read: {e}') from e
    template = Template(side=meta['side'], samples=samples, engine_version=meta['engine_version'], config_hash=meta['config_hash'], created=meta['created'])
    if template.engine_version != ENGINE_VERSION or template.config_hash != config_hash(settings):
        raise TemplateOutdated(f'the template was made by {template.engine_version} ({template.config_hash})')
    return template


def new_key() -> str:
    """A fresh key for sealing templates, as text (keep it secret, like a password)."""
    return Fernet.generate_key().decode()


def seal(template: Template, key: str | bytes) -> bytes:
    return Fernet(key).encrypt(to_bytes(template))


def unseal(sealed: bytes, key: str | bytes, settings: EngineSettings = DEFAULT) -> Template:
    try:
        data = Fernet(key).decrypt(sealed)
    except (InvalidToken, ValueError, TypeError) as e:
        raise TemplateError('the template could not be opened with this key') from e
    return from_bytes(data, settings)
