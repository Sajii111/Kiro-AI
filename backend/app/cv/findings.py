"""What both finders (the stand-in and the real one) share: rounding, the sentences that describe a finding, and the
thresholds that turn the shape of a hand into words. The sentences are about what the PHOTO shows. What tradition says
about it is written in llm/knowledge.py, kept apart on purpose."""

from __future__ import annotations

import math

from app.llm.knowledge import FEATURE_NAMES
from app.schemas import FeatureStatus, FeatureTraits, PalmShapeTraits


def js_round(value: float) -> int:
    """JavaScript's Math.round (halves go up), which Python's round() does not do."""
    return math.floor(value + 0.5)


def r3(value: float) -> float:
    return js_round(value * 1000) / 1000


def clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


# ------------------------------------------------------------------ lines

LEN_WORD = {'short': 'short', 'medium': 'medium-length', 'long': 'long'}
CLARITY_WORD = {'clear': 'clearly marked', 'deep': 'deeply marked', 'faint': 'faint'}
CURVE_WORD = {'straight': 'runs almost straight', 'gentle': 'curves gently', 'pronounced': 'curves strongly'}


def observation_for(fid: str, status: FeatureStatus, t: FeatureTraits) -> str:
    name = FEATURE_NAMES[fid].lower()
    if status == 'not_visible':
        return f'No clear line was found where the {name} usually runs. It may be absent, very faint, or lost to lighting or focus.'
    if status == 'uncertain':
        return (
            f'Something line-like runs here, but it is faint or broken, so it may or may not be the {name}. '
            'Its length and shape cannot be judged reliably.'
        )
    length = LEN_WORD[t.length or 'medium']
    clarity = CLARITY_WORD[t.clarity or 'clear']
    curve = CURVE_WORD[t.curve or 'gentle']
    if fid == 'heart':
        end = 'beneath the index finger' if t.length == 'long' else 'beneath the middle finger' if t.length == 'medium' else 'beneath the ring finger'
        return f'A {length}, {clarity} line across the upper palm. It {curve} and ends {end}.'
    if fid == 'head':
        tail = ', reaching close to it' if t.length == 'long' else ', stopping well short of it' if t.length == 'short' else ''
        return f'A {length}, {clarity} line across the middle of the palm. It {curve} as it heads toward the outer edge{tail}.'
    if fid == 'life':
        tail = (
            'reaches down toward the wrist'
            if t.length == 'long'
            else 'fades out partway down the palm'
            if t.length == 'short'
            else 'runs about two thirds of the way to the wrist'
        )
        return f'A {length}, {clarity} line that arcs around the base of the thumb. It {curve} and {tail}.'
    if fid == 'fate':
        return f'A {length}, {clarity} line rising from the wrist toward the middle finger. It {curve}.'
    return f'A {length}, {clarity} line below the ring finger. It {curve}.'


# ------------------------------------------------------------------ the shape of the hand

#: width across the knuckles divided by the palm's length: at or above this the palm is called square, below it long
PALM_SQUARE_AT = 0.88
#: finger length divided by palm length, for the stand-in's stylised hand
FINGERS_LONG_AT = 0.9
#: the same ratio measured on a real photo: the middle finger counts as long when it is at least as long as the palm
#: (wrist to knuckles), the rule traditional palmistry gives
REAL_FINGERS_LONG_AT = 1.0


def shape_observation(traits: PalmShapeTraits, palm_ratio: float, finger_ratio: float) -> str:
    return f'A {traits.palm} palm (width to length {palm_ratio:.2f}) with {traits.fingers} fingers (finger length to palm length {finger_ratio:.2f}).'
