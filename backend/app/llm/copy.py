"""Sentences that the website also shows (src/app/copy.ts and src/lib/status.ts). Kept word for word, so a reading
reads the same whichever side wrote it."""

from __future__ import annotations

DISCLAIMER_SHORT = 'Traditional palmistry, for reflection and entertainment. Not medical, financial, employment or relationship advice.'

DISCLAIMER_LONG = (
    'Palmistry is a traditional practice kept here for reflection and entertainment. It is not science, and this reading '
    'is not medical, financial, employment or relationship advice. Lines in a photo can also be missed or misread, which '
    'is why each one is marked detected, uncertain or not visible.'
)

PHOTO_TIPS = [
    'Use even daylight. Avoid flash and strong shadows across the palm.',
    'Hold the palm flat and facing the camera, fingers gently apart.',
    'Keep the whole hand in the frame, from fingertips to the wrist crease.',
    'Hold still and tap to focus on the palm. Sharp creases matter most.',
]

STATUS_LABEL = {
    'detected': 'Detected',
    'uncertain': 'Uncertain',
    'not_visible': 'Not visible',
}
