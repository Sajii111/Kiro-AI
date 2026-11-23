"""scripts/fetch_models.py, the hand-model downloader. A small web server on this computer stands in for Google's."""

from __future__ import annotations

import importlib.util
import io
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'fetch_models.py'


@pytest.fixture(scope='module')
def fetch():
    spec = importlib.util.spec_from_file_location('fetch_models', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_bundle(names=('hand_detector.tflite', 'hand_landmarks_detector.tflite'), size=600_000) -> bytes:
    """A zip of the same shape as the real .task file: two or more uncompressed .tflite models."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as bundle:
        for name in names:
            bundle.writestr(name, bytes(size))
    return buffer.getvalue()


class Server:
    """Answers GET requests from a table of {path: (status, content type, body)} and remembers what was asked."""

    def __init__(self, routes: dict[str, tuple[int, str, bytes]]):
        self.asked: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.asked.append(self.path)
                status, content_type, body = routes.get(self.path, (404, 'text/plain', b'not here'))
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve(monkeypatch):
    """Starts a server for one test. Requests to this computer never go through a proxy."""
    for name in ('no_proxy', 'NO_PROXY'):
        monkeypatch.setenv(name, '*')
    servers: list[Server] = []

    def start(routes):
        servers.append(Server(routes))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_it_downloads_checks_and_places_the_model(fetch, serve, tmp_path, capsys):
    bundle = make_bundle()
    server = serve({'/model.task': (200, 'application/octet-stream', bundle)})
    folder = tmp_path / 'models'

    assert fetch.main(['--url', server.base + '/model.task'], models_dir=folder) == 0

    assert (folder / 'hand_landmarker.task').read_bytes() == bundle
    assert leftovers(folder) == ['hand_landmarker.task']  # no half-finished .part file
    out = capsys.readouterr().out
    assert 'Done' in out and 'sha256' in out


def test_a_good_copy_is_left_alone_unless_forced(fetch, serve, tmp_path, capsys):
    server = serve({'/model.task': (200, 'application/octet-stream', make_bundle())})
    folder = tmp_path / 'models'
    args = ['--url', server.base + '/model.task']

    assert fetch.main(args, models_dir=folder) == 0
    assert len(server.asked) == 1

    capsys.readouterr()
    assert fetch.main(args, models_dir=folder) == 0
    assert 'already in place' in capsys.readouterr().out
    assert len(server.asked) == 1  # it did not even ask

    assert fetch.main([*args, '--force'], models_dir=folder) == 0
    assert len(server.asked) == 2


@pytest.mark.parametrize(
    ('body', 'why'),
    [
        (b'<html><body>Sign in to continue</body></html>', 'too small'),
        (b'<html>' + b'x' * 1_200_000, 'not a model bundle'),
    ],
    ids=['a small web page', 'a big web page'],
)
def test_a_web_page_is_refused_and_nothing_is_left_behind(fetch, serve, tmp_path, capsys, body, why):
    server = serve({'/model.task': (200, 'text/html', body)})
    folder = tmp_path / 'models'

    assert fetch.main(['--url', server.base + '/model.task'], models_dir=folder) == 1

    out = capsys.readouterr().out
    assert 'could not be downloaded' in out and why in out
    assert 'download it by hand' in out
    assert leftovers(folder) == []


def test_a_server_error_is_explained(fetch, serve, tmp_path, capsys):
    server = serve({})
    folder = tmp_path / 'models'

    assert fetch.main(['--url', server.base + '/missing'], models_dir=folder) == 1

    assert '404' in capsys.readouterr().out
    assert leftovers(folder) == []


def test_an_unreachable_server_is_explained(fetch, serve, tmp_path, capsys):
    server = serve({})
    address = server.base + '/model.task'
    server.close()  # now nothing listens there

    assert fetch.main(['--url', address], models_dir=tmp_path / 'models') == 1

    assert 'could not connect' in capsys.readouterr().out


def test_a_bundle_with_one_model_is_refused(fetch, serve, tmp_path, capsys):
    server = serve({'/m': (200, 'application/octet-stream', make_bundle(names=('only.tflite',), size=1_200_000))})

    assert fetch.main(['--url', server.base + '/m'], models_dir=tmp_path / 'models') == 1

    assert 'needs at least 2' in capsys.readouterr().out


def test_a_damaged_bundle_is_refused(fetch, serve, tmp_path, capsys):
    damaged = bytearray(make_bundle())
    damaged[300_000] ^= 0xFF  # one flipped byte inside the first model: the zip's own checksum no longer matches
    server = serve({'/m': (200, 'application/octet-stream', bytes(damaged))})
    folder = tmp_path / 'models'

    assert fetch.main(['--url', server.base + '/m'], models_dir=folder) == 1

    assert 'damaged' in capsys.readouterr().out
    assert leftovers(folder) == []


def test_a_bad_file_that_is_already_there_is_replaced(fetch, serve, tmp_path, capsys):
    bundle = make_bundle()
    server = serve({'/m': (200, 'application/octet-stream', bundle)})
    folder = tmp_path / 'models'
    folder.mkdir()
    (folder / 'hand_landmarker.task').write_bytes(b'<html>saved by mistake</html>')

    assert fetch.main(['--url', server.base + '/m'], models_dir=folder) == 0

    assert (folder / 'hand_landmarker.task').read_bytes() == bundle
    assert 'no good' in capsys.readouterr().out


def test_check_mode_reports_and_never_downloads(fetch, serve, tmp_path, capsys):
    server = serve({'/m': (200, 'application/octet-stream', make_bundle())})
    folder = tmp_path / 'models'

    assert fetch.main(['--check'], models_dir=folder) == 1
    assert 'not in place yet' in capsys.readouterr().out
    assert server.asked == []

    assert fetch.main(['--url', server.base + '/m'], models_dir=folder) == 0
    assert fetch.main(['--check'], models_dir=folder) == 0
    assert 'already in place' in capsys.readouterr().out
