"""Serving the built website from the same address as the API, and the errors every route shares."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from helpers import add_profile, start_guest

from app.core.config import PROJECT_DIR, Settings
from app.main import create_app


def test_the_home_page_and_client_side_routes_get_the_app(client):
    for path in ('/', '/signin', '/start', '/app/new', '/app/readings/rd_9', '/app/readings/rd_9/chat'):
        r = client.get(path)
        assert r.status_code == 200, path
        assert '<div id="root">' in r.text and r.headers['content-type'].startswith('text/html'), path
        assert r.headers['cache-control'] == 'no-cache'


def test_real_files_are_served_as_they_are_and_cached_for_a_long_time(client):
    r = client.get('/assets/app-123.js')
    assert r.status_code == 200 and r.text == 'console.log("hi")'
    assert 'immutable' in r.headers['cache-control'] and 'max-age=31536000' in r.headers['cache-control']
    assert client.get('/favicon.svg').status_code == 200


def test_scripts_and_styles_get_the_right_content_type_whatever_the_computer_believes(client, site_dir):
    """Windows can have a registry entry that calls .js "text/plain"; the browser then refuses to run the script."""
    import mimetypes

    (site_dir / 'assets' / 'app-123.css').write_text('body{margin:0}')
    (site_dir / 'assets' / 'font-1.woff2').write_bytes(b'wOF2')
    saved = dict(mimetypes.types_map)
    try:
        mimetypes.add_type('text/plain', '.js')
        mimetypes.add_type('text/plain', '.css')
        mimetypes.add_type('text/plain', '.svg')
        assert client.get('/assets/app-123.js').headers['content-type'].startswith('text/javascript')
        assert client.get('/assets/app-123.css').headers['content-type'].startswith('text/css')
        assert client.get('/favicon.svg').headers['content-type'] == 'image/svg+xml'
        assert client.get('/assets/font-1.woff2').headers['content-type'] == 'font/woff2'
    finally:
        mimetypes.types_map.clear()
        mimetypes.types_map.update(saved)


def test_a_missing_asset_is_a_404_not_the_app(client):
    r = client.get('/assets/old-hash.js')
    assert r.status_code == 404 and '<div' not in r.text  # a script request must not be answered with HTML


def test_files_outside_the_site_folder_cannot_be_reached(client):
    for path in ('/../../etc/passwd', '/%2e%2e/%2e%2e/etc/passwd', '/assets/../../../etc/passwd', '/..%2f..%2fetc/passwd'):
        r = client.get(path)
        assert 'root:' not in r.text, path
        assert r.status_code in (200, 400, 404), path
        if r.status_code == 200:
            assert '<div id="root">' in r.text  # the app, never the file


def test_the_website_carries_a_content_security_policy_the_api_does_not_need(client):
    csp = client.get('/').headers['content-security-policy']
    for part in ("default-src 'self'", "img-src 'self' data: blob:", "script-src 'self'", "object-src 'none'", "frame-ancestors 'none'"):
        assert part in csp
    assert client.get('/').headers['x-content-type-options'] == 'nosniff'
    assert 'content-security-policy' not in client.get('/v1/health').headers


def test_unknown_api_addresses_are_json_404s_never_the_app(client):
    for method in ('get', 'post', 'delete'):
        r = getattr(client, method)('/v1/no/such/thing')
        assert r.status_code == 404 and r.json() == {'error': {'code': 'not_found', 'message': 'That address does not exist.'}}


def test_a_missing_build_says_so_instead_of_failing(tmp_path):
    c = TestClient(create_app(Settings(env='test', site_dir=tmp_path / 'nothing', stage_pause_ms=0)))
    r = c.get('/')
    assert r.status_code == 503 and 'has not been built' in r.text
    assert c.get('/v1/health').status_code == 200  # the API still works


def test_the_wrong_method_is_an_error_in_the_usual_body(client):
    start_guest(client)
    r = client.put('/v1/profiles', json={})
    assert r.status_code in (404, 405) and r.json()['error']['message']


def test_every_error_has_the_one_body_the_website_reads(client):
    start_guest(client)
    add_profile(client)
    answers = [
        client.get('/v1/readings/rd_nope'),  # not_found
        client.post('/v1/profiles', json={'name': ''}),  # invalid (validation)
        client.post('/v1/profiles', json={'name': 'Saji', 'owner': 'self'}),  # invalid (duplicate)
        client.post('/v1/profiles', content=b'{not json', headers={'content-type': 'application/json'}),  # invalid (broken JSON)
        TestClient(client.app).get('/v1/profiles'),  # unauthorised
    ]
    for r in answers:
        body = r.json()
        assert set(body) == {'error'} and set(body['error']) == {'code', 'message'}, r.text
        assert body['error']['code'] in ('invalid', 'unauthorised', 'forbidden', 'not_found', 'expired', 'processing_failed')
        assert body['error']['message'] and len(body['error']['message']) < 200
        assert r.headers['cache-control'] == 'no-store'
        assert 'Traceback' not in r.text and 'pydantic' not in r.text.lower() and 'loc' not in body['error']


def test_a_crash_is_a_500_in_the_same_body_without_details(app, client, monkeypatch):
    from app.api import profiles

    def boom(*args, **kwargs):
        raise RuntimeError('secret internal detail')

    start_guest(client)
    monkeypatch.setattr(profiles, 'check_name', boom)
    quiet = TestClient(app, raise_server_exceptions=False)
    quiet.cookies.update(client.cookies)
    r = quiet.post('/v1/profiles', json={'name': 'Saji', 'owner': 'self', 'consent': True})
    assert r.status_code == 500 and r.json()['error']['code'] == 'processing_failed'
    assert 'secret internal detail' not in r.text and r.headers['cache-control'] == 'no-store'


def test_the_health_check_needs_no_session_and_says_the_analysis_is_a_sample_and_who_writes(client):
    r = client.get('/v1/health')
    assert r.status_code == 200 and r.json() == {'ok': True, 'service': 'kiro-ai', 'version': '0.1.0', 'analysis': 'sample', 'writer': 'knowledge-base', 'storage': 'memory'}


def test_cookies_are_secure_only_when_asked(site_dir):
    secure = TestClient(create_app(Settings(env='production', site_dir=site_dir, stage_pause_ms=0, cookie_secure=True)), base_url='https://testserver')
    cookie = secure.post('/v1/auth/guest').headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=lax' in cookie
    assert secure.get('/v1/docs').status_code == 404  # the interactive docs are for development only


def test_the_real_page_has_no_inline_script_because_the_policy_would_block_it():
    """index.html is the page the browser opens. `script-src 'self'` refuses inline scripts, so every script needs a src."""
    page = (PROJECT_DIR / 'index.html').read_text(encoding='utf-8')
    scripts = re.findall(r'<script\b([^>]*)>(.*?)</script>', page, flags=re.DOTALL)
    assert scripts, 'index.html has no scripts at all?'
    for attributes, body in scripts:
        assert 'src=' in attributes and not body.strip(), f'an inline script would be blocked: <script{attributes}>{body[:40]}'
    for source in re.findall(r'<script[^>]*\bsrc="/([^"]+)"', page):
        if not source.startswith('src/'):  # /src/main.tsx is bundled by the build; anything else must be a file in public/
            assert (PROJECT_DIR / 'public' / source).is_file(), f'public/{source} is missing'
