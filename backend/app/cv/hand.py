"""Finding the hand in a photo, and the geometry that follows from where it is.

THE HAND MODEL. The finder is MediaPipe's hand landmarker (from Google). It is a small neural network that runs on THIS
computer, in this process, from the file backend/models/hand_landmarker.task (`run.bat models` downloads it). For every
hand it sees it returns 21 landmark points (the wrist, and four joints along each finger) and says whether the hand is a
left or a right one. Nothing else in this project uses a trained network: the creases themselves are found with the
classical image-processing steps in palm.py and lines.py, and the landmarks only tell those steps where the hand is.

WHAT MEDIAPIPE SENDS TO GOOGLE. The model runs offline, but the MediaPipe library itself opens a connection to Google
(play.googleapis.com) the first time a model runs, to report usage statistics. We traced the library's network calls to
check this. Its own Python code hands over the name and version of the operating system and the version of the library
(a photo and the landmarks are not part of that call), and there is no switch to turn it off. The connection is made by
the library, not by this project, and the content of the encrypted call cannot be read, so the claim here is only about
what the library is built to send. It is listed in the README, the privacy text and the report.

Landmark numbers (MediaPipe's): 0 wrist; 1-4 thumb; 5-8 index; 9-12 middle; 13-16 ring; 17-20 little finger. Points 5, 9,
13 and 17 are the knuckles (the joints where the fingers join the palm).
"""

from __future__ import annotations

import importlib.util
import itertools
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import cv2
import numpy as np

log = logging.getLogger('kiro.hand')

N_LANDMARKS = 21
WRIST = 0
INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP = 5, 9, 13, 17
#: the base of the thumb, where it joins the wrist
THUMB_CMC = 1
MIDDLE_FINGER = (9, 10, 11, 12)

Label = Literal['left', 'right']

# ------------------------------------------------------------------ what the finder returns


@dataclass(frozen=True)
class FoundHand:
    """One hand found in a picture. `points` are in pixels of that picture. `label` is what the network says the hand is,
    as it looks in the picture: a mirrored photo of a left hand reads as a right hand."""

    points: np.ndarray  # (21, 2)
    label: Label
    score: float  # how sure the network is of the label, 0 to 1

    @property
    def size(self) -> float:
        """Wrist to the middle knuckle, in pixels. Used to pick the biggest of several hands."""
        return float(np.linalg.norm(self.points[MIDDLE_MCP] - self.points[WRIST]))


class HandFinder(Protocol):
    def find(self, bgr: np.ndarray) -> list[FoundHand]:
        """Every hand in the picture, the biggest first."""
        ...


# ------------------------------------------------------------------ the palm's own coordinates


@dataclass(frozen=True)
class Frame:
    """A coordinate system fixed to one palm, so that every hand is measured the same way whatever the photo.

    Origin: the wrist. Unit: L, the distance from the wrist to the middle of the four knuckles. Y runs from the wrist
    toward the fingers. X runs toward the thumb (so a left and a right hand, as seen from the palm, are each other's
    mirror image in photo space but look the same here).
    """

    wrist: np.ndarray
    u: np.ndarray  # unit vector, photo pixels: wrist to knuckles
    v: np.ndarray  # unit vector, photo pixels: toward the thumb
    length: float  # L in photo pixels
    sign: int  # +1: the thumb is to the right of the fingers' direction in the photo (a right palm, or the back of a left hand); -1: the opposite

    def to_canon(self, points: np.ndarray) -> np.ndarray:
        d = np.asarray(points, np.float64) - self.wrist
        return np.stack([(d @ self.v) / self.length, (d @ self.u) / self.length], axis=-1)

    def to_photo(self, xy: np.ndarray) -> np.ndarray:
        xy = np.asarray(xy, np.float64)
        return self.wrist + self.length * (xy[..., 0:1] * self.v + xy[..., 1:2] * self.u)


def hand_frame(points: np.ndarray) -> Frame | None:
    """The palm's frame from its 21 landmarks. None when the points are too bunched up to define one."""
    if not np.all(np.isfinite(points)):
        return None
    wrist = points[WRIST]
    knuckles = points[[INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]].mean(axis=0)
    u = knuckles - wrist
    length = float(np.linalg.norm(u))
    if length < 8:
        return None
    u = u / length
    t = points[INDEX_MCP] - points[PINKY_MCP]  # across the knuckles, little finger to index finger
    t = t - (t @ u) * u
    n = float(np.linalg.norm(t))
    if n < 1e-6:
        return None
    v = t / n
    sign = 1 if (u[0] * v[1] - u[1] * v[0]) > 0 else -1
    return Frame(wrist=wrist.astype(np.float64), u=u, v=v, length=length, sign=sign)


# ------------------------------------------------------------------ what the landmarks say about the photo


@dataclass(frozen=True)
class HandFacts:
    #: the palm's length in pixels (wrist to knuckles)
    length: float
    #: width across the knuckles divided by the palm's length. About 0.7 for a palm facing the camera, near 0 when it is edge-on.
    flatness: float
    #: length of the middle finger divided by the palm's length. Small when the fingers are curled.
    finger_reach: float
    #: some landmark is at, or past, the edge of the photo
    cut_off: bool
    #: the same, ignoring the thumb: the palm and the four fingers are what the reading needs
    cut_off_palm: bool
    #: does the palm (not the back of the hand) face the camera? None when the network is not sure enough to say.
    shows_palm: bool | None
    #: the network's left/right label agrees with the slot the photo was added to. None when not sure enough.
    side_matches: bool | None


#: a landmark this close to the edge of the photo (as a share of its width or height) counts as cut off
EDGE_MARGIN = 0.002
THUMB = (1, 2, 3, 4)
LABEL_SURE = 0.80
BACK_SURE = 0.85


def chain_length(points: np.ndarray, ids: tuple[int, ...]) -> float:
    return float(sum(np.linalg.norm(points[a] - points[b]) for a, b in itertools.pairwise(ids)))


def describe(hand: FoundHand, frame: Frame, width: int, height: int, slot: Label) -> HandFacts:
    p = hand.points
    flatness = float(np.linalg.norm(p[INDEX_MCP] - p[PINKY_MCP]) / frame.length)
    reach = chain_length(p, MIDDLE_FINGER) / frame.length
    mx, my = width * EDGE_MARGIN, height * EDGE_MARGIN
    outside = (p[:, 0] < mx) | (p[:, 0] > width - mx) | (p[:, 1] < my) | (p[:, 1] > height - my)
    cut = bool(outside.any())
    cut_palm = bool(np.delete(outside, THUMB).any())

    # The network reads the hand from its look (thumb, knuckles), the frame reads it from where the thumb is. They agree
    # when the palm faces the camera, and disagree for the back of the hand.
    shows_palm: bool | None = None
    if hand.score >= BACK_SURE and flatness >= 0.45:
        shows_palm = (hand.label == 'right') == (frame.sign > 0)
    side_matches = (hand.label == slot) if hand.score >= LABEL_SURE else None
    return HandFacts(length=frame.length, flatness=flatness, finger_reach=reach, cut_off=cut, cut_off_palm=cut_palm, shows_palm=shows_palm, side_matches=side_matches)


# ------------------------------------------------------------------ MediaPipe


class MediaPipeFinder:
    """MediaPipe's hand landmarker, loaded on first use and shared by every request (one picture at a time)."""

    def __init__(self, model_path: Path):
        self.model_path = Path(model_path)
        self._landmarker = None
        self._mp = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        os.environ.setdefault('GLOG_minloglevel', '2')  # keep the library's own chatter out of the console
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            HandLandmarker,
            HandLandmarkerOptions,
            RunningMode,
        )

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
        )
        self._mp = mp
        self._landmarker = HandLandmarker.create_from_options(options)

    def close(self) -> None:
        """Releases the model. Call it while the program is still running (the server does, when it stops): the library
        complains if it is only cleaned up while Python is shutting down."""
        with self._lock:
            landmarker, self._landmarker = self._landmarker, None
        if landmarker is not None:
            landmarker.close()

    def warm_up(self) -> None:
        with self._lock:
            if self._landmarker is None:
                self._load()

    def find(self, bgr: np.ndarray) -> list[FoundHand]:
        height, width = bgr.shape[:2]
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        with self._lock:
            if self._landmarker is None:
                self._load()
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            result = self._landmarker.detect(image)
        found: list[FoundHand] = []
        for landmarks, handedness in zip(result.hand_landmarks, result.handedness, strict=False):
            if len(landmarks) != N_LANDMARKS or not handedness:
                continue
            points = np.array([[p.x * width, p.y * height] for p in landmarks], np.float64)
            category = handedness[0]
            label: Label = 'left' if str(category.category_name).lower().startswith('l') else 'right'
            found.append(FoundHand(points=points, label=label, score=float(category.score)))
        found.sort(key=lambda h: h.size, reverse=True)
        return found


# ------------------------------------------------------------------ choosing the mode when the server starts


def mediapipe_installed() -> bool:
    return importlib.util.find_spec('mediapipe') is not None


def build_finder(mode: str, model: Path) -> HandFinder | None:
    """The finder real analysis needs, or None to run on the sample finder.

    mode "sample": never use the hand model.   "real": the hand model must work, or the server does not start.
    "auto": use it when it is installed and the model file is there, and say so when it is not."""
    if mode == 'sample':
        return None
    problem: str | None = None
    if not mediapipe_installed():
        problem = 'The MediaPipe package is not installed. Run run.bat to install it.'
    elif not Path(model).is_file():
        problem = f'The hand model file {Path(model).name} is not in {Path(model).parent}. Run  run.bat models  once to download it.'
    if problem is None:
        finder = MediaPipeFinder(model)
        try:
            finder.warm_up()
            return finder
        except Exception as exc:  # noqa: BLE001 - the library raises several kinds of error for a bad or missing model
            problem = f'The hand model could not be loaded ({type(exc).__name__}: {exc}).'
    if mode == 'real':
        raise RuntimeError(problem)
    log.warning('Photos will get SAMPLE readings, not real ones. %s', problem)
    return None
