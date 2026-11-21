"""Writes a REAL report for your own photos, with Gemini, and shows everything: what was found, what Gemini is told, what it wrote,
and which passages the safety checks refused.

    run.bat live                         reads E:\\Project\\test-photos\\person1
    run.bat live person2                 another folder under test-photos (or a full path)
    run.bat live --no-gemini             the same with the fixed wording only, to compare the two
    run.bat live --model NAME            try another Gemini model for this run
    python scripts/live_report.py ...    the same, from any terminal (use the Python in backend/.venv)

It does what the server does for a reading: the six photo checks, the hand model, the lines, the report. Then Gemini writes the
passages that interpret the findings, and every passage is checked before it is used.

Photos: put them in the folder as   left.jpg  and  right.jpg   (a file name with "left" or "right" in it says which hand).
YOUR PHOTOS NEVER GO TO GOOGLE. Only the findings, in words, are sent, and this script prints exactly those before it asks.

A text copy of what it prints is saved in E:\\Project\\debug. It describes your palms (not the photos), so it is kept outside the
project: never commit it.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, 'reconfigure'):  # a Windows console may not speak UTF-8; never let a print crash the script
    sys.stdout.reconfigure(errors='replace')

try:
    from app.core.config import Settings, read_settings
    from app.cv.images import check_photo
    from app.cv.pipeline import make_real_reading
    from app.llm.gemini import (
        ModelService,
        ModelUnavailable,
        redact,
        service_from_settings,
    )
    from app.llm.prompts import findings_payload, plan_fields
    from app.llm.writer import Outcome, meta_for, note_for, write_report
    from app.schemas import HandAnalysis, Reading
except ImportError:
    print()
    print('  The Python packages are not installed in this Python.')
    print('  Run  run.bat  once (it makes backend\\.venv and installs them), then use  run.bat live')
    print()
    raise SystemExit(1) from None

TEST_PHOTOS = ROOT.parent / 'test-photos'
DEBUG = ROOT.parent / 'debug'
PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
WIDTH = 100


class Page:
    """Prints, and keeps what it printed so that a copy can be saved."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def say(self, text: str = '') -> None:
        self.lines.append(text)
        print(text, flush=True)

    def wrapped(self, text: str, indent: str = '  ', first: str | None = None) -> None:
        for paragraph in text.split('\n'):
            lines = textwrap.wrap(paragraph, WIDTH - len(indent), initial_indent=first if first is not None else indent, subsequent_indent=indent, break_long_words=False)
            self.say('\n'.join(lines))
            first = None


# ------------------------------------------------------------------ finding the photos


def resolve_folder(arg: str | None) -> Path:
    """The photo folder: nothing given is test-photos\\person1; a name or path is tried as it is, then beside the project, then in test-photos."""
    if not arg:
        return TEST_PHOTOS / 'person1'
    for path in (Path(arg), ROOT.parent / arg, TEST_PHOTOS / arg):
        if path.is_dir():
            return path
    return TEST_PHOTOS / arg


def find_pair(folder: Path) -> tuple[Path, Path] | None:
    """(left photo, right photo) from the folder, or from the first folder under it that holds both."""
    if not folder.is_dir():
        return None
    for directory in [folder, *sorted(p for p in folder.rglob('*') if p.is_dir())]:
        images = [p for p in sorted(directory.iterdir()) if p.is_file() and p.suffix.lower() in PHOTO_EXTENSIONS]
        lefts = [p for p in images if 'left' in p.name.lower() and 'right' not in p.name.lower()]
        rights = [p for p in images if 'right' in p.name.lower() and 'left' not in p.name.lower()]
        if lefts and rights:
            return lefts[0], rights[0]
    return None


# ------------------------------------------------------------------ showing what was found


def show_findings(page: Page, hands: dict[str, HandAnalysis]) -> None:
    for side in ('left', 'right'):
        hand = hands[side]
        page.say(f'  {side.upper()} hand  (photo {hand.photo.width} x {hand.photo.height}, quality {hand.quality.score:.2f}: sharpness {hand.quality.sharpness}, lighting {hand.quality.lighting})')
        for f in hand.features:
            traits = ', '.join(f'{k} {v}' for k, v in f.traits.model_dump(exclude_none=True).items())
            confidence = '' if f.confidence is None else f'  confidence {f.confidence:.2f}'
            page.say(f'    {f.name:11s} {f.status:11s} {traits}{confidence}')
        shape = hand.palmShape
        traits = ', '.join(f'{k} {v}' for k, v in shape.traits.model_dump(exclude_none=True).items())
        page.say(f'    {"hand shape":11s} {shape.status:11s} {traits}')


def tag(used: bool, accepted: dict[str, str], key: str, both: bool = False) -> str:
    """Who wrote a passage, for the label in front of it."""
    if not used:
        return ''
    if key in accepted:
        return ' [app + Gemini]' if both else ' [Gemini]'
    return ' [fixed wording]'


def show_observed(page: Page, left: str, right: str, used: bool) -> None:
    page.say('  Observed' + (' [app]' if used else ''))
    page.wrapped(f'left: {left}', '      ', '    ')
    page.wrapped(f'right: {right}', '      ', '    ')


def show_report(page: Page, reading: Reading, accepted: dict[str, str], used: bool) -> None:
    report = reading.report
    page.say()
    page.say('=' * WIDTH)
    page.say('THE REPORT' + ('   ([Gemini] = written by Gemini and checked; [fixed wording] = from the knowledge base; [app] = measured by the app)' if used else '   (all the words come from the knowledge base)'))
    page.say('=' * WIDTH)
    lead, _, rest = report.summary.partition('\n')
    page.say()
    page.say('SUMMARY [app]' if used else 'SUMMARY')
    page.wrapped(lead)
    if rest:
        page.say('  --- overview' + tag(used, accepted, 'summary'))
        page.wrapped(rest)
    for section in report.sections:
        fid = section.featureId
        page.say()
        page.say(section.title.upper())
        show_observed(page, section.observed.left.text, section.observed.right.text, used)
        for side in ('left', 'right'):
            text = getattr(section.traditional, side)
            if text:
                page.say(f'  Tradition, {side} hand{tag(used, accepted, f"{fid}_{side}")}')
                page.wrapped(text, '    ')
        if section.comparison:
            page.say(f'  Comparison{tag(used, accepted, f"compare_{fid}", both=True)}')
            page.wrapped(section.comparison, '    ')
    page.say()
    page.say('HAND SHAPE')
    show_observed(page, report.shape.observed.left.text, report.shape.observed.right.text, used)
    for side in ('left', 'right'):
        text = getattr(report.shape.traditional, side)
        if text:
            page.say(f'  Tradition, {side} hand{tag(used, accepted, f"shape_{side}")}')
            page.wrapped(text, '    ')
    if report.shape.comparison:
        page.say('  Comparison [app]' if used else '  Comparison')
        page.wrapped(report.shape.comparison, '    ')
    for theme in report.themes:
        page.say()
        page.say(f'THEME: {theme.title.upper()}  (based on {", ".join(theme.basedOn) or "nothing"}; left out: {", ".join(theme.leftOut) or "nothing"}){tag(used, accepted, f"theme_{theme.themeId}", both=True)}')
        if theme.traditional:
            page.wrapped(theme.traditional, '    ')
    page.say()
    page.say('UNCERTAINTY [app]' if used else 'UNCERTAINTY')
    for item in report.uncertainty:
        page.wrapped(item, '    ', '  - ')
    page.say()
    page.say('DISCLAIMER')
    page.wrapped(report.disclaimer, '    ')
    meta = reading.meta
    page.say()
    page.say('HOW THIS READING WAS MADE')
    page.say(f'  writer: {meta.provider} / {meta.model}     knowledge base: {meta.knowledgeBase}     prompt: {meta.prompt}')
    page.say(f'  analysis: {meta.pipeline}')
    if meta.note:
        page.wrapped(f'note: {meta.note}', '    ', '  ')


# ------------------------------------------------------------------ the whole thing


def open_finder(model: Path, page: Page):
    from app.cv.hand import MediaPipeFinder, mediapipe_installed

    if not mediapipe_installed():
        page.say()
        page.say('  The MediaPipe package is not installed. Run  run.bat  once, then use  run.bat live')
        return None
    if not model.is_file():
        page.say()
        page.say(f'  The hand model {model} is missing. Run  run.bat models  first.')
        return None
    return MediaPipeFinder(model)


def main(
    argv: list[str],
    *,
    settings: Settings | None = None,
    make_service: Callable[[Settings], ModelService] = service_from_settings,
    finder=None,
) -> int:
    parser = argparse.ArgumentParser(description='Writes a real report for your own photos, with Gemini.')
    parser.add_argument('folder', nargs='?', help='the folder with left.jpg and right.jpg (default: test-photos\\person1)')
    parser.add_argument('--out', type=Path, default=DEBUG, help='where the text copy goes (default: ..\\debug)')
    parser.add_argument('--no-gemini', action='store_true', help='do not use Gemini: show the fixed wording only')
    parser.add_argument('--model', help='use this Gemini model instead of the one in backend\\.env')
    parser.add_argument('--thinking', help='use this thinking level (MINIMAL, LOW, MEDIUM or HIGH)')
    parser.add_argument('--hand-model', type=Path, default=None, help='the hand model file (default: backend\\models\\hand_landmarker.task)')
    args = parser.parse_args(argv)

    page = Page()
    settings = settings or read_settings()
    if args.model:
        settings = settings.with_(gemini_model=args.model.strip())
    if args.thinking is not None:
        settings = settings.with_(gemini_thinking=args.thinking.strip())

    folder = resolve_folder(args.folder)
    pair = find_pair(folder)
    page.say()
    if pair is None:
        page.say(f'  No left and right photo found in {folder}')
        page.say('  Put  left.jpg  and  right.jpg  there (a file name with "left" or "right" in it says which hand).')
        page.say()
        return 1
    page.say(f'Kiro AI: a real report for the photos in {folder}')
    page.say(f'  left photo: {pair[0].name}     right photo: {pair[1].name}     (the photos stay on this computer)')

    service: ModelService | None = None
    if not args.no_gemini:
        service = make_service(settings)
        if not service.available:
            page.say('  Gemini: not used, because there is no key in backend\\.env (the fixed wording is shown). Add one, then run  run.bat gemini  to check it.')
            service = None
        else:
            page.say(f'  Gemini: {settings.gemini_model}. On the free tier, Google may use what it receives to improve its products, and people may read it.')
    else:
        page.say('  Gemini: not used (--no-gemini). The fixed wording is shown.')

    owns_finder = finder is None
    if finder is None:
        finder = open_finder(args.hand_model or settings.hand_model, page)
        if finder is None:
            page.say()
            return 1
    try:
        checked = {}
        for side, path in (('left', pair[0]), ('right', pair[1])):
            result = check_photo(path.read_bytes(), side, settings.max_pixels, finder)  # type: ignore[arg-type]
            checked[side] = result
            if not result.ok:
                page.say()
                page.say(f'  The {side} photo ({path.name}) does not pass the photo checks:')
                for c in result.result.checks:
                    if c.status == 'fail':
                        page.wrapped(f'{c.label}: {c.message}', '      ', '    - ')
                page.say()
                return 1
        started = time.monotonic()
        now = datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        reading = make_real_reading('rd_live_report', 'prf_live_report', checked, now)  # type: ignore[arg-type]
        page.say(f'  lines found in {time.monotonic() - started:.1f} s')
    finally:
        if owns_finder and hasattr(finder, 'close'):
            finder.close()

    hands = {'left': reading.hands.left, 'right': reading.hands.right}
    page.say()
    page.say('WHAT WAS FOUND')
    show_findings(page, hands)

    accepted: dict[str, str] = {}
    if service is not None:
        fields = plan_fields(hands)
        page.say()
        page.say(f'WHAT GEMINI IS TOLD  (the findings as words, nothing else about you; {len(fields)} passages are asked for)')
        payload = findings_payload(hands)
        for side in ('left', 'right'):
            page.wrapped(json.dumps(payload[side], separators=(',', ':')), '    ', f'  {side:5s} ')
        page.say('  Asking Gemini... (this can take up to a minute)')
        started = time.monotonic()
        outcome: Outcome = write_report(hands, reading.report, service)
        seconds = time.monotonic() - started
        accepted = outcome.accepted
        reading = reading.model_copy(update={'report': outcome.report, 'meta': meta_for(outcome, service)})
        repeated = ', repeated once because Google was busy' if outcome.repeats else ''
        page.say(f'  Gemini wrote {len(accepted)} of {outcome.asked} passages that passed every check ({outcome.calls} request{"" if outcome.calls == 1 else "s"}{repeated}, {seconds:.1f} s).')
        if outcome.replaced:
            page.say('  These kept the fixed wording, and why:')
            for key, reasons in outcome.replaced.items():
                page.wrapped(f'{key}: {"; ".join(reasons)}', '        ', '    ')
        if outcome.error is not None:
            page.wrapped(f'The last request failed: {outcome.error.reason} [{outcome.error.kind}] {redact(outcome.error.detail, settings.gemini_api_key, 300)}', '      ', '  ')
        if note_for(outcome):
            page.wrapped(f'note: {note_for(outcome)}', '      ', '  ')

    show_report(page, reading, accepted, used=service is not None)

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f'live_report_{folder.name}.txt'
    target.write_text('\n'.join(page.lines) + '\n', encoding='utf-8')
    page.say()
    page.say(f'A text copy of this is saved in {target}')
    page.say('It describes your palms: keep it out of the project, and never commit it.')
    if service is not None:
        page.say('Now READ the Gemini passages as an examiner would. Copy to me anything that sounds like a prediction, a medical or money claim,')
        page.say('advice, or a mark your hands do not show.')
    page.say()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except ModelUnavailable as exc:  # not expected: the writer never raises for what Gemini does
        print(f'  Gemini failed: {exc.reason}')
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        print('Stopped.')
        sys.exit(1)
