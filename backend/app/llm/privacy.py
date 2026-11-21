"""What is taken out of a question before it is sent to Gemini.

A report is written from findings that are only words from short fixed lists, so nothing personal can be in them. A chat
question is typed by a person, so it can hold anything: a name, an e-mail address, a phone number. Before a question (or an
earlier message of the same chat) goes to Gemini, this removes those. It is not a promise that nothing personal can ever be
typed (a person can write what they like), which is why the website also says, next to the chat box, that questions are sent
to Gemini. Photos are never sent at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

EMAIL = re.compile(r'\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b')
LINK = re.compile(r'(?:https?://|www\.)\S+', re.IGNORECASE)
#: seven or more digits, possibly with spaces, dashes, dots, brackets or a leading plus: a phone number or an id
NUMBER = re.compile(r'(?<![\w])[+(]?\d[\d\s().-]{5,}\d(?![\w])')


def name_parts(names: Iterable[str]) -> list[str]:
    """Every name given, and each word of it of three letters or more, longest first (so "Saji Kumar" goes before "Saji")."""
    parts: set[str] = set()
    for name in names:
        name = name.strip()
        if len(name) < 2:
            continue
        parts.add(name)
        parts.update(word for word in re.split(r'\s+', name) if len(word) >= 3)
    return sorted(parts, key=len, reverse=True)


def scrub(text: str, names: Iterable[str] = ()) -> str:
    """The text with e-mail addresses, links, long numbers and the given names replaced by a bracketed word."""
    text = EMAIL.sub('[email removed]', text)
    text = LINK.sub('[link removed]', text)
    text = NUMBER.sub('[number removed]', text)
    for part in name_parts(names):
        text = re.sub(rf'(?<!\w){re.escape(part)}(?!\w)', '[name]', text, flags=re.IGNORECASE)
    return text
