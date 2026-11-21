"""Smoke check: does a running Kiro AI server do everything the website needs?

    run.bat smoke                      Windows (start the server first, in another window)
    run.bat smoke --expect-real        the same, and it fails unless the server really reads photos (see below)
    run.bat smoke --expect-gemini      the same, and it fails unless Gemini also wrote the report and a chat answer (see below)
    python scripts/smoke.py            finds the server on ports 8000-8019
    python scripts/smoke.py --url http://127.0.0.1:8100

It needs nothing but Python (no packages). It plays the part of two browsers: one makes a guest session, a profile and
a reading from two made-up palm photos (backend/tests/data), asks the chat two questions and downloads its data; the
other checks that it cannot see any of that. Then everything is deleted again.

The made-up photos are drawings, so they are sent marked as samples (the server gives them a labelled sample reading
whatever mode it runs in). One more check reads YOUR photos: when the server runs the real analysis and the folder
../test-photos holds person1/left.jpg and person1/right.jpg, it makes a reading of them with a third guest and checks
that it is real (not a sample) and that lines were found. --expect-real turns "the server is in sample mode" and "the
photos are missing" from a note into a failure. The photos only go to the server on this computer, and are not kept.

When the server has a Gemini key, that same reading is also written by Gemini, and two chat messages are sent about it (one
Gemini may answer, one that must be turned away without Gemini). --expect-gemini turns "the server writes with the fixed wording"
into a failure: it passes only when Gemini wrote part of the report and the chat answer (it implies --expect-real, because only
real readings go to Gemini). Only the findings, as words, go to Google. The made-up sample photos never do.

It prints one line per check and ends with  RESULT: PASS  or  RESULT: FAIL  (exit code 0 or 1).
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTOS = ROOT / 'backend' / 'tests' / 'data'
REAL_PHOTOS = ROOT.parent / 'test-photos'

STAGES = ['validate', 'resize', 'gray', 'blur', 'contrast', 'edges', 'threshold', 'morphology', 'lines', 'reading']
IMAGE_STAGES = ['gray', 'blur', 'contrast', 'edges', 'threshold', 'morphology']
THEMES = {'personality', 'career', 'financial', 'relationships', 'future'}

if hasattr(sys.stdout, 'reconfigure'):  # a Windows console may not speak UTF-8; never let a print crash the check
    sys.stdout.reconfigure(errors='replace')


# ------------------------------------------------------------------ a tiny browser


class Reply:
    def __init__(self, status: int, headers, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def text(self) -> str:
        return self.body.decode('utf-8', errors='replace')

    def json(self):
        return json.loads(self.text)

    def error_code(self):
        try:
            return self.json()['error']['code']
        except (ValueError, KeyError, TypeError):
            return None


def multipart(fields: dict, files: dict):
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    for name, (filename, content, kind) in files.items():
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f'Content-Type: {kind}\r\n\r\n'
        ).encode() + content + b'\r\n'
    out += f'--{boundary}--\r\n'.encode()
    return bytes(out), f'multipart/form-data; boundary={boundary}'


class Browser:
    """One person's browser. It keeps its own cookies, like a real one."""

    def __init__(self, base: str):
        self.base = base.rstrip('/')
        self.jar = http.cookiejar.CookieJar()
        # ProxyHandler({}): talk to this computer directly, whatever proxy settings Windows or the company has
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.jar))

    def _request(self, method: str, path: str, body=None, kind=None):
        headers = {'Content-Type': kind} if kind else {}
        return urllib.request.Request(self.base + path, data=body, method=method, headers=headers)

    def send(self, method: str, path: str, json_body=None, fields=None, files=None, timeout: int = 60) -> Reply:
        body, kind = None, None
        if json_body is not None:
            body, kind = json.dumps(json_body).encode(), 'application/json'
        elif fields is not None or files is not None:
            body, kind = multipart(fields or {}, files or {})
        try:
            with self.opener.open(self._request(method, path, body, kind), timeout=timeout) as r:
                return Reply(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            return Reply(e.code, e.headers, e.read())

    def get(self, path: str) -> Reply:
        return self.send('GET', path)

    def stream(self, path: str, fields: dict, files: dict, timeout: int = 180, on_event=None):
        """A reading: (status, [(event name, data, seconds since the request)]). Reads the events as they arrive;
        `on_event(name, data)`, when given, is called for each one at that moment (a check that must act in the middle of a reading)."""
        body, kind = multipart(fields, files)
        started = time.monotonic()
        events = []
        try:
            with self.opener.open(self._request('POST', path, body, kind), timeout=timeout) as r:
                name, data = 'message', []
                for raw in r:
                    line = raw.decode('utf-8').rstrip('\r\n')
                    if line == '':
                        if data:
                            events.append((name, json.loads('\n'.join(data)), time.monotonic() - started))
                            if on_event is not None:
                                on_event(name, events[-1][1])
                        name, data = 'message', []
                    elif line.startswith('event:'):
                        name = line[6:].strip()
                    elif line.startswith('data:'):
                        data.append(line[5:].lstrip(' '))
                return r.status, events
        except urllib.error.HTTPError as e:
            return e.code, events


def tiny_png(size: int = 600, grey: int = 128) -> bytes:
    """A flat grey picture (a valid PNG made by hand): sharp enough to open, with no palm in it."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xFFFFFFFF)

    rows = b''.join(b'\x00' + bytes([grey]) * size for _ in range(size))
    header = struct.pack('>IIBBBBB', size, size, 8, 0, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


# ------------------------------------------------------------------ checks


class Skip(Exception):
    """A check that cannot run because an earlier one failed."""


class Run:
    def __init__(self, base: str, expect_real: bool = False, expect_gemini: bool = False):
        self.base = base
        self.expect_gemini = expect_gemini
        self.expect_real = expect_real or expect_gemini  # only real readings are ever sent to Gemini
        self.me = Browser(base)  # the person who makes the data
        self.stranger = Browser(base)  # another person, in another browser
        self.tester = Browser(base)  # a third one, who reads the real photos when there are any
        self.results: list[tuple[str, str, str]] = []
        self.state: dict = {}

    def check(self, name: str, fn) -> None:
        try:
            note = fn() or ''
            self.results.append(('PASS', name, note))
        except Skip as why:
            self.results.append(('SKIP', name, str(why)))
        except AssertionError as why:
            self.results.append(('FAIL', name, str(why) or 'the check did not hold'))
        except Exception as why:  # noqa: BLE001 (a crash in the check itself or a connection problem: show it, keep going)
            self.results.append(('FAIL', name, f'{type(why).__name__}: {why}'))
        print(f'  {self.results[-1][0]:4}  {name}' + (f'   [{self.results[-1][2]}]' if self.results[-1][2] else ''), flush=True)

    def need(self, key: str):
        if key not in self.state:
            raise Skip('needs an earlier check to pass')
        return self.state[key]


def expect(reply: Reply, status: int, what: str = '') -> Reply:
    assert reply.status == status, f'{what or "the server"} answered {reply.status}, expected {status}: {reply.text[:200]}'
    return reply


def find_real_pair(folder: Path) -> tuple[Path, Path] | None:
    """(left photo, right photo) from the first folder under `folder` that holds both. A file whose name has "left" (or
    "right") in it is that hand."""
    if not folder.is_dir():
        return None
    for directory in [folder, *sorted(p for p in folder.rglob('*') if p.is_dir())]:
        images = [p for p in sorted(directory.iterdir()) if p.is_file() and p.suffix.lower() in ('.jpg', '.jpeg', '.png')]
        lefts = [p for p in images if 'left' in p.name.lower() and 'right' not in p.name.lower()]
        rights = [p for p in images if 'right' in p.name.lower() and 'left' not in p.name.lower()]
        if lefts and rights:
            return lefts[0], rights[0]
    return None


def writer_and_chat(tester: Browser, reading: dict, health: dict, expect_gemini: bool) -> str:
    """Who wrote the real reading's words, and (when the server has a Gemini key) a chat about it. Returns a short description."""
    meta = reading['meta']
    gemini_on = health.get('writer') == 'gemini'
    if expect_gemini:
        assert meta['provider'] == 'gemini', f'--expect-gemini was given, but Gemini wrote none of the report: {meta.get("note") or "no reason given"}'
    if not gemini_on:
        return 'words: the knowledge base (no Gemini key on this server)'
    assert meta['provider'] in ('gemini', 'knowledge-base'), f'the report says it was written by {meta["provider"]!r}'
    wrote = f'report by {meta["provider"]}' + (f' ({meta["model"]})' if meta['provider'] == 'gemini' else f', because: {meta.get("note") or "no reason given"}')
    convo = expect(tester.send('POST', f'/v1/readings/{reading["id"]}/conversations'), 201, 'POST /v1/readings/{id}/conversations (real reading)').json()
    path = f'/v1/conversations/{convo["id"]}/messages'
    answer = expect(tester.send('POST', path, json_body={'text': 'What does my heart line say?'}), 200, 'POST messages (real reading)').json()['assistant']
    assert answer['text'] and answer['role'] == 'assistant', 'the assistant said nothing'
    source = answer.get('source')
    if expect_gemini:
        assert source == 'gemini', f'--expect-gemini was given, but the chat answer came from {source or "the fixed wording"}: {answer.get("note") or "no reason given"}'
    refused = expect(tester.send('POST', path, json_body={'text': 'Will I get married?'}), 200, 'POST messages (a marriage question)').json()['assistant']
    assert refused.get('flags', {}).get('boundary') == 'relationship' and 'source' not in refused, 'a marriage question was not turned away with the fixed wording'
    return f'{wrote}; chat answer by {source or "the fixed wording"}' + (f' ({answer["note"]})' if answer.get('note') else '')


def run_checks(base: str, expect_real: bool = False, expect_gemini: bool = False) -> bool:
    run = Run(base, expect_real, expect_gemini)
    me, stranger = run.me, run.stranger
    left = (PHOTOS / 'sample-left.jpg').read_bytes()
    right = (PHOTOS / 'sample-right.jpg').read_bytes()

    def server_is_up():
        body = expect(me.get('/v1/health'), 200, 'GET /v1/health').json()
        assert body.get('ok') is True and body.get('service') == 'kiro-ai', f'unexpected health answer {body}'
        run.state['health'] = body
        writer = body.get('writer', 'knowledge-base') + (f" ({body['writerModel']})" if body.get('writerModel') else '')
        return f"version {body.get('version')}, analysis: {body.get('analysis')}, writer: {writer}, accounts kept in: {body.get('storage', 'memory')}"

    def answers_are_not_cached():
        for path in ('/v1/health', '/v1/session', '/v1/no-such-thing'):
            assert me.get(path).headers.get('Cache-Control') == 'no-store', f'{path} can be cached'

    def nobody_is_signed_in():
        assert expect(me.get('/v1/session'), 200, 'GET /v1/session').json() == {'session': None}
        expect(me.get('/v1/profiles'), 401, 'GET /v1/profiles without a session')

    def guest_session():
        reply = expect(me.send('POST', '/v1/auth/guest'), 200, 'POST /v1/auth/guest')
        body = reply.json()
        assert body.get('kind') == 'guest' and str(body.get('guestId', '')).startswith('gst_'), body
        assert body['expiresAt'] > time.time() * 1000, 'the session is already over'
        assert 'httponly' in reply.headers.get('Set-Cookie', '').lower(), 'the session cookie is not httpOnly'
        run.state['guest'] = body
        assert me.get('/v1/session').json() == {'session': body}, 'GET /v1/session does not return the same session'
        return f"ends in {round((body['expiresAt'] - time.time() * 1000) / 60000)} minutes"

    def profile_rules():
        run.need('guest')
        bad = me.send('POST', '/v1/profiles', json_body={'name': '   ', 'owner': 'self', 'consent': True})
        assert bad.status == 422 and bad.error_code() == 'invalid', f'an empty name answered {bad.status}'
        no_consent = me.send('POST', '/v1/profiles', json_body={'name': 'Nimal', 'owner': 'other', 'consent': False})
        assert no_consent.status == 422, "a profile for someone else was accepted without that person's consent"
        made = expect(me.send('POST', '/v1/profiles', json_body={'name': 'Smoke Test', 'owner': 'self', 'consent': True}), 201, 'POST /v1/profiles').json()
        assert made['name'] == 'Smoke Test' and made['id'].startswith('prf_'), made
        twin = me.send('POST', '/v1/profiles', json_body={'name': 'smoke test', 'owner': 'self', 'consent': True})
        assert twin.status == 422, 'two profiles with the same name (ignoring case) were accepted'
        run.state['profile'] = made

    def photo_checks():
        run.need('guest')
        for side, data in (('left', left), ('right', right)):
            result = expect(
                # "sample": 1 says this is one of the website's drawn sample photos, which a hand finder cannot read
                me.send('POST', '/v1/photos/validate', fields={'side': side, 'sample': '1'}, files={'photo': (f'{side}.jpg', data, 'image/jpeg')}),
                200,
                'POST /v1/photos/validate',
            ).json()
            ids = [c['id'] for c in result['checks']]
            assert ids == ['file_type', 'integrity', 'dimensions', 'blur', 'lighting', 'palm_visible'], f'the six checks came as {ids}'
            assert result['ok'] is True, f'the {side} sample photo was refused: {[c for c in result["checks"] if c["status"] == "fail"]}'
        bad = expect(
            me.send('POST', '/v1/photos/validate', fields={'side': 'left'}, files={'photo': ('wall.png', tiny_png(), 'image/png')}),
            200,
            'POST /v1/photos/validate (flat grey picture)',
        ).json()
        assert bad['ok'] is False, 'a flat grey picture was accepted as a palm photo'
        not_an_image = me.send('POST', '/v1/photos/validate', fields={'side': 'left'}, files={'photo': ('notes.txt', b'hello', 'text/plain')})
        assert not_an_image.status in (200, 422) and (not_an_image.status == 422 or not_an_image.json()['ok'] is False), 'a text file was accepted as a photo'

    def reading_stream():
        profile = run.need('profile')
        fields = {'profileId': profile['id'], 'leftSample': '1', 'rightSample': '1'}
        status, events = me.stream('/v1/readings', fields, {'left': ('left.jpg', left, 'image/jpeg'), 'right': ('right.jpg', right, 'image/jpeg')})
        assert status == 200, f'POST /v1/readings answered {status}'
        names = [name for name, _, _ in events]
        assert names and names[-1] == 'reading', f'the stream did not end with the reading: {names[-3:]}'
        assert 'error' not in names, f'the stream carried an error: {[d for n, d, _ in events if n == "error"]}'
        done = [d['stage'] for n, d, _ in events if n == 'stage' and d['state'] == 'done']
        assert done == STAGES, f'the steps came as {done}'
        previews = {d['stage']: d['previews'] for n, d, _ in events if n == 'stage' and d.get('previews')}
        assert list(previews) == IMAGE_STAGES, f'pictures came for {list(previews)}'
        for stage, pair in previews.items():
            for hand in ('left', 'right'):
                assert pair[hand].startswith('data:image/jpeg;base64,') and len(pair[hand]) > 1500, f'the {stage} picture for the {hand} hand is not a picture'
        reading = events[-1][1]
        run.state['reading'] = reading
        first, last = events[0][2], events[-1][2]
        return f'{len(events)} events, first after {first:.1f}s, reading after {last:.1f}s'

    def reading_content():
        reading = run.need('reading')
        for hand in ('left', 'right'):
            analysis = reading['hands'][hand]
            assert [f['id'] for f in analysis['features']] == ['heart', 'head', 'life', 'fate', 'sun'], f'{hand} hand features'
            assert analysis['palmShape'] and 'otherCreases' in analysis and analysis['outline'], f'{hand} hand is missing hand shape, other creases or outline'
        report = reading['report']
        assert {t['themeId'] for t in report['themes']} == THEMES, f'themes: {[t["themeId"] for t in report["themes"]]}'
        assert len(report['sections']) == 5 and report['shape'] and report['disclaimer'] and report['uncertainty'], 'the report is missing a part'
        assert reading['meta']['provider'] == 'sample', 'the reading does not say it is a sample reading'
        return 'themes, per-line sections, hand shape, uncertainty and disclaimer are all there'

    def reading_is_saved():
        reading = run.need('reading')
        listed = expect(me.get(f'/v1/readings?profileId={run.state["profile"]["id"]}'), 200, 'GET /v1/readings').json()
        assert [r['id'] for r in listed] == [reading['id']], 'the new reading is not in the list'
        fetched = expect(me.get(f'/v1/readings/{reading["id"]}'), 200, 'GET /v1/readings/{id}').json()
        assert fetched['id'] == reading['id'] and fetched['report'] == reading['report'], 'the saved reading differs from the streamed one'
        profiles = me.get('/v1/profiles').json()
        assert profiles[0]['readingCount'] == 1, 'the profile does not count its reading'

    def real_photos():
        health = run.need('health')
        if health.get('analysis') != 'real':
            assert not run.expect_real, (
                'the server is in SAMPLE mode, but --expect-real was given. Run  run.bat models  (it downloads the hand model), '
                'then start the server again.'
            )
            return 'not run: this server has no hand model, so every reading it makes is a labelled sample'
        if run.expect_gemini:
            assert health.get('writer') == 'gemini', 'the server has no Gemini key. Put GEMINI_API_KEY in backend\\.env, then start the server again.'
        pair = find_real_pair(REAL_PHOTOS)
        if pair is None:
            assert not run.expect_real, f'--expect-real was given, but there are no photos in {REAL_PHOTOS}. Put person1\\left.jpg and person1\\right.jpg there.'
            return f'not run: no left and right photos in {REAL_PHOTOS}'
        photos = {'left': pair[0].read_bytes(), 'right': pair[1].read_bytes()}
        tester = run.tester
        expect(tester.send('POST', '/v1/auth/guest'), 200, 'the third browser starting a guest session')
        try:
            profile = expect(tester.send('POST', '/v1/profiles', json_body={'name': 'Real Photos', 'owner': 'self', 'consent': True}), 201, 'POST /v1/profiles').json()
            palm = {}
            for side in ('left', 'right'):
                files = {'photo': (f'{side}.jpg', photos[side], 'image/jpeg')}
                verdict = expect(tester.send('POST', '/v1/photos/validate', fields={'side': side}, files=files), 200, f'POST /v1/photos/validate ({side} photo)').json()
                assert verdict['ok'] is True, f'the {side} photo was refused: {[c["message"] for c in verdict["checks"] if c["status"] == "fail"]}'
                palm[side] = next(c for c in verdict['checks'] if c['id'] == 'palm_visible')['status']
            files = {side: (f'{side}.jpg', photos[side], 'image/jpeg') for side in ('left', 'right')}
            status, events = tester.stream('/v1/readings', {'profileId': profile['id']}, files)
            assert status == 200, f'POST /v1/readings answered {status}'
            names = [name for name, _, _ in events]
            assert names and names[-1] == 'reading' and 'error' not in names, f'the stream ended with {names[-3:]}'
            reading = events[-1][1]
            assert reading['meta']['mock'] is False and reading['meta']['provider'] != 'sample', 'a reading of real photos is still marked as a sample'
            said = {d['stage']: d.get('detail') for n, d, _ in events if n == 'stage' and d['state'] == 'done'}
            assert not str(said.get('lines', '')).startswith('Sample result'), f'the lines step says: {said.get("lines")}'
            counts = {}
            for hand in ('left', 'right'):
                features = reading['hands'][hand]['features']
                for f in features:
                    assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in f['path']), f'{hand} hand, {f["id"]}: a line leaves the photo'
                    assert (f['status'] == 'not_visible') == (f['path'] == []), f'{hand} hand, {f["id"]}: the status and the line disagree'
                found = [f['status'] for f in features]
                counts[hand] = {word: found.count(word) for word in ('detected', 'uncertain', 'not_visible')}
            assert sum(c['detected'] for c in counts.values()) >= 1, f'no line was found on either real hand: {counts}'
            assert reading['hands']['left']['palmShape']['status'] != 'not_visible' or reading['hands']['right']['palmShape']['status'] != 'not_visible', 'the shape of neither hand was measured'
            summary = '; '.join(f'{hand}: {c["detected"]} detected, {c["uncertain"]} uncertain, {c["not_visible"]} not visible' for hand, c in counts.items())
            words = writer_and_chat(tester, reading, health, run.expect_gemini)
            return f'{summary} (palm checks: {palm["left"]}, {palm["right"]}); {said.get("lines")}; {words}'
        finally:
            tester.send('DELETE', '/v1/account/data')
            tester.send('POST', '/v1/auth/signout')

    def chat():
        reading = run.need('reading')
        convo = expect(me.send('POST', f'/v1/readings/{reading["id"]}/conversations'), 201, 'POST /v1/readings/{id}/conversations').json()
        run.state['conversation'] = convo
        first = expect(me.send('POST', f'/v1/conversations/{convo["id"]}/messages', json_body={'text': 'What does my heart line say?'}), 200, 'POST messages').json()
        assert first['assistant']['text'] and first['assistant']['role'] == 'assistant', 'the assistant said nothing'
        assert 'hand' in first['assistant']['text'].lower(), 'the answer does not talk about the hands'
        assert 'source' not in first['assistant'], f'a sample reading was answered by {first["assistant"].get("source")}: samples must never go to Gemini'
        second = expect(me.send('POST', f'/v1/conversations/{convo["id"]}/messages', json_body={'text': 'Will I get married?'}), 200, 'POST messages').json()
        assert second['assistant']['flags']['boundary'] == 'relationship', f'a marriage question was not turned away: {second["assistant"].get("flags")}'
        listed = me.get(f'/v1/conversations?readingId={reading["id"]}').json()
        assert listed[0]['title'] == 'What does my heart line say?', f'the chat title is {listed[0]["title"]!r}'
        too_long = me.send('POST', f'/v1/conversations/{convo["id"]}/messages', json_body={'text': 'x' * 501})
        assert too_long.status == 422 and too_long.error_code() == 'invalid', f'a 501-character message answered {too_long.status}'

    def one_person_cannot_see_anothers_data():
        reading, convo, profile = run.need('reading'), run.need('conversation'), run.need('profile')
        expect(stranger.send('POST', '/v1/auth/guest'), 200, 'the second browser starting a guest session')
        assert stranger.get('/v1/profiles').json() == [], 'a new guest session is not empty'
        for path in (f'/v1/readings/{reading["id"]}', f'/v1/conversations/{convo["id"]}'):
            r = stranger.get(path)
            assert r.status == 404 and r.error_code() == 'not_found', f'GET {path} answered {r.status} to someone else'
        # asking for the list of someone else's profile shows nothing, exactly as for a profile that does not exist
        for path in (f'/v1/readings?profileId={profile["id"]}', f'/v1/conversations?readingId={reading["id"]}', '/v1/readings?profileId=prf_0000000000000000'):
            r = stranger.get(path)
            assert r.status == 200 and r.json() == [], f'GET {path} showed {r.text[:100]} to someone else'
        for method, path in (('DELETE', f'/v1/profiles/{profile["id"]}'), ('DELETE', f'/v1/readings/{reading["id"]}')):
            r = stranger.send(method, path)
            assert r.status == 404, f'{method} {path} answered {r.status} to someone else'
        r = stranger.send('POST', f'/v1/conversations/{convo["id"]}/messages', json_body={'text': 'hello'})
        assert r.status == 404, f'someone else could write into this chat ({r.status})'
        assert len(me.get('/v1/profiles').json()) == 1, 'the owner lost data to a stranger'
        nobody = Browser(run.base)
        assert nobody.get('/v1/profiles').status == 401, 'data is readable with no session at all'

    def errors_share_one_shape():
        r = me.get('/v1/no/such/thing')
        assert r.status == 404 and r.json() == {'error': {'code': 'not_found', 'message': 'That address does not exist.'}}, r.text[:200]
        r = me.send('POST', '/v1/auth/signin', json_body={'email': 'nobody@example.com', 'password': 'not-a-password'})
        assert r.status == 401 and r.error_code() == 'unauthorised', f'a wrong sign-in answered {r.status}'

    def export_and_delete():
        run.need('reading')
        bundle = expect(me.get('/v1/account/export'), 200, 'GET /v1/account/export').json()
        assert len(bundle['profiles']) == 1 and len(bundle['readings']) == 1 and len(bundle['conversations']) == 1, 'the download is missing something'
        assert 'data:image' not in json.dumps(bundle), 'the download contains photos or pictures of photos'
        gone = expect(me.send('DELETE', '/v1/account/data'), 200, 'DELETE /v1/account/data').json()
        assert gone == {'profiles': 1, 'readings': 1, 'conversations': 1, 'messages': 4}, f'deleted {gone}'
        assert me.get('/v1/profiles').json() == [], 'data is still there after deleting it'

    def sign_out():
        run.need('guest')
        expect(me.send('POST', '/v1/auth/signout'), 204, 'POST /v1/auth/signout')
        assert me.get('/v1/session').json() == {'session': None}, 'still signed in'
        expect(stranger.send('POST', '/v1/auth/signout'), 204, 'the second browser signing out')

    def website_is_served():
        page = me.get('/')
        assert page.status == 200, f'GET / answered {page.status}. Has the website been built? (run.bat builds it)'
        assert '<div id="root">' in page.text, 'GET / is not the website'
        assert "default-src 'self'" in page.headers.get('Content-Security-Policy', ''), 'the website carries no content security policy'
        assert 'text/html' in page.headers.get('Content-Type', ''), f'the page is {page.headers.get("Content-Type")}'
        for route in ('/app/new', '/signin', '/app/readings/rd_0000/chat'):
            r = me.get(route)
            assert r.status == 200 and '<div id="root">' in r.text, f'the page address {route} did not open the app'
        for attributes, body in re.findall(r'<script\b([^>]*)>(.*?)</script>', page.text, flags=re.DOTALL):
            assert 'src=' in attributes and not body.strip(), "the page has an inline script, which the security policy blocks (the theme would flash on every load)"
        scripts = re.findall(r'src="(/assets/[^"]+\.js)"', page.text)
        styles = re.findall(r'href="(/assets/[^"]+\.css)"', page.text)
        assert scripts and styles, 'the page names no script or style file'
        js = me.get(scripts[0])
        assert js.status == 200 and 'javascript' in js.headers.get('Content-Type', ''), f'the script is served as {js.headers.get("Content-Type")}: the browser would refuse to run it'
        css = me.get(styles[0])
        assert css.status == 200 and 'text/css' in css.headers.get('Content-Type', ''), f'the stylesheet is served as {css.headers.get("Content-Type")}'
        missing = me.get('/assets/does-not-exist-123.js')
        assert missing.status == 404 and '<div' not in missing.text, 'a missing script is answered with the web page'

    def website_is_the_server_build():
        reply = me.get('/build-info.json')
        assert reply.status == 200, 'the website has no build-info.json. Rebuild it:  run.bat --rebuild'
        info = reply.json()
        assert info.get('mock') is False, 'this website was built with sample data, so it never calls the server. Rebuild it:  run.bat --rebuild'
        return f"mode {info.get('mode')}, built {info.get('builtAt')}"

    print(f'\nKiro AI smoke check against {base}\n')
    run.check('the server is up', server_is_up)
    run.check('every answer from /v1 is marked "do not cache"', answers_are_not_cached)
    run.check('nobody is signed in at first, and /v1/profiles says so', nobody_is_signed_in)
    run.check('a guest session starts, with an httpOnly cookie', guest_session)
    run.check('profile rules: empty name, no consent, duplicate name', profile_rules)
    run.check('photo checks accept two good photos and refuse bad files', photo_checks)
    run.check('a reading streams its ten steps and six pictures, then arrives', reading_stream)
    run.check('the reading holds both hands, themes, per-line sections and uncertainty', reading_content)
    run.check('the reading is saved, listed and fetchable', reading_is_saved)
    run.check('your own photos, when the server reads photos for real, get a real reading', real_photos)
    run.check('chat answers, turns a marriage question away, and limits message length', chat)
    run.check("one person cannot see, change or delete another person's data", one_person_cannot_see_anothers_data)
    run.check('errors all have the same shape', errors_share_one_shape)
    run.check('the data download works and holds no photos; deleting it works', export_and_delete)
    run.check('signing out ends the guest session', sign_out)
    run.check('the website is served from this same address, with the right file types', website_is_served)
    run.check('the website is the build that talks to this server, not the sample-data one', website_is_the_server_build)

    passed = sum(1 for status, _, _ in run.results if status == 'PASS')
    failed = [(name, note) for status, name, note in run.results if status == 'FAIL']
    skipped = sum(1 for status, _, _ in run.results if status == 'SKIP')
    print(f'\n{passed} of {len(run.results)} checks passed' + (f', {skipped} skipped' if skipped else '') + '.')
    for name, note in failed:
        print(f'  FAILED: {name}\n          {note}')
    ok = not failed and not skipped
    print(f'\nRESULT: {"PASS" if ok else "FAIL"}')
    return ok


# ------------------------------------------------------------------ finding the server


def kiro_at(base: str) -> bool:
    try:
        reply = Browser(base).send('GET', '/v1/health', timeout=3)
        return reply.status == 200 and reply.json().get('service') == 'kiro-ai'
    except (OSError, ValueError):
        return False


def find_server(asked: str | None) -> str | None:
    if asked:
        return asked.rstrip('/') if kiro_at(asked) else None
    for port in range(8000, 8020):
        base = f'http://127.0.0.1:{port}'
        if kiro_at(base):
            return base
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description='Checks a running Kiro AI server.')
    parser.add_argument('--url', help='where the server is, for example http://127.0.0.1:8100 (default: look on ports 8000-8019)')
    parser.add_argument('--expect-real', action='store_true', help='fail unless the server reads photos for real and your own photos (..\\test-photos) were read')
    parser.add_argument('--expect-gemini', action='store_true', help='fail unless Gemini also wrote the report and a chat answer (implies --expect-real)')
    args = parser.parse_args()
    for name in ('sample-left.jpg', 'sample-right.jpg'):
        if not (PHOTOS / name).is_file():
            print(f'Cannot find {PHOTOS / name}. It comes with the project (backend/tests/data).')
            return 1
    base = find_server(args.url)
    if base is None:
        print('No Kiro AI server was found' + (f' at {args.url}' if args.url else ' on ports 8000-8019') + '.')
        print('Start it first (double-click run.bat, and leave that window open), then run this again.')
        return 1
    return 0 if run_checks(base, args.expect_real, args.expect_gemini) else 1


if __name__ == '__main__':
    sys.exit(main())
