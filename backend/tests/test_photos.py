"""POST /photos/validate: six checks, always 200 for a bad photo, an error only for a broken request."""

from __future__ import annotations

import cv2
import photos as P
import pytest
from helpers import LEFT, start_guest

ORDER = ['file_type', 'integrity', 'dimensions', 'blur', 'lighting', 'palm_visible']
LABELS = ['File type', 'File opens', 'Size', 'Focus', 'Lighting', 'Palm in view']


@pytest.fixture
def guest(client):
    start_guest(client)
    return client


def validate(client, data: bytes, side: str = 'left', name: str = 'photo.jpg'):
    return client.post('/v1/photos/validate', data={'side': side}, files={'photo': (name, data, 'image/jpeg')})


def statuses(r) -> dict[str, str]:
    return {c['id']: c['status'] for c in r.json()['checks']}


def test_a_good_photo_passes_all_six_checks_in_order(guest):
    r = validate(guest, LEFT)
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True and body['side'] == 'left' and (body['width'], body['height']) == (800, 1000)
    assert [c['id'] for c in body['checks']] == ORDER
    assert [c['label'] for c in body['checks']] == LABELS
    assert set(statuses(r).values()) == {'pass'}
    assert all(c['message'] for c in body['checks'])


def test_png_is_accepted_too(guest):
    assert validate(guest, P.png(P.palm()), name='palm.png').json()['ok'] is True


def test_the_type_is_decided_by_the_first_bytes_not_by_the_name(guest):
    # a text file called photo.jpg is not a photo, and a photo called notes.txt still is one
    assert statuses(validate(guest, b'just some text', name='photo.jpg'))['file_type'] == 'fail'
    assert validate(guest, LEFT, name='notes.txt').json()['ok'] is True
    # GIF and BMP are refused even though OpenCV could open them
    gif = b'GIF89a' + b'\x00' * 50
    assert statuses(validate(guest, gif))['file_type'] == 'fail'
    _, bmp = cv2.imencode('.bmp', P.palm())
    assert statuses(validate(guest, bmp.tobytes()))['file_type'] == 'fail'


def test_a_corrupt_photo_is_a_failed_check_not_an_http_error(guest):
    r = validate(guest, LEFT[:4000])
    assert r.status_code == 200
    assert r.json()['ok'] is False and statuses(r)['integrity'] == 'fail'
    assert [c['id'] for c in r.json()['checks']] == ORDER  # still all six


def test_blurry_dark_small_and_not_a_palm(guest):
    palm = P.palm()
    assert statuses(validate(guest, P.jpeg(P.blurry(palm))))['blur'] == 'fail'
    assert statuses(validate(guest, P.jpeg(P.dark(palm))))['lighting'] == 'fail'
    assert statuses(validate(guest, P.jpeg(cv2.resize(palm, (300, 375)))))['dimensions'] == 'fail'
    assert statuses(validate(guest, P.jpeg(P.not_a_palm())))['palm_visible'] == 'fail'
    small = validate(guest, P.jpeg(cv2.resize(palm, (700, 875))))
    assert statuses(small)['dimensions'] == 'warn' and small.json()['ok'] is True  # a warning never blocks


def test_every_failing_check_says_what_to_do_next(guest):
    for image, check, word in [
        (P.blurry(P.palm()), 'blur', 'focus'),
        (P.dark(P.palm()), 'lighting', 'daylight'),
        (P.not_a_palm(), 'palm_visible', 'palm'),
    ]:
        message = next(c['message'] for c in validate(guest, P.jpeg(image)).json()['checks'] if c['id'] == check)
        assert word in message.lower(), message


def test_a_picture_with_too_many_pixels_is_refused_before_it_is_opened(app, client):
    start_guest(client)
    from app.cv.images import check_photo

    result = check_photo(LEFT, 'left', max_pixels=500_000)
    assert not result.ok and result.work is None and result.measures is None  # never decoded
    assert next(c for c in result.result.checks if c.id == 'dimensions').status == 'fail'
    assert 'megapixels' in next(c for c in result.result.checks if c.id == 'dimensions').message


def with_exif_rotation(jpeg_bytes: bytes, orientation: int = 6) -> bytes:
    """The same JPEG with an EXIF tag that says "turn me a quarter turn" (what a phone writes when held sideways)."""
    import struct

    tiff = b'MM\x00*\x00\x00\x00\x08' + b'\x00\x01' + b'\x01\x12\x00\x03\x00\x00\x00\x01' + struct.pack('>H', orientation) + b'\x00\x00' + b'\x00\x00\x00\x00'
    body = b'Exif\x00\x00' + tiff
    return jpeg_bytes[:2] + b'\xff\xe1' + struct.pack('>H', len(body) + 2) + body + jpeg_bytes[2:]


def test_the_camera_rotation_is_not_applied_again(guest):
    # the browser already turned the picture upright, so the server must read the pixels exactly as they are stored
    rotated = with_exif_rotation(LEFT)
    assert rotated != LEFT
    r = validate(guest, rotated)
    assert r.status_code == 200 and r.json()['ok'] is True
    assert (r.json()['width'], r.json()['height']) == (800, 1000)  # not swapped to 1000 x 800


def test_a_broken_request_is_an_error(guest):
    assert guest.post('/v1/photos/validate', data={'side': 'left'}).status_code == 422  # no photo
    assert guest.post('/v1/photos/validate', files={'photo': ('p.jpg', LEFT, 'image/jpeg')}).status_code == 422  # no side
    r = guest.post('/v1/photos/validate', data={'side': 'middle'}, files={'photo': ('p.jpg', LEFT, 'image/jpeg')})
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid' and 'left or right' in r.json()['error']['message']
    r = guest.post('/v1/photos/validate', data={'side': 'left'}, files={'photo': ('p.jpg', b'', 'image/jpeg')})
    assert r.status_code == 422 and 'empty' in r.json()['error']['message']
    assert guest.post('/v1/photos/validate', json={'side': 'left'}).status_code == 422  # not a form at all


def test_a_photo_over_the_size_limit_is_refused(app, client):
    start_guest(client)
    app.state.settings = app.state.settings.with_(max_photo_bytes=100_000)
    r = validate(client, LEFT)  # about 200 KB
    assert r.status_code == 422 and 'larger than' in r.json()['error']['message']


def test_a_request_over_the_total_limit_is_refused_before_it_is_read(app):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    small = create_app(Settings(env='test', site_dir=app.state.settings.site_dir, stage_pause_ms=0, max_photo_bytes=50_000))
    c = TestClient(small)
    start_guest(c)
    r = c.post('/v1/photos/validate', data={'side': 'left'}, files={'photo': ('p.jpg', b'x' * 3_000_000, 'image/jpeg')})
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid' and 'too large' in r.json()['error']['message']


def test_it_needs_a_session(client):
    r = validate(client, LEFT)
    assert r.status_code == 401 and r.json()['error']['code'] == 'unauthorised'
