"""Sentences that the website also shows (src/app/copy.ts and src/lib/status.ts). Kept word for word, so a reading
reads the same whichever side wrote it."""

from __future__ import annotations

DISCLAIMER_SHORT = 'Palmistry is an old art, not a science: take your reading as a story about who you may become, not a promise. Never medical, financial or legal advice.'

DISCLAIMER_LONG = (
    'Palmistry is an old art of reading the hand, not a science. Your reading is written in the voice of a fortune teller, for '
    'enjoyment and for thought: take it as a story about who you may become, not as a promise, and never as medical, financial, '
    'legal or relationship advice. Lines in a photo can also be missed or misread, which is why each one is marked detected, '
    'uncertain or not visible.'
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
