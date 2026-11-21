"""A server that does the real analysis on two drawn hands: a fake hand finder (synth.FakeFinder) stands in for the hand model, so
nothing needs MediaPipe or its model file. Pass `llm` to give it a language model (usually a FakeModel from fake_gemini.py)."""

from __future__ import annotations

from functools import lru_cache
from types import SimpleNamespace

from fastapi.testclient import TestClient
from helpers import add_profile, parse_stream, photo_files, start_guest
from synth import FakeFinder, found, jpeg, render

from app.main import create_app

LEFT_SIZE = (1300, 1250)
RIGHT_SIZE = (1300, 1300)


@lru_cache(maxsize=1)
def drawn_hands() -> SimpleNamespace:
    """Two drawn hands (a photo each) and what the fake finder knows about them. Drawn once for the whole test run."""
    left_image, left_placed = render('left', 12, size=LEFT_SIZE, seed=2)
    right_image, right_placed = render('right', -8, size=RIGHT_SIZE, seed=3)
    return SimpleNamespace(left=jpeg(left_image), right=jpeg(right_image), known={LEFT_SIZE: [found(left_placed)], RIGHT_SIZE: [found(right_placed)]})


def real_client(settings, llm=None) -> TestClient:
    """A browser on a server that reads the drawn hands for real, already signed in as a guest."""
    app = create_app(settings, finder=FakeFinder(drawn_hands().known), llm=llm)
    client = TestClient(app)
    start_guest(client)
    return client


def real_reading(client: TestClient, name: str = 'Saji') -> tuple[dict, dict, list]:
    """Makes a profile and a real reading. Returns (profile, reading, the stream's events)."""
    profile = add_profile(client, name=name)
    hands = drawn_hands()
    response = client.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files(hands.left, hands.right))
    assert response.status_code == 200, response.text
    events = parse_stream(response.text)
    assert events[-1][0] == 'reading', events[-1]
    return profile, events[-1][1], events  # type: ignore[return-value]
