"""Every setting the palm lock uses, in one place.

A template only makes sense with the settings that made it: change one number here and old templates no longer
compare fairly with new photos. So the settings are hashed (`config_hash`) and the hash is kept in every template and in
the calibration file. A template or calibration made with different settings is refused instead of being misread.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

#: shown in the attempt log and kept in every template; bump it when the method changes
ENGINE_VERSION = 'palm-lock 0.2'


@dataclass(frozen=True)
class RoiSettings:
    #: the middle of the square lies this far below the line of the four knuckles, toward the wrist, in knuckle spans (index-finger
    #: knuckle to little-finger knuckle). 0.75 puts the square on the middle of the palm below the finger-base creases, where the principal lines are.
    center_below: float = 0.75
    #: the side of the square, as a share of the knuckle span (index-finger knuckle to little-finger knuckle)
    side_scale: float = 0.9
    #: pixels on each side of the cut-out square
    size: int = 128
    #: the share of the square that must lie on the hand
    min_inside: float = 0.95
    #: the shortest palm (wrist to knuckles, in pixels of the analysis copy) that still shows its creases
    min_palm_px: float = 160.0
    #: the silhouette (used only to check the square is on the hand) is cut out at this size: small is quick
    mask_side: int = 320


@dataclass(frozen=True)
class PrepSettings:
    denoise_sigma: float = 1.0
    clahe_clip: float = 2.0
    clahe_tiles: int = 8
    #: how far the brightness is averaged to take out shading; detail smaller than this is kept
    flatten_sigma: float = 8.0
    #: a square whose detail varies less than this (grey levels, 0-255) is too flat or too blurred to judge
    min_spread: float = 3.0


@dataclass(frozen=True)
class CreaseSettings:
    #: scales of the valley filter, in pixels of the square
    sigmas: tuple[float, ...] = (1.5, 2.0, 3.0)
    #: the share of pixels kept as crease
    keep: float = 0.12
    #: crease pieces smaller than this many pixels are dropped as noise
    min_area: int = 15
    #: cells across the square for the direction histograms, and direction bins in each
    grid: int = 8
    bins: int = 4
    #: the crease map is softened by this much (pixels) so a crease one pixel off still overlaps
    blur: float = 2.0
    #: the stored map is this many pixels across (the square is shrunk to it)
    map_size: int = 64
    #: the largest shift tried when two maps are compared, in pixels of the stored map
    shift: int = 3


@dataclass(frozen=True)
class CompCodeSettings:
    orientations: int = 6
    ksize: int = 25
    sigma: float = 4.0
    lambd: float = 9.0
    gamma: float = 0.5
    #: block size in pixels: one code per block
    step: int = 4
    #: the largest shift tried, in blocks
    shift: int = 2
    #: a block whose winning direction is weaker than this share of a strong block's is left out of the comparison
    weak: float = 0.15
    #: at least this share of the blocks must be comparable in both codes
    min_overlap: float = 0.3


@dataclass(frozen=True)
class LbpSettings:
    grid: int = 4


@dataclass(frozen=True)
class MatchSettings:
    #: the methods that decide, and how much each counts
    methods: tuple[str, ...] = ('crease', 'compcode')
    weights: tuple[float, ...] = (0.5, 0.5)
    #: photos needed to lock a profile, and the most that are kept
    enrol_min: int = 3
    enrol_max: int = 5
    #: every enrolment photo must match the others on average by at least the threshold plus this
    consistency_margin: float = 0.0


@dataclass(frozen=True)
class EngineSettings:
    roi: RoiSettings = field(default_factory=RoiSettings)
    prep: PrepSettings = field(default_factory=PrepSettings)
    crease: CreaseSettings = field(default_factory=CreaseSettings)
    compcode: CompCodeSettings = field(default_factory=CompCodeSettings)
    lbp: LbpSettings = field(default_factory=LbpSettings)
    match: MatchSettings = field(default_factory=MatchSettings)


def config_hash(settings: EngineSettings) -> str:
    """A short fingerprint of the settings that change what a template holds or how it is compared."""
    data = asdict(settings)
    data.pop('match', None)  # how many photos are asked for does not change a template
    text = json.dumps(data, sort_keys=True)
    return hashlib.sha256(f'{ENGINE_VERSION}|{text}'.encode()).hexdigest()[:16]


DEFAULT = EngineSettings()
