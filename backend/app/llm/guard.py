"""The safety checks that every passage written by the language model must pass before it is shown or saved.

The model is asked to follow rules (llm/prompts.py), but a request is not a guarantee, so each passage it returns is
checked here, by plain rules that do not depend on the model. A passage that fails is asked for again once and, if it
fails again, replaced by the fixed-rule wording (llm/writer.py). A reading therefore always finishes, and it never
contains a passage that broke a rule.

The reading speaks like a fortune teller: it foretells ("you will ...", "love is coming to you", "the road ahead opens"), with
conviction, and nobody has to hedge every sentence. So what the rules guard is not the voice but what the voice may be used
for. What they catch, in the order they run:

  plain         empty, too long, a link or an e-mail address, a number (numbers are where invented ages, dates and
                percentages come from), a list where sentences were asked for
  anchor        the words must be about the palm: they name a line, the hand, the palm or the fingers
  plain         the words are everyday words: no fancy, "spiritual" or technical ones ("tapestry", "resilience", "temperament"
                ...). A report passage that uses one is asked for again in plain words (a chat answer is not held to this:
                it has no second try, so a plain-words instruction in the prompt has to do)
  timing        a prediction may be as sure as it likes, but it names no time: no ages, years, months, dates, "next year",
                "within six months", "in your thirties". Soft time ("soon", "in time", "one day") is the reader's own.
  advice        orders and recommendations ("you should ...", "I recommend ..."): a reader foretells, and does not decide
                for anyone
  sensitive     health, illness, injury, pregnancy and children, how long anyone will live, money in sums and instruments,
                and misfortune of any kind (betrayal, divorce, accidents, curses ...): never foretold, only mentioned in a
                sentence that says the reading does not speak of them
  overclaim     "guaranteed", "proven", "scientific": the reading is an old art and says so, it makes no claim of proof
  invented      marks and signs that are not among the findings (marriage lines, islands, mounts, other creases ...)
  claims to see "I have analysed your photo ...": the model never sees the photos. (The reader's own "I see a generous
                heart" is a figure of speech, and is fine.)
  not seen      a line that was not clearly seen may only be mentioned to say so
  other hand    a passage about one hand does not talk about the other
  dominant      nothing may assume which of the person's hands is dominant: the reading does not know
  consistency   a passage must not describe a line as short when the findings say long, deep when they say faint, and so on;
                in a chat answer the same test is applied to every sentence that is about one line on one hand

"Only mentioned in a sentence that says ..." is the same test everywhere: the sentence must contain a word of denial
(not, never, nothing, cannot, myth ...). It is deliberately simple. A rule that is easy to explain is easy to trust, and
a false alarm only costs a fallback to the fixed wording, never a wrong reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import FeatureTraits, HandAnalysis, PalmShapeTraits

#: written into a reading's `meta.prompt` beside the prompt version; change it whenever a rule below changes
GUARD_VERSION = 'guard 2.1'

#: the longest each kind of passage may be, in characters
MAX_LENGTH = {
    'summary': 800,
    'line': 700,
    'compare': 450,
    'shape': 600,
    'theme': 1100,
    'chat': 1800,
    'limits': 700,
}

LINE_NAMES = {
    'heart': r'heart',
    'head': r'head',
    'life': r'life',
    'fate': r'fate|destiny',
    'sun': r'sun|apollo',
}


def rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


#: a word of denial or limitation
NEGATION = rx(
    r"\b(?:not|no|never|nothing|none|cannot|can't|cant|isn't|aren't|wasn't|weren't|doesn't|don't|didn't|won't|wouldn't|shouldn't|without|neither|nor|myth|rather than|instead of)\b|n't\b"
)
#: for a line that was not clearly seen: the words that say so
NOT_SEEN = rx(
    r"\b(?:not|no|never|nothing|none|cannot|can't|couldn't|wasn't|weren't|without|unseen|unclear|uncertain|faint|faintly|tentative|tentatively|loose|loosely|partly|partially|missing|absent|hard to)\b|n't\b"
)

URL = rx(r'https?:|www\.|\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b')
DIGIT = rx(r'\d')
#: a passage of the report is about the palm: it names a line, the hand, the palm or the fingers
ANCHOR = rx(r'\b(?:palms?|lines?|hands?|fingers?|thumbs?|creases?)\b|palmist')
#: a chat answer may also be about the reading itself (how sure it is, what was seen)
CHAT_ANCHOR = rx(
    r'\b(?:palms?|lines?|hands?|fingers?|thumbs?|creases?)\b|palmist|tradition|this reading|the reading|findings|detected|photo|seen|saw|found|clearly|uncertain|not visible'
)

NUMBER_WORDS = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
    r"|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|dozen|couple|few|several)"
)
TIME_UNITS = r"(?:years?|months?|weeks?|days?|hours?|decades?|centuries)"
#: when something will happen. A fortune teller says "soon", "in time", "one day"; she does not give a date, an age or a count.
TIMING = rx(
    r"\b(?:next|coming|upcoming|this|last) (?:year|month|week|decade)s?\b"
    r"|\b(?:next|this|last) (?:spring|summer|autumn|fall|winter)\b"
    rf"|\bwithin\b(?:\W+\w+){{0,3}}?\W+{TIME_UNITS}\b"
    rf"|\b(?:in|after|for|over) (?:an? |the )?(?:next |coming |following )?{NUMBER_WORDS}(?:\W+\w+)?\W+{TIME_UNITS}\b"
    r"|\bin an? (?:year|month|week|day)\b"
    r"|\bin (?:your|the) (?:early |late |mid |middle )?(?:teens|twenties|thirties|forties|fifties|sixties|seventies|eighties)\b"
    r"|\b(?:at|by|around|before|after|until|aged?) (?:the )?age\b"
    r"|\bat (?:the age of )?(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ]\w+)?\b"
)
#: a month named as a date ("in November"); "may" and "march" are left out because they are also ordinary words
MONTH = re.compile(r"\b(?:in|by|on|before|after|until|since) (?:January|February|April|June|July|August|September|October|November|December)\b")
ADVICE = rx(
    r"\byou (?:should|must|ought|need to|have to|had better|would do well to)\b|\b(?:i|we) (?:recommend|suggest|advise|urge)\b|\bmy advice\b|\bit would be wise\b|\bit is wise to\b|\bbest (?:thing|course of action) (?:is|would be)\b"
    r"|\b(?:be sure to|make sure (?:that )?you|do not forget to|don't forget to|remember to)\b"
)

SENSITIVE = {
    'health': rx(
        r"\b(?:health\w*|medical|medicine|medication|doctors?|diagnos\w*|diseases?|illness\w*|sick\w*|cancer|diabet\w*|disorders?|symptoms?|treatments?|therap\w*|pregnan\w*|fertil\w*|surgery|stroke|depress\w*|injur\w*|babies|baby|newborns?|children|childbirth|offspring)\b"
    ),
    'lifespan': rx(
        r"\b(?:lifespan|life expectancy|longevity|live longer|(?:longer|long|short|shorter) life\b(?! line)|live (?:a )?(?:long|longer|short|shorter|to|for)|how long (?:you|one|someone|anyone|a person|people) (?:will |would |can |may )?(?:live|last)|die\w*|death|dead|dying|mortality)\b"
    ),
    'money': rx(r"\b(?:invest\w*|stocks?|crypto\w*|bitcoin|lottery|gambl\w*|betting|salary|debts?|loans?|mortgage|taxes|tax)\b"),
    'misfortune': rx(
        r"\b(?:divorc\w*|betray\w*|cheat\w*|unfaithful\w*|infidel\w*|affairs?|bankrupt\w*|ruin\w*|accidents?|tragic\w*|tragedy|disasters?|curses?|cursed|misfortunes?|heartbreaks?|heartbroken|widow\w*|grief|doom\w*|fired|sacked|jail|prison|arrest\w*|lawsuits?|violen\w*|abandon\w*|failure|failures|poverty|penniless)\b"
    ),
}
OVERCLAIM = rx(
    r"\b(?:guarantee[ds]?|proven|scientific(?:ally)?|infallible|cannot fail|never fails?|never wrong|never lies?|100 ?%|certain to)\b"
)

#: fancy, "spiritual" or technical words a normal person does not use or may not understand. Kept short on purpose: it is the words
#: a language model reaches for when it is asked to sound like a fortune teller, not every word that could be simpler.
FANCY = rx(
    r"\b(?:tapestr\w*|embrac\w*|resonat\w*|navigat\w*|harness\w*|unlock\w*|essence|radiat\w*|radiant|vibrant|holistic|synerg\w*|manifest\w*"
    r"|auras?|vibes?|vibrations?|energies|cosmic|cosmos|universe|ethereal|luminous|profound\w*|transform\w*|empower\w*|authentic\w*"
    r"|resilien\w*|intuiti\w*|introspect\w*|multifacet\w*|dynamic\w*|innate\w*|nurtur\w*|analytic\w*|pragmat\w*|temperament\w*"
    r"|vitality|empath\w*|communicative|appreciative|fulfil\w*|abundan\w*|harmon\w*|serene|serenity|equilibrium|grounded|mindful\w*"
    r"|trajectory|life force|vital (?:spirit|energy|force)|inner (?:strength|peace|self|world|light|voice|fire|child|compass))\b"
)
INVENTED = rx(
    r"\bmounts? of\b|\bmarriage lines?\b|\blove lines?\b|\bgirdle\b|\bbracelets?\b|\bsimian\b|\bmercury line\b|\bhealth line\b|\btravel lines?\b"
    r"|\bchild(?:ren)? lines?\b|\bintuition line\b|\bring of (?:solomon|saturn|jupiter)\b|\bislands?\b|\bforks?\b|\bforked\b|\bchained\b"
    r"|\btassels?\b|\bbreaks? (?:in|on) (?:the|your|a)\b|\bbroken line\b|\bother creases?\b|\bextra creases?\b|\bminor lines?\b"
)
#: claims to have looked at the photos or analysed them. "I see a generous heart" is the reader's figure of speech and is allowed.
CLAIMS_TO_SEE = rx(
    r"\bi(?:'ve| have)? (?:looked at|examined|analysed|analyzed|studied|scanned|inspected)\b|\bmy (?:analysis|algorithm|scan|software|sensors?)\b"
    r"|\b(?:the|your|this|these) (?:photos?|pictures?|images?|selfies?|scans?)\b(?:\W+\w+){0,2}?\W+(?:shows?|reveals?|tells?|proves?)\b"
)

ASSUMES_DOMINANT = rx(r"\b(?:your|the person(?:'s)?) (?:non-?dominant|dominant|writing|main) hand\b")

OTHER_HAND = {
    'left': rx(r"\bright (?:hand|palm)\b|\bboth (?:hands|palms)\b|\bthe other (?:hand|palm)\b"),
    'right': rx(r"\bleft (?:hand|palm)\b|\bboth (?:hands|palms)\b|\bthe other (?:hand|palm)\b"),
}

#: a word that says "left hand" / "right hand" in a sentence about a line (for the chat's consistency check)
SIDE_WORD = {'left': rx(r"\bleft\b"), 'right': rx(r"\bright\b(?! now| away| time| of)")}
#: words that describe how a line looks: said about a line that was not clearly seen, they are a claim about something unseen
LOOK_WORDS = rx(r"\b(?:long|longer|short|shorter|straight|straighter|curved|curving|curve|pronounced|deep|deeply|faint|clear|clearly|wide|sharp)\b")

# ---- consistency between a passage and the findings it is about. Each pattern is a description that CONTRADICTS a finding.
GAP = r"(?:\W+\w+){0,2}?\W+"
BE = r"(?:is|are|was|were|looks|look|appears|appear|seems|seem|runs|run|measures|measure)"
INTENSIFIER = r"(?:(?:very|quite|fairly|rather|relatively|noticeably|slightly|somewhat|also|still|generally|really|more|so|too)\W+){0,2}"


def describes(adjectives: str, nouns: str) -> re.Pattern[str]:
    """A description in either word order: "a long line" (the adjective first) or "the line is long" (the adjective after
    a form of "to be", with at most an intensifier such as "quite" between). "how long the line is" is a question word, not a claim."""
    return rx(
        rf"(?<!how )\b(?:{adjectives}){GAP}(?:{nouns})\b"
        rf"|\b(?:{nouns})\b(?:\W+\w+){{0,4}}?\W+{BE}\W+{INTENSIFIER}(?:{adjectives})\b"
    )


LONG_LINE = describes('long|longer|longest', 'line|course|sweep|path')
SHORT_LINE = describes('short|shorter|shortest', 'line|course|sweep|path')
STRONG_CURVE = describes('pronounced|deep|deeply|sharp|sharply|strong|strongly|wide|steep|steeply', 'curve|curved|curving|sweep|slope|sloping|bend|bending')
STRAIGHT_LINE = describes('straight|straighter', 'line|course|path')
DEEP_MARK = rx(rf"\bdeep(?:ly)?{GAP}(?:marked|etched|grooved)\b|{describes('deep|deeply', 'line').pattern}")
FAINT = rx(r"\bfaint(?:ly)?\b|\bshallow\b|\bfine line\b")
CLEAR_MARK = rx(r"\bclearly marked\b|\bwell[- ]marked\b")
SQUARE_PALM = describes('square', 'palm|hand')
LONG_PALM = describes('long|rectangular|narrow', 'palm')
LONG_FINGERS = describes('long|longer', 'fingers')
SHORT_FINGERS = describes('short|shorter', 'fingers')


@dataclass(frozen=True)
class Subject:
    """What a passage is about, so the rules know what would be a mistake."""

    #: summary | line | compare | shape | theme | chat | limits
    kind: str
    side: str | None = None
    traits: FeatureTraits | None = None
    shape: PalmShapeTraits | None = None
    #: the lines that were not detected on either hand (uncertain or not visible): they may only be mentioned to say so
    unseen: frozenset[str] = frozenset()
    #: for a chat answer: the findings of both hands, so a sentence about one line on one hand can be checked against them
    hands: dict[str, HandAnalysis] | None = None


# ------------------------------------------------------------------ cleaning


def clean(text: str) -> str:
    """Plain text for the screen, which shows paragraphs and "• " bullets and nothing else. Markdown the model may have
    added (bold, headings, "- " bullets) is turned into that, and nothing else about the words is changed."""
    text = str(text).replace('\r\n', '\n').replace('\r', '\n').replace('’', "'").replace('‘', "'")
    text = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', text)
    text = re.sub(r'(?m)^\s*(?:[-*•]|\d+[.)])\s+', '• ', text)  # before the emphasis marks go, or "* item" would lose its star
    text = re.sub(r'[*_`]{1,3}', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' ?\n ?', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip().strip('"').strip()


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if s.strip()]


# ------------------------------------------------------------------ the rules


def line_mention(line: str) -> re.Pattern[str]:
    return rx(rf"\b(?:{LINE_NAMES[line]})(?: line)?\b" if line in ('fate', 'sun') else rf"\b(?:{LINE_NAMES[line]}) line\b")


def contradictions(text: str, traits: FeatureTraits | None, shape: PalmShapeTraits | None) -> list[str]:
    """What the text says about a line (or a hand shape) that the findings contradict. A sentence with a word of denial is not
    judged: "not a short line" does not say the line is short."""
    problems: list[str] = []
    for sentence in sentences(text):
        if NEGATION.search(sentence):
            continue
        problems.extend(sentence_contradictions(sentence, traits, shape))
    return problems


def sentence_contradictions(text: str, traits: FeatureTraits | None, shape: PalmShapeTraits | None) -> list[str]:
    problems: list[str] = []
    if traits:
        if traits.length in ('long', 'medium') and SHORT_LINE.search(text):
            problems.append(f'calls the line short, but the findings say {traits.length}')
        if traits.length in ('short', 'medium') and LONG_LINE.search(text):
            problems.append(f'calls the line long, but the findings say {traits.length}')
        if traits.curve == 'straight' and STRONG_CURVE.search(text):
            problems.append('describes a strong curve, but the findings say straight')
        if traits.curve == 'pronounced' and STRAIGHT_LINE.search(text):
            problems.append('calls the line straight, but the findings say pronounced curve')
        if traits.clarity == 'clear' and (DEEP_MARK.search(text) or FAINT.search(text)):
            problems.append('describes the line as deep or faint, but the findings say clear')
        if traits.clarity == 'deep' and FAINT.search(text):
            problems.append('calls the line faint, but the findings say deep')
        if traits.clarity == 'faint' and (DEEP_MARK.search(text) or CLEAR_MARK.search(text)):
            problems.append('calls the line deeply or clearly marked, but the findings say faint')
    if shape:
        if shape.palm == 'square' and LONG_PALM.search(text):
            problems.append('calls the palm long, but the findings say square')
        if shape.palm == 'long' and SQUARE_PALM.search(text):
            problems.append('calls the palm square, but the findings say long')
        if shape.fingers == 'short' and LONG_FINGERS.search(text):
            problems.append('calls the fingers long, but the findings say short')
        if shape.fingers == 'long' and SHORT_FINGERS.search(text):
            problems.append('calls the fingers short, but the findings say long')
    return problems


def chat_contradictions(text: str, hands: dict[str, HandAnalysis]) -> list[str]:
    """Sentences of a chat answer that are about ONE line on ONE hand ("your left heart line ...") are held to the findings for
    that line on that hand: not a long line called short, and no description of a line that was not clearly seen there. A
    sentence about several lines or both hands is not judged (it would be a guess which claim belongs to which)."""
    problems: list[str] = []
    for sentence in sentences(text):
        lines = [fid for fid in LINE_NAMES if line_mention(fid).search(sentence)]
        sides = [side for side, pattern in SIDE_WORD.items() if pattern.search(sentence)]
        if len(lines) != 1 or len(sides) != 1:
            continue
        fid, side = lines[0], sides[0]
        found = next(f for f in hands[side].features if f.id == fid)
        if found.status == 'detected':
            problems.extend(f'{why}: "{shorten(sentence)}"' for why in contradictions(sentence, found.traits, None))
        elif LOOK_WORDS.search(sentence) and not NOT_SEEN.search(sentence):
            problems.append(f'describes the {side} hand\'s {fid} line, which was not clearly seen on that hand: "{shorten(sentence)}"')
    return problems


def check(text: str, subject: Subject) -> list[str]:
    """Every rule a passage breaks, in words. An empty list means it passed. `text` should already be `clean`ed."""
    problems: list[str] = []
    kind = subject.kind
    if len(text.strip()) < 20:
        return ['is empty or far too short']
    if len(text) > MAX_LENGTH.get(kind, 1100):
        problems.append(f'is too long ({len(text)} characters; the limit is {MAX_LENGTH.get(kind, 1100)})')
    if URL.search(text):
        problems.append('contains a link or an e-mail address')
    if DIGIT.search(text):
        problems.append('contains a number (write numbers as words, and never give ages, dates or percentages)')
    if kind != 'chat' and re.search(r'(?m)^• ', text):
        problems.append('is a list (write plain sentences)')

    if kind != 'limits' and not (CHAT_ANCHOR if kind == 'chat' else ANCHOR).search(text):
        problems.append('is not about the palm (name the line, the hand or the palm it reads)')

    if kind != 'chat':
        fancy = sorted({m.group(0).lower() for m in FANCY.finditer(text)})
        if fancy:
            problems.append(f'uses fancy or technical words ({", ".join(fancy)}): say it in plain everyday words, in short sentences')

    unseen = [line_mention(line) for line in subject.unseen]
    unseen_names = sorted(subject.unseen)
    for sentence in sentences(text):
        denied = bool(NEGATION.search(sentence))
        if (TIMING.search(sentence) or MONTH.search(sentence)) and not denied:
            problems.append(f'gives a time, an age or a date, which a prediction must not (say "soon" or "in time"): "{shorten(sentence)}"')
        if ADVICE.search(sentence) and not denied:
            problems.append(f'gives advice or an order (foretell instead): "{shorten(sentence)}"')
        for topic, pattern in SENSITIVE.items():
            if pattern.search(sentence) and not denied:
                problems.append(f'speaks about {topic}, which a reading never foretells: "{shorten(sentence)}"')
        if OVERCLAIM.search(sentence) and not denied:
            problems.append(f'claims proof or certainty that palmistry cannot give: "{shorten(sentence)}"')
        for line, pattern in zip(unseen_names, unseen, strict=True):
            if pattern.search(sentence) and not NOT_SEEN.search(sentence):
                problems.append(f'talks about the {line} line, which was not clearly seen: "{shorten(sentence)}"')
        if ASSUMES_DOMINANT.search(sentence) and not denied:
            problems.append(f'assumes which hand is dominant, which this reading does not know: "{shorten(sentence)}"')
        if CLAIMS_TO_SEE.search(sentence):
            problems.append(f'claims to have looked at the photos, which the model never sees: "{shorten(sentence)}"')
    if INVENTED.search(text):
        problems.append(f'mentions a mark or sign that is not among the findings ("{INVENTED.search(text).group(0)}")')  # type: ignore[union-attr]
    if subject.side and kind in ('line', 'shape') and OTHER_HAND[subject.side].search(text):
        problems.append('talks about the other hand in a passage about one hand')
    if kind in ('line', 'shape'):
        problems.extend(contradictions(text, subject.traits, subject.shape))
    if kind == 'chat' and subject.hands:
        problems.extend(chat_contradictions(text, subject.hands))
    return list(dict.fromkeys(problems))  # the same complaint once


def shorten(sentence: str, limit: int = 90) -> str:
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + '…'
