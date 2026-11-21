"""Evidence: the screenshots for the report and the viva, taken by a real browser that goes through the real app.

    run.bat evidence                  Windows (the first time it installs Playwright, the tool that drives the browser: about 40 MB)
    run.bat evidence --show           watch the browser while it works (it works out of sight otherwise)
    run.bat evidence --no-gemini      let the fixed wording write the words, to show that everything works without a key
    run.bat evidence --light          take them in the light theme (Golden Hour), which prints better, instead of Night Sky
    run.bat evidence --people NAME    only this folder of photos (give it again for more), for example  --people person1
    run.bat evidence --chat N         how many questions to ask in the first person's chat (0 to 7, default 7)
    run.bat evidence --url ADDRESS    use the app that is already running at ADDRESS instead of starting a copy of it
    run.bat evidence --photos DIR     read the photos from DIR instead of ..\\test-photos
    run.bat evidence --out DIR        save the pictures in DIR instead of ..\\evidence
    run.bat evidence --browser NAME   msedge, chrome or chromium (default: the first one that is there, Edge first on Windows)
    python scripts/capture_evidence.py ...   the same, from any terminal (use the Python in backend/.venv)

What it does. It starts its own copy of the app on a spare port (your own window is not touched) and opens Edge or Chrome, without
a window unless you ask for one. Then it goes through the guest flow the way a person would, once for every pair of photos in
..\\test-photos (the same folders that  run.bat preflight  reads: one folder per person, "left" and "right" in the file names):

    the upload page, both photos with their checks, the reading being made, every processing step as a before/after picture of
    each hand, the five lines marked on each palm, the reading page, the report by theme and by line, what was unclear, how the
    reading was made, and the chat (five questions it answers and two it must decline). The first person also gets the
    dashboard, the history and the settings page.

After the pairs come the photos meant to fail ("bad", "blur", "dark" and the like in the name): each goes in beside a good photo,
to show what the checks say and, when the app lets the reading go ahead, what the reading then says it could not see. Last, three
wrong files made on the spot: a text file named .jpg, an iPhone HEIC photo and a file over 15 MB. With no pair of photos at all it
uses the app's own sample palms instead, which the app labels as a sample reading.

Every picture is numbered in the order it was taken, and index.html in the same folder lists them all, each with a sentence that
says what it shows. A run replaces the pictures of the run before (only those: anything else in the folder is left alone).

Privacy. The pictures show your photos and what was found in them, so they are saved outside the project, in ..\\evidence, and must
never be committed. Your photos go only to the app on this computer. As always, Google gets only the findings, as words: Gemini is
asked to write about six to eight times for each pair of photos (once for the report, and once for each chat answer).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
OUT = ROOT.parent / 'evidence'
TEST_PHOTOS = ROOT.parent / 'test-photos'

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / 'backend'))

if hasattr(sys.stdout, 'reconfigure'):  # a Windows console may not speak UTF-8; never let a print stop the pictures
    sys.stdout.reconfigure(errors='replace')

import preflight  # the copy of the app on a spare port, and how the photo folders are read
import smoke

#: what this script writes next to the pictures, so that the next run can take away exactly what this one made
MANIFEST = 'made-by-capture-evidence.json'
INDEX = 'index.html'
#: the only names the next run may delete
OWN_NAME = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.png$')

#: wide enough for the reading page to show the report and the chat side by side
VIEWPORT = {'width': 1440, 'height': 900}
SCALE = 2
#: a part of the page taller than this (in CSS pixels) is saved at one pixel per CSS pixel, so that the file stays a sensible size
TALL = 2400
#: hidden in every picture: the short notes that pop up at the bottom for a few seconds ("Added Person1.")
HIDE_TOASTS = 'div[aria-live="polite"].fixed { visibility: hidden !important; }'
#: the bar with the Start reading button, which stays at the bottom of the screen as the page scrolls
START_BAR = '[class*="sticky"][class*="bottom-"]'
#: hidden while one part of the page is photographed: the bars that stay on screen as the page scrolls (the top bar, the guest
#: notice and the Start reading bar), so that none of them lies across that part
HIDE_BARS = HIDE_TOASTS + f' header.sticky, section[aria-label="Guest session notice"], {START_BAR} {{ visibility: hidden !important; }}'
#: a whole page in one picture: the Start reading bar goes back to the end of the page instead of lying across its middle
WHOLE_PAGE = HIDE_TOASTS + f' {START_BAR} {{ position: static !important; }}'
#: what the website remembers as the choice of the light theme (public/theme-init.js); the dark one is its default
LIGHT_THEME = "try { localStorage.setItem('kiro-theme-v2', 'light') } catch (e) {}"

#: the window while the chat questions are asked: the chat panel is as tall as the window, so a long answer fits under its question
CHAT_VIEWPORT = {'width': 1440, 'height': 1800}
#: puts the last question at the top of the conversation; says whether the answer under it is then wholly in view
SHOW_LAST_EXCHANGE = """(panel) => {
  const log = panel.querySelector('[role=log]');
  if (!log || log.children.length < 2) return true;
  const items = Array.from(log.children);
  const question = items[items.length - 2], answer = items[items.length - 1];
  log.scrollTop += question.getBoundingClientRect().top - log.getBoundingClientRect().top - 12;
  return answer.getBoundingClientRect().bottom <= log.getBoundingClientRect().bottom + 1;
}"""

READING_TIMEOUT_MS = 240_000
ANSWER_TIMEOUT_MS = 120_000
CHECK_TIMEOUT_MS = 90_000

#: the chat questions, in order: five that the chat answers from the reading, and two that it has to decline
QUESTIONS = (
    'Summarise this reading',
    'What does my heart line say?',
    'How is it different between my two hands?',
    'How sure is the app about these findings?',
    'I read that a long life line means a long life. Is that true?',
    'Will I get married?',
    'Should I quit my job?',
)
#: how many of them the people after the first one are asked
OTHERS_ASK = 2

#: what the photo checks say about a photo they have looked at (see src/app/new/PhotoSlot.tsx)
VERDICTS = re.compile(r'This photo looks good|Usable, with a note|This photo needs replacing')

#: the processing steps that make a picture, in the words of the website, and what each one does
STEP_WORDS = {
    'Resized': 'brought to the standard working size',
    'Grayscale': 'the colour taken out, so that only brightness is left',
    'Gaussian smoothing': 'smoothed, to take away noise',
    'CLAHE contrast': 'local contrast lifted, so that faint creases show',
    'Canny edges': 'the places where brightness changes sharply',
    'Thresholding': 'the creases turned into a black-and-white map',
    'Morphology': 'specks cleared away and broken pieces joined',
}
LINES_STEP = 'Locating the lines'

BROWSER_NAMES = {'msedge': 'Microsoft Edge', 'chrome': 'Google Chrome', 'chromium': "Playwright's own Chromium"}

INSTALL_HELP = """Playwright, the tool that drives the browser, is not installed in the private environment.
  run.bat evidence  installs it by itself. From a terminal:
      backend\\.venv\\Scripts\\python -m pip install -r backend\\requirements-evidence.txt"""

BROWSER_HELP = """No browser could be started. This uses Microsoft Edge (every Windows 10 and 11 computer has it) or Google Chrome.
  If neither is there, Playwright can fetch its own copy of Chromium (about 150 MB):
      backend\\.venv\\Scripts\\python -m playwright install chromium
  and then:  run.bat evidence --browser chromium"""


def say(text: str = '') -> None:
    print(text, flush=True)


def slug(text: str, limit: int = 48) -> str:
    """A piece of a file name: small letters, digits and single dashes only."""
    out = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:limit].strip('-')
    return out or 'x'


def short(error: BaseException) -> str:
    """The first line of an error, short enough for one line of the list."""
    lines = [line.strip() for line in str(error).strip().splitlines() if line.strip()]
    text = lines[0] if lines else type(error).__name__
    return text if len(text) <= 160 else text[:157] + '...'


def inside(path: Path, folder: Path) -> bool:
    path, folder = path.resolve(), folder.resolve()
    return path == folder or folder in path.parents


def browser_order(choice: str, windows: bool) -> list[str]:
    """Which browsers to try, in order. Every Windows computer has Edge, so it comes first there."""
    if choice != 'auto':
        return [choice]
    return ['msedge', 'chrome', 'chromium'] if windows else ['chromium', 'chrome', 'msedge']


def hand_for(photo: Path) -> str:
    """The slot a photo meant to fail goes into: the right one when only "right" is in its name, the left one otherwise."""
    name = photo.name.lower()
    return 'right' if 'right' in name and 'left' not in name else 'left'


def questions_for(person: int, first: int) -> tuple[str, ...]:
    """The first person is asked `first` questions (all seven by default); everybody after that the first two."""
    count = first if person == 0 else min(first, OTHERS_ASK)
    return QUESTIONS[: max(0, min(count, len(QUESTIONS)))]


def profile_name(folder: str, person: int) -> str:
    """A name the website accepts for the hand profile (letters, digits, spaces, dots and dashes, at most 24 characters)."""
    name = ' '.join(re.sub(r"[^A-Za-z0-9 '.-]+", ' ', folder).split())[:24].strip()
    if not name or re.search(r'\d{5,}', name):
        return f'Person {person + 1}'
    return name[0].upper() + name[1:]


def make_wrong_files(folder: Path) -> list[tuple[str, Path, str]]:
    """Three files that a person might choose by mistake, made on the spot: (name, file, what the picture shows)."""
    folder.mkdir(parents=True, exist_ok=True)
    corrupt = folder / 'not-really-a-photo.jpg'
    corrupt.write_bytes(b'This is a text file with a .jpg name. The app has to refuse it.\n')
    heic = folder / 'iphone-photo.heic'
    heic.write_bytes(b'\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic' + bytes(4000))
    large = folder / 'far-too-large.jpg'
    with large.open('wb') as out:
        out.write(b'\xff\xd8\xff\xe0')
        out.truncate(16 * 1024 * 1024)
    return [
        ('corrupt-file', corrupt, 'A corrupt file: a text file renamed to .jpg is refused before anything is sent, with a plain explanation.'),
        ('heic-photo', heic, "An iPhone HEIC photo is refused with its own explanation of how to get a JPG."),
        ('too-large', large, 'A file over the 15 MB limit is refused, and the message says how big it is.'),
    ]


# ------------------------------------------------------------------ the album: every picture, numbered


@dataclass
class Shot:
    group: str
    number: int
    key: str
    caption: str
    file: str | None  # None when it could not be taken
    why: str = ''  # the reason, when it could not be taken


@dataclass
class Album:
    out: Path
    shots: list[Shot] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    notes: dict[str, list[str]] = field(default_factory=dict)
    titles: dict[str, str] = field(default_factory=dict)

    def reserve(self, group: str, key: str) -> tuple[int, str]:
        number = self.counts.get(group, 0) + 1
        self.counts[group] = number
        return number, f'{slug(group)}-{number:02d}-{slug(key)}.png'

    def note(self, group: str, text: str) -> None:
        self.notes.setdefault(group, []).append(text)

    def taken(self) -> list[Shot]:
        return [s for s in self.shots if s.file]

    def missed(self) -> list[Shot]:
        return [s for s in self.shots if not s.file]


def previous_files(out: Path) -> list[Path]:
    """What the run before made here, as its manifest lists it, and nothing that does not look like one of its own pictures."""
    try:
        listed = json.loads((out / MANIFEST).read_text(encoding='utf-8')).get('files', [])
    except (OSError, ValueError, AttributeError):
        return []
    found = []
    for name in listed:
        if isinstance(name, str) and (OWN_NAME.match(name) or name == INDEX):
            path = out / name
            if path.is_file():
                found.append(path)
    return found


def clear_previous(out: Path) -> int:
    gone = 0
    for path in previous_files(out):
        try:
            path.unlink()
            gone += 1
        except OSError:
            pass
    return gone


def write_manifest(album: Album) -> None:
    files = [s.file for s in album.taken()] + [INDEX]
    body = {'made': datetime.now().isoformat(timespec='seconds'), 'files': files}
    (album.out / MANIFEST).write_text(json.dumps(body, indent=1) + '\n', encoding='utf-8')


def index_html(album: Album, facts: list[tuple[str, str]]) -> str:
    """One page that lists every picture with what it shows. It reads the pictures from the same folder."""
    e = html.escape
    parts = [
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>Kiro AI evidence</title><style>',
        'body{font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:24px 16px;color:#1f1b18;background:#faf7f2}',
        'h1{font-weight:500}h2{margin-top:2.2em;border-top:1px solid #ddd;padding-top:1em;font-weight:500}',
        'dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px}dt{color:#6b625a}dd{margin:0}',
        '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px}',
        'figure{margin:0;background:#fff;border:1px solid #e5ded5;border-radius:10px;padding:10px}',
        'figure img{width:100%;height:220px;object-fit:contain;background:#f1ece5;border-radius:6px}',
        'figcaption{font-size:13px;margin-top:8px}figcaption b{display:block;font-weight:600}',
        '.note{color:#6b625a;font-size:14px}.miss{color:#9b2c2c}.warn{background:#fff4d6;padding:10px 14px;border-radius:8px}',
        '</style></head><body>',
        '<h1>Kiro AI: evidence screenshots</h1>',
        '<p class="warn">These pictures show real palms and what was found in them. Keep them out of the project and never commit them.</p>',
        '<dl>' + ''.join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k, v in facts) + '</dl>',
    ]
    order = list(dict.fromkeys(s.group for s in album.shots))
    for group in order:
        parts.append(f'<h2>{e(album.titles.get(group, group))}</h2>')
        for line in album.notes.get(group, []):
            parts.append(f'<p class="note">{e(line)}</p>')
        parts.append('<div class="grid">')
        for s in album.shots:
            if s.group != group:
                continue
            if s.file:
                parts.append(
                    f'<figure><a href="{e(s.file)}"><img src="{e(s.file)}" alt="{e(s.caption)}" loading="lazy"></a>'
                    f'<figcaption><b>{s.number:02d} &middot; {e(s.file)}</b>{e(s.caption)}</figcaption></figure>'
                )
            else:
                parts.append(f'<figure><figcaption class="miss"><b>{s.number:02d} &middot; not taken</b>{e(s.caption)}<br>Why: {e(s.why)}</figcaption></figure>')
        parts.append('</div>')
    parts.append('</body></html>\n')
    return '\n'.join(parts)


# ------------------------------------------------------------------ the browser


def load_playwright():
    """Playwright's synchronous API, or None when it is not installed."""
    try:
        from playwright import sync_api
    except ImportError:
        return None
    return sync_api


class Camera:
    """Takes the pictures of one page into the album. A picture that cannot be taken is listed with the reason, and the run goes on."""

    def __init__(self, page, album: Album, group: str, errors: tuple[type[BaseException], ...]) -> None:
        self.page = page
        self.album = album
        self.group = group
        self.errors = errors

    def settle(self) -> None:
        self.page.evaluate('() => (document.fonts ? document.fonts.ready.then(() => true) : true)')
        self.page.wait_for_timeout(300)

    def page_shot(self, key: str, caption: str, *, full: bool = False, at_once: bool = False) -> bool:
        def take(path: Path) -> None:
            if not at_once:
                self.settle()
            self.page.screenshot(path=str(path), full_page=full, scale='css', animations='disabled', style=WHOLE_PAGE if full else HIDE_TOASTS)

        return self.take(key, caption, take)

    def element_shot(self, locator, key: str, caption: str) -> bool:
        def take(path: Path) -> None:
            target = locator.first
            target.wait_for(state='visible')
            target.scroll_into_view_if_needed()
            self.settle()
            box = target.bounding_box()
            scale = 'css' if box and box['height'] > TALL else 'device'
            target.screenshot(path=str(path), scale=scale, animations='disabled', style=HIDE_BARS)

        return self.take(key, caption, take)

    def take(self, key: str, caption: str, take) -> bool:
        number, name = self.album.reserve(self.group, key)
        try:
            take(self.album.out / name)
        except self.errors as error:
            self.album.shots.append(Shot(self.group, number, key, caption, None, short(error)))
            say(f'  --  {number:02d} {key}: not taken ({short(error)})')
            return False
        self.album.shots.append(Shot(self.group, number, key, caption, name))
        say(f'  ok  {number:02d} {key}')
        return True


def launch(api, playwright, choice: str, show: bool):
    """(browser, its name). Tries each browser in turn; raises RuntimeError with the reasons when none starts."""
    reasons = []
    for name in browser_order(choice, os.name == 'nt'):
        try:
            if name == 'chromium':
                browser = playwright.chromium.launch(headless=not show)
            else:
                browser = playwright.chromium.launch(channel=name, headless=not show)
            return browser, BROWSER_NAMES.get(name, name)
        except api.Error as error:
            reasons.append(f'{BROWSER_NAMES.get(name, name)}: {short(error)}')
    raise RuntimeError('\n'.join(reasons))


def new_page(browser, light: bool):
    context = browser.new_context(
        viewport=VIEWPORT,
        device_scale_factor=SCALE,
        reduced_motion='reduce',  # the app then shows chat answers whole and keeps everything still: the pictures come out the same each time
        color_scheme='light' if light else 'dark',
        locale='en-GB',
    )
    if light:
        context.add_init_script(LIGHT_THEME)
    context.set_default_timeout(30_000)
    return context, context.new_page()


def start_guest(page, base: str) -> None:
    page.goto(f'{base}/start')
    page.get_by_role('heading', name='One clear photo of each palm.').wait_for()


def add_profile(page, cam: Camera | None, name: str, mine: bool) -> None:
    page.get_by_role('button', name=re.compile('Create a profile')).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('Name', exact=True).fill(name)
    if not mine:
        dialog.get_by_text('Someone else', exact=True).click()
        dialog.get_by_role('checkbox').check()
    if cam is not None:
        what = 'their own palms' if mine else 'someone else, who has agreed (the tick is required)'
        cam.element_shot(dialog, 'profile', f'Making the hand profile "{name}" for {what}.')
    dialog.get_by_role('button', name=re.compile('Add profile')).click()
    dialog.wait_for(state='detached')
    page.locator('section[aria-label="Left palm"]').wait_for()


def slot_of(page, side: str):
    return page.locator(f'section[aria-label="{"Left palm" if side == "left" else "Right palm"}"]')


def both_slots(page):
    """The part of the page that holds both photo slots: the nearest box around the left one that also holds the right one."""
    return page.locator('xpath=//section[@aria-label="Left palm"]/ancestor::div[.//section[@aria-label="Right palm"]][1]')


def add_photo(page, side: str, photo: Path, previous: str | None = None) -> str:
    """Puts a photo in one slot and waits for what the checks say about it: the verdict, or why the photo was refused."""
    slot = slot_of(page, side)
    slot.locator('input[type=file]').set_input_files(str(photo))
    said = slot.locator('strong', has_text=VERDICTS).or_(slot.get_by_role('alert'))
    deadline = CHECK_TIMEOUT_MS
    while deadline > 0:
        if said.count():
            text = ' '.join(said.first.inner_text().split())
            if text and text != previous:
                return text
        page.wait_for_timeout(250)
        deadline -= 250
    raise TimeoutError(f'the checks said nothing about {photo.name} within {CHECK_TIMEOUT_MS // 1000} s')


def can_start(page) -> bool:
    start = page.get_by_role('button', name=re.compile('Start reading'))
    return start.count() > 0 and start.first.is_enabled()


def make_reading(page, cam: Camera, errors) -> str | None:
    """Starts the reading and waits for it. None when it finished, otherwise what went wrong."""
    page.get_by_role('button', name=re.compile('Start reading')).click()
    steps = page.locator('ol[aria-label="Steps"]')
    steps.wait_for()
    # the best moment for a picture is late in the run, with most steps ticked off: the writing of the words takes longest
    late = steps.locator('li', has_text='Writing the reading').get_by_text('Working on it')
    for moment, wait in ((late, 20_000), (steps.get_by_text('Working on it').first, 1_000)):
        try:
            moment.wait_for(timeout=wait)
        except errors:
            continue
        cam.page_shot('processing-live', 'The reading being made: each step is ticked off as the server streams it, and its picture appears.', at_once=True)
        break
    else:
        cam.album.note(cam.group, 'The reading finished before a picture of it in progress could be taken.')
    done = page.get_by_role('button', name=re.compile('Open your reading'))
    again = page.get_by_role('button', name='Try again')
    done.or_(again).first.wait_for(timeout=READING_TIMEOUT_MS)
    if again.count() and again.first.is_visible():
        why = ' '.join(page.get_by_role('alert').first.inner_text().split())
        cam.page_shot('reading-failed', f'The reading did not finish, and the page says why: "{why}"')
        return why or 'the reading did not finish'
    return None


def capture_steps(page, cam: Camera) -> None:
    cam.page_shot('processing-done', 'All ten steps finished. Each finished step can be opened to compare its picture with the photo.', full=True)
    steps = page.locator('ol[aria-label="Steps"] button')
    labels = []
    for i in range(steps.count()):
        first = steps.nth(i).inner_text().strip().splitlines()
        if first:
            labels.append(first[0].strip())
    hands = page.get_by_role('tablist', name='Which hand to look at')
    for label in labels:
        for side in ('left', 'right'):
            try:
                hands.get_by_role('tab', name='Left palm' if side == 'left' else 'Right palm').click()
                steps.filter(has_text=label).first.click()
                page.wait_for_timeout(300)
            except cam.errors as error:
                cam.album.note(cam.group, f'Could not open the step "{label}" for the {side} palm: {short(error)}')
                continue
            if label == LINES_STEP:
                panel = page.locator(f'svg[aria-label^="{side} palm with its main lines" i]').locator('xpath=..')
                cam.element_shot(
                    panel,
                    f'lines-{side}',
                    f'The {side} palm with the five main lines the server found, numbered: a solid line was detected, a dashed one is '
                    'uncertain, and a dotted box marks where a line was looked for and not seen (nothing is drawn there).',
                )
            else:
                words = STEP_WORDS.get(label, 'this step')
                cam.element_shot(
                    page.locator('[role=slider]'),
                    f'step-{slug(label)}-{side}',
                    f'{label}, {side} palm: {words}. Left of the handle is the photo as it arrived, right of it the result of this step.',
                )


def reading_facts(page, base: str) -> str | None:
    """Who wrote the words of the reading now open, from the app's own record of it (the page's cookie is used)."""
    match = re.search(r'/app/readings/([^/?#]+)', page.url)
    if not match:
        return None
    response = page.request.get(f'{base}/v1/readings/{match.group(1)}')
    if not response.ok:
        return None
    meta = response.json().get('meta', {})
    writer = {'gemini': f'Gemini ({meta.get("model", "")})', 'knowledge-base': 'the fixed wording from the knowledge base'}.get(
        meta.get('provider', ''), meta.get('provider', 'unknown')
    )
    text = f'The words of this reading were written by {writer}.'
    if meta.get('note'):
        text += f' {meta["note"]}'
    return text


def capture_reading(page, cam: Camera, base: str, *, full: bool) -> None:
    page.get_by_role('button', name=re.compile('Open your reading')).click()
    page.locator('#report').wait_for()
    page.get_by_role('heading', level=1).first.wait_for()
    try:
        facts = reading_facts(page, base)
        if facts:
            cam.album.note(cam.group, facts)
    except cam.errors + (ValueError,) as error:
        cam.album.note(cam.group, f'Could not read who wrote the words: {short(error)}')
    cam.page_shot('reading-top', 'The reading page: whose palms, how many lines were detected, uncertain or not visible, and the chat beside it.')
    cam.element_shot(page.locator('#lines'), 'reading-lines', 'What was found on each hand: both palms with their lines marked, the photo quality, the hand shape, and the table of every line on both hands.')
    if not full:
        cam.element_shot(page.locator('#report-uncertainty'), 'report-unclear', 'What the reading could not see clearly, and why: an unclear line is never described.')
        return
    cam.element_shot(page.locator('#report .card', has_text='In short'), 'report-summary', 'The report in short.')
    view = page.get_by_role('group', name='How to read the report')
    try:
        view.get_by_role('button', name='By theme').click()
    except cam.errors as error:
        cam.album.note(cam.group, f'Could not switch the report to "By theme": {short(error)}')
    cam.element_shot(page.locator('#report-themes'), 'report-by-theme', 'The report by theme (personality, career, money, relationships, outlook): each theme says which lines it rests on.')
    try:
        view.get_by_role('button', name='By line').click()
    except cam.errors as error:
        cam.album.note(cam.group, f'Could not switch the report to "By line": {short(error)}')
    cam.element_shot(page.locator('#report-lines'), 'report-by-line', 'The report by line, with the left and right hands side by side and what the tradition says about the difference between them.')
    cam.element_shot(page.locator('#report-uncertainty'), 'report-unclear', 'What the reading could not see clearly, and why: an unclear line is never described.')
    made = page.locator('#report details').first
    try:
        made.locator('summary').click()
    except cam.errors as error:
        cam.album.note(cam.group, f'Could not open "How this reading was made": {short(error)}')
    cam.element_shot(made, 'report-how-it-was-made', 'How this reading was made: who wrote the words, the versions of the knowledge base, the instructions and the image processing.')


def show_last_exchange(panel) -> bool:
    """Scrolls the conversation so that the last question is at its top. True when the whole answer under it is in view."""
    return bool(panel.evaluate(SHOW_LAST_EXCHANGE))


def show_end_of_conversation(panel) -> None:
    panel.evaluate("(panel) => { const log = panel.querySelector('[role=log]'); if (log) log.scrollTop = log.scrollHeight; }")


def capture_chat(page, cam: Camera, questions: tuple[str, ...]) -> None:
    if not questions:
        return
    panel = page.locator('section[aria-label="Chat about this reading"]')
    cam.element_shot(panel, 'chat-start', 'The chat before the first question, with suggested questions and a note on what is sent to Gemini.')
    # The chat panel is as tall as the window, and a long answer under its question does not fit in 900 px: the window is made
    # taller while the questions are asked, so that each picture holds the whole exchange.
    page.set_viewport_size(CHAT_VIEWPORT)
    box = panel.get_by_label('Your question')
    typing = panel.locator('[role=status][aria-label$="is writing a reply"]')
    try:
        for number, question in enumerate(questions, 1):
            try:
                box.fill(question)
                panel.get_by_role('button', name='Send question').click()
                try:
                    typing.wait_for(state='visible', timeout=5_000)
                except cam.errors:
                    pass  # the answer came before the "writing" sign could be seen
                typing.wait_for(state='detached', timeout=ANSWER_TIMEOUT_MS)
                page.wait_for_timeout(400)
                whole = show_last_exchange(panel)
            except cam.errors as error:
                cam.album.note(cam.group, f'Chat question {number} ("{question}") did not get an answer: {short(error)}')
                continue
            declined = question in QUESTIONS[5:]
            what = 'one the app must decline, in its own words' if declined else 'answered from this reading only'
            key = f'chat-{number}-{slug(question, 32)}'
            cam.element_shot(panel, key, f'Chat, question {number}: "{question}" ({what}).')
            if not whole:
                try:
                    show_end_of_conversation(panel)
                except cam.errors:
                    continue
                cam.element_shot(panel, f'{key}-end', f'Chat, question {number}, continued: the end of the answer.')
    finally:
        page.set_viewport_size(VIEWPORT)


def capture_app_pages(page, cam: Camera, base: str) -> None:
    for path, key, caption in (
        ('/app', 'dashboard', 'The dashboard of the guest session, with the hand profile drawn as its own planet.'),
        ('/app/history', 'history', 'History: in a guest session it is headed "This session", because nothing is kept.'),
        ('/app/settings', 'settings', 'Settings: what is kept and what is not (what Gemini and MediaPipe receive), and the data controls: export, delete everything.'),
    ):
        try:
            page.goto(f'{base}{path}')
            page.get_by_role('heading', level=1).first.wait_for()
        except cam.errors as error:
            cam.album.note(cam.group, f'Could not open {path}: {short(error)}')
            continue
        cam.page_shot(key, caption, full=key == 'settings')


# ------------------------------------------------------------------ the groups of pictures


@dataclass
class Outcome:
    group: str
    finished: bool
    why: str = ''


def capture_person(browser, base: str, album: Album, errors, person: int, name: str, left: Path, right: Path, args) -> Outcome:
    group = slug(name)
    mine = person == 0
    album.titles[group] = f'{name}: a pair of real palms' + (' (the author\'s own)' if mine else ' (someone who agreed)')
    say(f'\n{name}  ({left.name}, {right.name})')
    context, page = new_page(browser, args.light)
    cam = Camera(page, album, group, errors)
    try:
        start_guest(page, base)
        add_profile(page, cam, profile_name(name, person), mine)
        cam.page_shot('upload-empty', 'The upload page: one slot for each palm, tips for a good photo, and what happens to the photos.')
        for side, photo in (('left', left), ('right', right)):
            verdict = add_photo(page, side, photo)
            album.note(group, f'{side.capitalize()} photo ({photo.name}): {verdict}')
        cam.element_shot(both_slots(page), 'photos-checked', 'Both palms uploaded and previewed, each with the result of every photo check.')
        cam.page_shot('ready-to-start', 'The bottom of the screen says whether the reading can start: both photos passed, so Start reading is allowed.')
        if not can_start(page):
            return Outcome(group, False, 'Start reading stayed switched off: a photo did not pass the checks')
        problem = make_reading(page, cam, errors)
        if problem:
            return Outcome(group, False, problem)
        capture_steps(page, cam)
        capture_reading(page, cam, base, full=True)
        capture_chat(page, cam, questions_for(person, args.chat))
        if mine:
            capture_app_pages(page, cam, base)
        return Outcome(group, True)
    except errors + (TimeoutError,) as error:
        cam.page_shot('where-it-stopped', f'Where the run stopped: {short(error)}')
        return Outcome(group, False, short(error))
    finally:
        context.close()


def capture_samples(browser, base: str, album: Album, errors, args) -> Outcome:
    """With no photos at all: the app's own drawn sample palms, which give a labelled sample reading."""
    group = 'samples'
    album.titles[group] = "The app's own sample palms (drawings: a labelled sample reading, not a real analysis)"
    say('\nsamples  (no pair of photos was found, so the app\'s own drawn sample palms are used)')
    context, page = new_page(browser, args.light)
    cam = Camera(page, album, group, errors)
    try:
        start_guest(page, base)
        add_profile(page, cam, 'Sample', True)
        page.get_by_role('button', name=re.compile('Use sample palms for both')).click()
        for side in ('left', 'right'):
            slot_of(page, side).locator('strong', has_text=VERDICTS).wait_for(timeout=CHECK_TIMEOUT_MS)
        cam.element_shot(both_slots(page), 'photos-checked', 'Both sample palms in place, each with the result of every photo check.')
        problem = make_reading(page, cam, errors)
        if problem:
            return Outcome(group, False, problem)
        capture_steps(page, cam)
        capture_reading(page, cam, base, full=True)
        capture_chat(page, cam, questions_for(0, args.chat))
        return Outcome(group, True)
    except errors + (TimeoutError,) as error:
        cam.page_shot('where-it-stopped', f'Where the run stopped: {short(error)}')
        return Outcome(group, False, short(error))
    finally:
        context.close()


def capture_bad_photo(browser, base: str, album: Album, errors, photo: Path, partner: Path | None, args) -> Outcome:
    group = 'bad-' + slug(re.sub(r'(?i)^bad[-_ ]*', '', photo.stem), 24)
    side = hand_for(photo)
    other = 'right' if side == 'left' else 'left'
    album.titles[group] = f'A photo meant to fail: {photo.name}'
    say(f'\n{photo.name}  (meant to fail, in the {side} slot)')
    context, page = new_page(browser, args.light)
    cam = Camera(page, album, group, errors)
    try:
        start_guest(page, base)
        add_profile(page, None, 'Test', True)
        verdict = add_photo(page, side, photo)
        album.note(group, f'What the checks said about {photo.name}: {verdict}')
        if partner is not None:
            add_photo(page, other, partner)
        allowed = can_start(page)
        if allowed:
            caption = f'{photo.name} in the {side} slot: the checks warn ("{verdict}") but let the reading go ahead.'
        else:
            caption = f'{photo.name} in the {side} slot: the checks refuse it ("{verdict}") and Start reading stays off until it is replaced.'
        cam.element_shot(both_slots(page), 'photos-checked', caption)
        cam.element_shot(slot_of(page, side), 'its-checks', f'The checks on {photo.name}, one by one, each saying how to take a better photo.')
        state = 'allowed, with a note' if allowed else 'switched off, with the reason'
        cam.page_shot('start-button', f'The bottom of the screen: Start reading is {state}.')
        if not allowed:
            return Outcome(group, True)
        problem = make_reading(page, cam, errors)
        if problem:
            return Outcome(group, False, problem)
        capture_reading(page, cam, base, full=False)
        return Outcome(group, True)
    except errors + (TimeoutError,) as error:
        cam.page_shot('where-it-stopped', f'Where the run stopped: {short(error)}')
        return Outcome(group, False, short(error))
    finally:
        context.close()


def capture_wrong_files(browser, base: str, album: Album, errors, folder: Path, args) -> Outcome:
    group = 'wrong-files'
    album.titles[group] = 'Files that are not usable photos'
    say('\nwrong files  (made on the spot: a text file named .jpg, a HEIC photo, a file over 15 MB)')
    context, page = new_page(browser, args.light)
    cam = Camera(page, album, group, errors)
    try:
        start_guest(page, base)
        add_profile(page, None, 'Test', True)
        said = None
        for key, path, caption in make_wrong_files(folder):
            said = add_photo(page, 'left', path, previous=said)
            album.note(group, f'{path.name}: {said}')
            cam.element_shot(slot_of(page, 'left'), key, f'{caption} The page says: "{said}"')
        return Outcome(group, True)
    except errors + (TimeoutError,) as error:
        cam.page_shot('where-it-stopped', f'Where the run stopped: {short(error)}')
        return Outcome(group, False, short(error))
    finally:
        context.close()


# ------------------------------------------------------------------ the run


def health_of(base: str) -> dict:
    try:
        with urllib.request.urlopen(f'{base}/v1/health', timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except (OSError, ValueError):
        return {}


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='run.bat evidence', description='The screenshots for the report, taken by a real browser going through the real app.')
    parser.add_argument('--photos', type=Path, default=TEST_PHOTOS, help='the folder of test photos (default: ..\\test-photos)')
    parser.add_argument('--out', type=Path, default=OUT, help='where the pictures go (default: ..\\evidence)')
    parser.add_argument('--url', help='use the app already running at this address instead of starting a copy')
    parser.add_argument('--browser', choices=('auto', 'msedge', 'chrome', 'chromium'), default='auto')
    parser.add_argument('--show', action='store_true', help='show the browser while it works')
    parser.add_argument('--light', action='store_true', help='use the light theme (Golden Hour) instead of Night Sky')
    parser.add_argument('--no-gemini', action='store_true', help='start the copy of the app without the Gemini key')
    parser.add_argument('--people', action='append', default=[], metavar='NAME', help='only this folder of photos (can be given more than once)')
    parser.add_argument('--chat', type=int, default=len(QUESTIONS), metavar='N', help=f'questions for the first person (0 to {len(QUESTIONS)})')
    args = parser.parse_args(argv)
    if not 0 <= args.chat <= len(QUESTIONS):
        parser.error(f'--chat takes a number from 0 to {len(QUESTIONS)}')
    if args.url and args.no_gemini:
        parser.error('--no-gemini only works when this starts its own copy of the app (leave out --url)')
    return args


def run(args: argparse.Namespace) -> int:
    api = load_playwright()
    if api is None:
        say(INSTALL_HELP)
        return 2
    out = args.out.resolve()
    if inside(out, ROOT):
        say(f'The pictures show real palms, so they may not be saved inside the project folder: {out}')
        say('Choose a folder outside it (the default is ..\\evidence).')
        return 2
    pairs, bad = preflight.find_pairs(args.photos)
    if args.people:
        wanted = {p.lower() for p in args.people}
        pairs = [p for p in pairs if p[0].lower() in wanted]
        bad = [b for b in bad if b.parent.name.lower() in wanted]
        if not pairs:
            say(f'No pair of photos in {args.photos} is in a folder called {", ".join(args.people)}.')
            return 2
    out.mkdir(parents=True, exist_ok=True)
    gone = clear_previous(out)

    say('Kiro AI evidence screenshots')
    say(f'  Photos: {args.photos}  ({len(pairs)} pair(s), {len(bad)} photo(s) meant to fail)')
    say(f'  Pictures go to: {out}' + (f'  (the {gone} picture(s) of the run before were taken away)' if gone else ''))
    say('  They show real palms: keep them out of the project and never commit them.')

    album = Album(out)
    outcomes: list[Outcome] = []
    errors = (api.Error,)
    app = None
    with tempfile.TemporaryDirectory(prefix='kiro-evidence-', ignore_cleanup_errors=True) as tmp:
        try:
            if args.url:
                base = args.url.rstrip('/')
                if not smoke.kiro_at(base):
                    say(f'\nNothing that looks like Kiro AI answers at {base}. Start it first (run.bat), or leave out --url.')
                    return 1
                say(f'  App: the one already running at {base}')
            else:
                app = preflight.RunningApp(Path(tmp) / 'app', extra_env={'GEMINI_API_KEY': ''} if args.no_gemini else None)
                say(f'  App: starting a copy of it on {app.base} (your own window is not touched) ...')
                app.start()
                app.wait_until_up()
                base = app.base
            health = health_of(base)
            writer = health.get('writer', '?') + (f' ({health["writerModel"]})' if health.get('writerModel') else '')
            say(f'  Analysis: {health.get("analysis", "?")}. Writer: {writer}.')
            with api.sync_playwright() as playwright:
                try:
                    browser, browser_name = launch(api, playwright, args.browser, args.show)
                except RuntimeError as reasons:
                    say(f'\n{BROWSER_HELP}\n\nWhat each one said:\n{reasons}')
                    return 1
                say(f'  Browser: {browser_name}' + ('' if args.show else ' (out of sight)'))
                try:
                    for person, (name, left, right) in enumerate(pairs):
                        outcomes.append(capture_person(browser, base, album, errors, person, name, left, right, args))
                    if not pairs:
                        outcomes.append(capture_samples(browser, base, album, errors, args))
                    for photo in bad:
                        partner = None
                        if pairs:
                            partner = pairs[0][2] if hand_for(photo) == 'left' else pairs[0][1]
                        outcomes.append(capture_bad_photo(browser, base, album, errors, photo, partner, args))
                    outcomes.append(capture_wrong_files(browser, base, album, errors, Path(tmp) / 'wrong-files', args))
                finally:
                    browser.close()
        except RuntimeError as error:  # the copy of the app did not start
            say(f'\n{error}')
            return 1
        finally:
            if app is not None:
                app.stop()

    facts = [
        ('Taken', datetime.now().strftime('%d %B %Y, %H:%M')),
        ('App', f'version {health.get("version", "?")}, analysis {health.get("analysis", "?")}, writer {writer}'),
        ('Browser', f'{browser_name}, {VIEWPORT["width"]} x {VIEWPORT["height"]}, {"light (Golden Hour)" if args.light else "dark (Night Sky)"} theme, reduced motion'),
        ('Photos', f'{len(pairs)} pair(s) and {len(bad)} photo(s) meant to fail, from {args.photos}'),
    ]
    (out / INDEX).write_text(index_html(album, facts), encoding='utf-8')
    write_manifest(album)

    taken, missed = album.taken(), album.missed()
    say('')
    for outcome in outcomes:
        say(f'  {"done" if outcome.finished else "FAIL"}  {outcome.group}' + (f': {outcome.why}' if outcome.why else ''))
    say(f'\n{len(taken)} picture(s) saved in {out}' + (f', {len(missed)} could not be taken (listed in index.html)' if missed else ''))
    say(f'Open {out / INDEX} to see them all, each with what it shows.')
    failed = [o for o in outcomes if not o.finished]
    if failed or not taken:
        say('\nRESULT: FAIL')
        return 1
    say('\nRESULT: PASS')
    return 0


def main(argv: list[str]) -> int:
    return run(parse(argv))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
