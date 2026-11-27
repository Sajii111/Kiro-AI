"""Step 4: matching. How alike two palms are, as one score, and the line between "same palm" and "not".

Each method gives its own similarity, on its own scale: the competitive code gives about 0.5 for two unrelated palms,
the crease map much less. So before they are averaged each one is normalised with two numbers measured on validation
photos: its typical value for two different people (`impostor`, mapped to 0) and for the same person (`genuine`, mapped
to 1). The fused score is the weighted mean of the normalised scores, clipped to 0-1.

The threshold is the fused score at which a photo counts as the same palm. It is set on validation photos at the equal
error rate (where wrongly accepted and wrongly refused attempts are equally rare), lives in `calibration.json` with the
numbers above, and is shown read-only in the website: nobody can change it from a browser.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import compcode, crease, lbp
from .compcode import CompCodeFeature
from .config import DEFAULT, ENGINE_VERSION, EngineSettings, config_hash
from .crease import CreaseFeature

CALIBRATION_PATH = Path(__file__).with_name('calibration.json')
METHODS = ('crease', 'compcode', 'lbp')


@dataclass
class Features:
    """Everything the methods keep from one photo."""

    crease: CreaseFeature
    compcode: CompCodeFeature
    lbp: np.ndarray


def raw_scores(a: Features, b: Features, settings: EngineSettings = DEFAULT) -> dict[str, float]:
    """Each method's own similarity of two photos, 0 to 1, on its own scale."""
    return {
        'crease': crease.similarity(a.crease, b.crease, settings.crease),
        'compcode': compcode.similarity(a.compcode, b.compcode, settings.compcode),
        'lbp': lbp.similarity(a.lbp, b.lbp),
    }


@dataclass(frozen=True)
class Normaliser:
    impostor: float
    genuine: float

    def apply(self, raw: float) -> float:
        span = self.genuine - self.impostor
        if span <= 1e-9:
            return 0.0
        return float(np.clip((raw - self.impostor) / span, 0.0, 1.0))


class CalibrationError(Exception):
    """The calibration file is missing, broken, or was made with different settings."""


@dataclass(frozen=True)
class Calibration:
    #: False until the numbers come from real validation photos; the website says "not yet calibrated" while it is
    calibrated: bool
    threshold: float
    normalisers: dict[str, Normaliser]
    weights: dict[str, float]
    #: where the numbers came from, in words
    source: str
    engine_version: str
    config_hash: str
    #: what was measured at the threshold (error rates, how many pairs), shown on the Palm lab page
    measured: dict = field(default_factory=dict)

    def normalised(self, raw: dict[str, float]) -> dict[str, float]:
        return {m: self.normalisers[m].apply(raw[m]) for m in self.normalisers if m in raw}

    def fuse(self, raw: dict[str, float]) -> float:
        norm = self.normalised(raw)
        total = sum(self.weights.values())
        if total <= 0:
            return 0.0
        return float(sum(w * norm[m] for m, w in self.weights.items()) / total)

    def to_json(self) -> dict:
        data = asdict(self)
        data['normalisers'] = {m: asdict(n) for m, n in self.normalisers.items()}
        return data


def calibration_from_json(data: dict) -> Calibration:
    try:
        return Calibration(
            calibrated=bool(data['calibrated']),
            threshold=float(data['threshold']),
            normalisers={m: Normaliser(float(v['impostor']), float(v['genuine'])) for m, v in data['normalisers'].items()},
            weights={m: float(w) for m, w in data['weights'].items()},
            source=str(data['source']),
            engine_version=str(data['engine_version']),
            config_hash=str(data['config_hash']),
            measured=dict(data.get('measured') or {}),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise CalibrationError(f'the calibration file is not complete: {e}') from e


def load_calibration(path: Path | None = None, settings: EngineSettings = DEFAULT) -> Calibration:
    """The calibration at `path`, or the shipped one (`CALIBRATION_PATH`, read when this is called)."""
    try:
        data = json.loads(Path(CALIBRATION_PATH if path is None else path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise CalibrationError(f'the calibration file could not be read: {e}') from e
    cal = calibration_from_json(data)
    if cal.engine_version != ENGINE_VERSION or cal.config_hash != config_hash(settings):
        raise CalibrationError(
            f'the calibration file was made for {cal.engine_version} ({cal.config_hash}), but the engine is {ENGINE_VERSION} '
            f'({config_hash(settings)}). Run the calibration again.'
        )
    for m in cal.weights:
        if m not in cal.normalisers:
            raise CalibrationError(f'the method {m} has a weight but no normaliser')
    return cal


def save_calibration(cal: Calibration, path: Path = CALIBRATION_PATH) -> None:
    Path(path).write_text(json.dumps(cal.to_json(), indent=2) + '\n', encoding='utf-8')
