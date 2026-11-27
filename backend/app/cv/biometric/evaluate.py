"""Measuring the palm lock on labelled photos, and setting its threshold from what was measured.

Pairs of photos of the same person are "genuine" pairs, pairs of different people "impostor" pairs.

- FAR (false acceptance rate): the share of impostor pairs that score at or above the threshold
- FRR (false rejection rate): the share of genuine pairs that score below it
- EER (equal error rate): where the two are equal; the threshold is set there

The normalisers (see `match`) are fitted first, from the medians of each method's raw scores, then the fused scores are
worked out and the threshold is placed at the EER. Fit them on validation photos and report the error rates on other,
test photos: numbers measured on the same photos the threshold was set on look better than they are.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from .config import DEFAULT, ENGINE_VERSION, EngineSettings, config_hash
from .match import Calibration, Features, Normaliser, raw_scores


@dataclass
class PairScores:
    genuine: list[dict[str, float]]
    impostor: list[dict[str, float]]
    #: (person a, photo a, person b, photo b) for each pair, genuine first, then impostor
    labels: list[tuple[str, int, str, int]]


def pair_scores(groups: Mapping[str, list[Features]], settings: EngineSettings = DEFAULT) -> PairScores:
    genuine: list[dict[str, float]] = []
    impostor: list[dict[str, float]] = []
    g_labels: list[tuple[str, int, str, int]] = []
    i_labels: list[tuple[str, int, str, int]] = []
    for person, samples in groups.items():
        for (i, a), (j, b) in itertools.combinations(enumerate(samples), 2):
            genuine.append(raw_scores(a, b, settings))
            g_labels.append((person, i, person, j))
    for p, q in itertools.combinations(groups, 2):
        for i, a in enumerate(groups[p]):
            for j, b in enumerate(groups[q]):
                impostor.append(raw_scores(a, b, settings))
                i_labels.append((p, i, q, j))
    return PairScores(genuine=genuine, impostor=impostor, labels=g_labels + i_labels)


def fit_normalisers(scores: PairScores, methods: tuple[str, ...]) -> dict[str, Normaliser]:
    out = {}
    for m in methods:
        g = float(np.median([s[m] for s in scores.genuine]))
        i = float(np.median([s[m] for s in scores.impostor]))
        out[m] = Normaliser(impostor=round(i, 4), genuine=round(max(g, i + 1e-3), 4))
    return out


def rates(genuine: np.ndarray, impostor: np.ndarray, threshold: float) -> tuple[float, float]:
    """(FAR, FRR) at a threshold."""
    far = float((impostor >= threshold).mean()) if len(impostor) else 0.0
    frr = float((genuine < threshold).mean()) if len(genuine) else 0.0
    return far, frr


def eer_threshold(genuine: np.ndarray, impostor: np.ndarray) -> tuple[float, float]:
    """(threshold, EER): the threshold where FAR and FRR are closest, and their mean there. When the two sets do not
    overlap at all, the threshold goes halfway between the best impostor and the worst genuine score."""
    genuine, impostor = np.asarray(genuine, float), np.asarray(impostor, float)
    if genuine.min() > impostor.max():
        return float((genuine.min() + impostor.max()) / 2), 0.0
    candidates = np.unique(np.concatenate([genuine, impostor]))
    best_t, best_gap, best_eer = float(candidates[0]), 2.0, 1.0
    for t in candidates:
        far, frr = rates(genuine, impostor, float(t))
        if abs(far - frr) < best_gap:
            best_t, best_gap, best_eer = float(t), abs(far - frr), (far + frr) / 2
    return best_t, float(best_eer)


def calibrate(groups: Mapping[str, list[Features]], source: str, calibrated: bool, settings: EngineSettings = DEFAULT) -> tuple[Calibration, PairScores]:
    methods = settings.match.methods
    scores = pair_scores(groups, settings)
    if not scores.genuine or not scores.impostor:
        raise ValueError('calibrating needs at least two people, one of them with two photos or more')
    normalisers = fit_normalisers(scores, ('crease', 'compcode', 'lbp'))
    weights = dict(zip(methods, settings.match.weights, strict=True))
    draft = Calibration(
        calibrated=calibrated,
        threshold=0.5,
        normalisers=normalisers,
        weights=weights,
        source=source,
        engine_version=ENGINE_VERSION,
        config_hash=config_hash(settings),
    )
    g = np.array([draft.fuse(s) for s in scores.genuine])
    i = np.array([draft.fuse(s) for s in scores.impostor])
    threshold, eer = eer_threshold(g, i)
    far, frr = rates(g, i, threshold)
    measured = {
        'date': datetime.now(UTC).date().isoformat(),
        'people': len(groups),
        'photos': sum(len(v) for v in groups.values()),
        'genuine_pairs': len(g),
        'impostor_pairs': len(i),
        'eer': round(eer, 4),
        'far': round(far, 4),
        'frr': round(frr, 4),
        'genuine_mean': round(float(g.mean()), 4),
        'impostor_mean': round(float(i.mean()), 4),
        'note': 'pairwise scores of the photos the threshold was set on',
    }
    cal = Calibration(
        calibrated=calibrated,
        threshold=round(threshold, 4),
        normalisers=normalisers,
        weights=weights,
        source=source,
        engine_version=ENGINE_VERSION,
        config_hash=config_hash(settings),
        measured=measured,
    )
    return cal, scores
