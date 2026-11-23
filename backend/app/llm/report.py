"""THE FIXED-RULE REPORT WRITER. It builds the report in exactly the shape the real writer returns, from fixed sentences in a
fortune teller's voice (llm/knowledge.py, which reads the knowledge-base entries in llm/kb/). Nothing is written about a line
that was not clearly seen.

It has two jobs. It writes the whole report for the website's built-in sample drawings (labelled a sample), and it is the
BASE of every real reading: llm/writer.py gives the findings and the matching knowledge-base entries to Gemini, checks each
passage it returns (llm/guard.py) and puts the accepted passages in place of the ones written here. A passage the model did
not write, or that failed its checks, stays as this file wrote it, so a reading always finishes and is never worse than the
fixed wording.
"""

from __future__ import annotations

from app.cv.findings import PALM_SQUARE_AT, REAL_FINGERS_LONG_AT
from app.cv.versions import (
    REAL_DETECTOR,
    REAL_PIPELINE,
    STAND_IN_DETECTOR,
    STAND_IN_PIPELINE,
)
from app.llm import kb
from app.llm.copy import DISCLAIMER_LONG
from app.llm.knowledge import (
    FEATURE_NAMES,
    FEATURE_ORDER,
    KB_VERSION,
    THEMES,
    line_clause,
    list_words,
    shape_clause,
    shape_traditional_text,
    source_name,
    traditional_text,
)
from app.schemas import (
    FeatureResult,
    HandAnalysis,
    HandSide,
    ObservedPair,
    PalmShape,
    ReadingMeta,
    Report,
    ReportSection,
    ShapeSection,
    SideObservation,
    StatusCounts,
    ThemeSection,
    TraditionalPair,
)

PROMPT_VERSION = 'fixed-rules 1.0'

#: Says where the words came from. `mock: True` makes the website label the reading a sample.
STAND_IN_META = ReadingMeta(
    provider='sample',
    model='stand-in-writer',
    knowledgeBase=KB_VERSION,
    prompt=PROMPT_VERSION,
    pipeline=f'{STAND_IN_PIPELINE} + {STAND_IN_DETECTOR}',
    mock=True,
)

#: A reading whose lines were really found in the person's photos, with the words written from the knowledge base by
#: fixed rules. This is what a real reading says when the language model is not used (llm/writer.py replaces it with the
#: model's own meta when it is). `mock: False`: the website draws the lines on the person's own photo.
REAL_META = ReadingMeta(
    provider='knowledge-base',
    model='rule-based-writer',
    knowledgeBase=KB_VERSION,
    prompt=PROMPT_VERSION,
    pipeline=f'{REAL_PIPELINE} + {REAL_DETECTOR}',
    mock=False,
)

SIDES: tuple[HandSide, HandSide] = ('left', 'right')

#: a measured ratio this close to the line between two shape words (in the ratio's own units) counts as "close to the line"
NEAR_THE_LINE = 0.05

RANK_LENGTH = {'short': 0, 'medium': 1, 'long': 2}
RANK_CURVE = {'straight': 0, 'gentle': 1, 'pronounced': 2}


def near_the_line(shape: PalmShape) -> list[str]:
    """What about a real hand's shape was measured so close to the dividing line that another photo of the same hand could give
    the other word. The word is still given (it is what the measurement says); the report just says how firm it is."""
    if shape.status != 'detected' or shape.method != REAL_DETECTOR:
        return []
    out: list[str] = []
    if shape.fingerRatio is not None and abs(shape.fingerRatio - REAL_FINGERS_LONG_AT) <= NEAR_THE_LINE:
        out.append(f'the finger length ({shape.fingerRatio:.2f}) is close to the line between short and long fingers')
    if shape.palmRatio is not None and abs(shape.palmRatio - PALM_SQUARE_AT) <= NEAR_THE_LINE:
        out.append(f'the palm width ({shape.palmRatio:.2f}) is close to the line between a square and a long palm')
    return out


def count_statuses(hands: dict[str, HandAnalysis]) -> StatusCounts:
    """How many of the ten findings (five lines on each hand) have each status."""
    counts = {'detected': 0, 'uncertain': 0, 'not_visible': 0}
    for side in SIDES:
        for f in hands[side].features:
            counts[f.status] += 1
    return StatusCounts(**counts)


def compare_parts(name: str, left: FeatureResult, right: FeatureResult) -> tuple[str, str | None] | None:
    """How one line compares across the hands, in two parts: what the photos show (always measured, so always written by
    the server) and what the tradition reads from it. The second part is None when only one hand showed the line, because
    there is nothing to read from a comparison then. The whole result is None when neither hand showed the line."""
    lower = name.lower()
    if left.status == 'detected' and right.status == 'detected':
        bits: list[str] = []
        li = RANK_LENGTH[left.traits.length or 'medium']
        ri = RANK_LENGTH[right.traits.length or 'medium']
        if li == ri:
            bits.append(f'The {lower} looks similar in length on both hands')
        else:
            bits.append(f'The {lower} looks longer on the {"left" if li > ri else "right"} hand')
        cl = RANK_CURVE[left.traits.curve or 'gentle']
        cr = RANK_CURVE[right.traits.curve or 'gentle']
        if cl != cr:
            bits.append(f'and more curved on the {"left" if cl > cr else "right"}')
        same = li == ri and cl == cr
        tail = kb.get('compare.same' if same else 'compare.differ').text
        return f'{" ".join(bits)}.', tail
    if left.status == 'detected' or right.status == 'detected':
        side = 'left' if left.status == 'detected' else 'right'
        return f'Only the {side} hand showed this line clearly, so the two hands are not compared on it.', None
    return None


def compare_feature(name: str, left: FeatureResult, right: FeatureResult) -> str | None:
    parts = compare_parts(name, left, right)
    return None if parts is None else ' '.join(x for x in parts if x)


def best_detected(src: str, hands: dict[str, HandAnalysis]) -> tuple[str, str] | None:
    """The detected source that scored best on either hand, with a clause about it. None when detected on neither."""
    best: tuple[str, str, float] | None = None
    for side in SIDES:
        if src == 'shape':
            shape = hands[side].palmShape
            score = shape.confidence or 0.0
            if shape.status == 'detected' and (best is None or score > best[2]):
                best = (side, shape_clause(shape.traits), score)
        else:
            f = next(x for x in hands[side].features if x.id == src)
            score = f.confidence or 0.0
            if f.status == 'detected' and (best is None or score > best[2]):
                best = (side, line_clause(src, f.traits), score)
    return (best[0], best[1]) if best else None


def left_out_sentence(left_out: list[str]) -> str:
    """The sentence that closes a theme and says which of its sources were not used, because they were not clearly seen."""
    if not left_out:
        return ''
    names = list_words([source_name(x).lower() for x in left_out])
    return f'Left out, because {"it was" if len(left_out) == 1 else "they were"} not clearly seen: the {names}.'


def build_themes(hands: dict[str, HandAnalysis]) -> list[ThemeSection]:
    """The "by theme" view: each theme is written only from the lines (and hand shape) that were detected, and says
    what it left out."""
    out: list[ThemeSection] = []
    for theme in THEMES:
        used: list[tuple[str, str, str]] = []  # (source, side, text)
        left_out: list[str] = []
        for src in theme.sources:
            found = best_detected(src, hands)
            if found:
                used.append((src, found[0], found[1]))
            else:
                left_out.append(src)
        if not used:
            out.append(ThemeSection(themeId=theme.id, title=theme.title, traditional=None, basedOn=[], leftOut=left_out))  # type: ignore[arg-type]
            continue
        sentences = [f'{source_name(src)} ({side} hand): {text}' for src, side, text in used]
        skipped = left_out_sentence(left_out)
        # one short paragraph per line of text: the introduction, one for each source that was used, what was left out, the reminder
        text = '\n'.join(x for x in [theme.intro, *sentences, skipped, theme.outro] if x)
        out.append(ThemeSection(themeId=theme.id, title=theme.title, traditional=text, basedOn=[u[0] for u in used], leftOut=left_out))  # type: ignore[arg-type]
    return out


def build_shape_section(hands: dict[str, HandAnalysis]) -> ShapeSection:
    left = hands['left'].palmShape
    right = hands['right'].palmShape
    comparison: str | None = None
    if left.status == 'detected' and right.status == 'detected':
        if left.traits.palm == right.traits.palm and left.traits.fingers == right.traits.fingers:
            comparison = 'The hand shape looks the same on both hands, as it normally does.'
        else:
            comparison = (
                f'The two photos suggest slightly different proportions (left: {left.traits.palm} palm, {left.traits.fingers} fingers; '
                f'right: {right.traits.palm} palm, {right.traits.fingers} fingers). That usually comes from the angle of each photo, '
                'so no meaning is read into it.'
            )
    elif left.status == 'detected' or right.status == 'detected':
        comparison = f'Only the {"left" if left.status == "detected" else "right"} hand was clear enough to judge its shape, so the two hands are not compared.'
    return ShapeSection(
        observed=ObservedPair(left=SideObservation(status=left.status, text=left.observation), right=SideObservation(status=right.status, text=right.observation)),
        traditional=TraditionalPair(left=shape_traditional_text(left.status, left.traits), right=shape_traditional_text(right.status, right.traits)),
        comparison=comparison,
    )


def build_report(hands: dict[str, HandAnalysis], created_at: str) -> Report:
    def get(side: str, fid: str) -> FeatureResult:
        return next(f for f in hands[side].features if f.id == fid)

    sections: list[ReportSection] = []
    for fid in FEATURE_ORDER:
        left, right = get('left', fid), get('right', fid)
        sections.append(
            ReportSection(
                featureId=fid,  # type: ignore[arg-type]
                title=FEATURE_NAMES[fid],
                observed=ObservedPair(left=SideObservation(status=left.status, text=left.observation), right=SideObservation(status=right.status, text=right.observation)),
                traditional=TraditionalPair(left=traditional_text(fid, left.status, left.traits), right=traditional_text(fid, right.status, right.traits)),
                comparison=compare_feature(FEATURE_NAMES[fid], left, right),
            )
        )

    both: list[str] = []
    one: list[str] = []
    none: list[str] = []
    for fid in FEATURE_ORDER:
        n = sum(1 for s in SIDES if get(s, fid).status == 'detected')
        name = FEATURE_NAMES[fid].lower()
        (both if n == 2 else one if n == 1 else none).append(name)
    sentences = ['Both photos were used.']
    if both:
        sentences.append(f'The {list_words(both)} {"was" if len(both) == 1 else "were"} found clearly on both hands.')
    if one:
        sentences.append(f'The {list_words(one)} {"was" if len(one) == 1 else "were"} clear on only one hand.')
    if none:
        sentences.append(f'The {list_words(none)} could not be seen clearly, so nothing is said about {"it" if len(none) == 1 else "them"}.')
    sentences.append('Below, what your photos show is kept apart from what your lines foretell.')

    uncertainty: list[str] = []
    for side in SIDES:
        cap_side = 'Left' if side == 'left' else 'Right'
        for fid in FEATURE_ORDER:
            f = get(side, fid)
            if f.status == 'uncertain':
                uncertainty.append(
                    f'{cap_side} hand, {FEATURE_NAMES[fid].lower()}: uncertain. Something line-like is there, but it was too faint or broken to judge, so the reading gives only a rough hint of it.'
                )
            if f.status == 'not_visible':
                uncertainty.append(f'{cap_side} hand, {FEATURE_NAMES[fid].lower()}: not visible. Nothing is said about it.')
        shape = hands[side].palmShape
        if shape.status == 'uncertain':
            uncertainty.append(f'{cap_side} hand, shape: uncertain. The hand was not clearly in view, so only a loose note is given.')
        if shape.status == 'not_visible':
            uncertainty.append(f'{cap_side} hand, shape: not measured. Nothing is said about it.')
        near = near_the_line(shape)
        if near:
            uncertainty.append(f'{cap_side} hand, shape: {" and ".join(near)}, so another photo of the same hand could be called the other way.')
        n = len(hands[side].otherCreases)
        if n:
            uncertainty.append(
                f'{cap_side} hand: {n} other {"crease was" if n == 1 else "creases were"} found that {"does" if n == 1 else "do"} not match one of the five main lines. '
                f'{"It is" if n == 1 else "They are"} drawn thinly and not named, and nothing is said about {"it" if n == 1 else "them"}.'
            )
        q = hands[side].quality
        issues: list[str] = []
        if q.sharpness != 'good':
            issues.append('a little soft')
        if q.lighting != 'good':
            issues.append('not evenly lit')
        if q.resolution != 'good':
            issues.append('on the small side')
        if issues:
            uncertainty.append(f'The {side} photo was {" and ".join(issues)}, which can make faint lines harder to find.')

    return Report(
        summary=' '.join(sentences),
        sections=sections,
        themes=build_themes(hands),
        shape=build_shape_section(hands),
        uncertainty=uncertainty,
        disclaimer=DISCLAIMER_LONG,
        generatedAt=created_at,
    )


def headline_for(hands: dict[str, HandAnalysis]) -> str:
    """One line that says what a reading found, for list rows."""
    both = [fid for fid in FEATURE_ORDER if all(next(f for f in hands[s].features if f.id == fid).status == 'detected' for s in SIDES)]
    if both:
        names = list_words([FEATURE_NAMES[fid].replace(' line', '').lower() for fid in both])
        text = f'{names} {"line" if len(both) == 1 else "lines"} clear on both hands'
        return text[:1].upper() + text[1:]
    c = count_statuses(hands)
    return f'{c.detected} of 10 lines detected, {c.uncertain} uncertain'
