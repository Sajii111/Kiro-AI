"""The names of the two ways a reading can be made, written into every reading's `meta` (see llm/report.py)."""

#: the stand-in: it never looks at the photo (cv/standin.py). Used for the website's built-in sample drawings, for the
#: tests, and when the hand model is not installed.
STAND_IN_PIPELINE = 'opencv-steps 0.1'
STAND_IN_DETECTOR = 'sample-detector 0.2'

#: the real analysis: the hand is found with MediaPipe, the creases with the ridge filter and tracer (cv/palm.py, cv/lines.py)
REAL_PIPELINE = 'opencv-steps 1.0'
REAL_DETECTOR = 'palm-lines 1.1'
