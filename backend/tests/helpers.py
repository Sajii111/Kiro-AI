"""Small helpers shared by the tests."""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / 'data'
LEFT = (DATA / 'sample-left.jpg').read_bytes()
RIGHT = (DATA / 'sample-right.jpg').read_bytes()

STAGES = ['validate', 'resize', 'gray', 'blur', 'contrast', 'edges', 'threshold', 'morphology', 'lines', 'reading']
IMAGE_STAGES = ['gray', 'blur', 'contrast', 'edges', 'threshold', 'morphology']


def parse_stream(text: str) -> list[tuple[str, object]]:
    """The events of a server-sent-events body as (name, data) pairs. Comment lines are skipped."""
    events: list[tuple[str, object]] = []
    for block in text.replace('\r\n', '\n').split('\n\n'):
        lines = [line for line in block.split('\n') if line and not line.startswith(':')]
        if not lines:
            continue
        name, data = 'message', []
        for line in lines:
            if line.startswith('event:'):
                name = line[6:].strip()
            elif line.startswith('data:'):
                data.append(line[5:].lstrip(' '))
        events.append((name, json.loads('\n'.join(data))))
    return events


def photo_files(left: bytes = LEFT, right: bytes = RIGHT) -> dict:
    return {'left': ('left.jpg', left, 'image/jpeg'), 'right': ('right.jpg', right, 'image/jpeg')}


def start_guest(client) -> dict:
    r = client.post('/v1/auth/guest')
    assert r.status_code == 200, r.text
    return r.json()


def sign_up(client, email: str = 'saji@example.com', password: str = 'a-long-password', name: str = 'Saji') -> dict:
    r = client.post('/v1/auth/signup', json={'email': email, 'password': password, 'displayName': name})
    assert r.status_code == 200, r.text
    return r.json()


def add_profile(client, name: str = 'Saji', owner: str = 'self', consent: bool = True) -> dict:
    r = client.post('/v1/profiles', json={'name': name, 'owner': owner, 'consent': consent})
    assert r.status_code == 201, r.text
    return r.json()


def run_reading(client, profile_id: str, left: bytes = LEFT, right: bytes = RIGHT):
    """Makes a reading and returns (response, events). The reading itself is the last event."""
    r = client.post('/v1/readings', data={'profileId': profile_id}, files=photo_files(left, right))
    assert r.status_code == 200, r.text
    return r, parse_stream(r.text)


def make_reading(client, profile_id: str) -> dict:
    _, events = run_reading(client, profile_id)
    name, data = events[-1]
    assert name == 'reading', events[-1]
    return data  # type: ignore[return-value]


def add_conversation(client, reading_id: str) -> dict:
    r = client.post(f'/v1/readings/{reading_id}/conversations')
    assert r.status_code == 201, r.text
    return r.json()


def ask(client, conversation_id: str, text: str) -> dict:
    r = client.post(f'/v1/conversations/{conversation_id}/messages', json={'text': text})
    assert r.status_code == 200, r.text
    return r.json()
