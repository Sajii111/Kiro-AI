# The palmistry knowledge base

The language model does not answer from memory. It is handed entries from this folder, and told to stay close to them
(`docs/LLM_DESIGN.md` explains why, in section 2). The fixed-rule writer, which takes over whenever Gemini is not used, writes
from the same entries. So whatever a reading says about palmistry, it says because an entry here says it.

## Status: a draft that the author must check

The 68 entries were **drafted for the project in its own words** from the four sources below, and written the way a palm
reader speaks: to "you", with confidence, about love, work and recognition, prosperity in general, creativity, journeys and
change. The claims about health, length of life, accidents, children, losses and dated events were left out on purpose. They have
been checked by tests (every entry is in the reader's voice and in plain everyday words, names a source, and passes the same safety rules the model's output
must pass; every length, curve and clarity of every line has an entry). **No person has yet checked them against the sources.** Until the author has, call it a *curated draft*, not a
reviewed knowledge base, in the report and in the viva. The review log at the bottom is where that gets recorded.

## What is in it

| File | Entries | What it holds |
| --- | --- | --- |
| `lines.json` | 45 | The five principal lines (heart, head, life, fate, sun): one entry on what each is linked with, then one for each length, curve and clarity the analysis can report |
| `shape.json` | 5 | The four hand shapes named for the elements (earth, air, water, fire), and a general note |
| `themes.json` | 5 | The five themes of the report (your nature, career and calling, fortune and prosperity, love and relationships, what lies ahead): which lines and shapes each is read from, an introduction, and a closing line. The wording of the closing lines is the app's, not Gemini's |
| `compare.json` | 4 | How the tradition reads two hands together: the general idea, hands that match, hands that differ, and a line shown on one hand only |
| `limits.json` | 9 | What the reading never claims (science, medicine, lifespan, money decisions, job decisions, other people's hearts, dates and misfortune) and what it never does (a missing line, a poor photo) |
| `sources.json` | 4 sources | Where the entries come from |
| `__init__.py` | | The loader, `KB_VERSION` and the checks that every file is complete |

## What an entry looks like

```json
{
  "id": "heart.length.long",
  "kind": "line",
  "line": "heart",
  "trait": "length",
  "value": "long",
  "short": "a long heart line promises an open, generous heart: love finds you easily, and you give it back in full measure",
  "text": "A long heart line promises an open, generous heart. Love finds you easily, and you give it back in full measure.",
  "keywords": ["heart line", "heart", "emotions", "long", "length"],
  "basis": ["S1"]
}
```

- `text` is the full statement given to Gemini. It is written as the reader speaks: to "you", sure of itself, and in the soft
  time of a fortune teller ("soon", "in time", "before long"), never with a date, an age or an amount.
- `short` is a clause the fixed-rule writer joins into a sentence when Gemini is not used.
- `keywords` are extra words the chat's search can match, besides the text.
- `basis` names the sources (`S1` to `S4`) the entry was written from. The one entry without a source, `limits.photo`, is about
  this app's own photos (how to take a better one), not about palmistry.
- The other fields depend on `kind`: a `line` entry has `line`, `trait`, `value` and `short`; a `shape` entry has `element`,
  `named`, `shape` and `temperament`; a `theme` entry has `theme`, `title`, `intro`, `outro`, `reads` and `roles`; a `compare`
  entry has `case`; a `limits` entry has `topic`.

## The sources

| | Source | Used for |
| --- | --- | --- |
| **S1** | Cheiro (Count Louis Hamon), *Palmistry for All*, 1916, public domain. [Project Gutenberg ebook 20480](https://www.gutenberg.org/ebooks/20480) | What each principal line is traditionally linked with and promises, and comparing the two hands (one inherited, the other developed). The book also makes claims about health, length of life, accidents and dated events: **this knowledge base leaves those out on purpose** |
| **S2** | HowStuffWorks, [Palm Reading: A Comprehensive Guide to Unlocking the Secrets of Your Hand](https://science.howstuffworks.com/science-vs-myth/extrasensory-perceptions/palm-reading.htm), undated | The four hand shapes named for the elements, and the idea that the dominant and non-dominant hands are read differently. It describes the fire hand as square with short fingers, where most sources use a long palm: the details differ between sources |
| **S3** | Palmistry Path, [Palmistry Hand Shapes: Earth, Air, Fire, and Water Hands](https://palmistry-site.pages.dev/blog/beginner/hand-shapes/), 1 May 2026 | The scheme this project uses: a square palm with short fingers is earth, square with long fingers is air, long with long is water, long with short is fire |
| **S4** | Wikipedia, [Palmistry](https://en.wikipedia.org/wiki/Palmistry) | The names of the lines, and the statements that palmistry is widely viewed as a pseudoscience and that its interpretations contradict one another |

S2 to S4 are web pages that can change, so each entry's wording should be checked against the page as it stands on the day of
the check, and the date written in the review log.

## How to check the entries (about an hour)

You do not need to read all 68 at once. Start with `lines.json`, which holds most of them, then the rest.

1. Open a file and an entry's source side by side. For each entry ask three questions:
   - **Is it in the source, or fair to it?** The entry may paraphrase, but it must not claim more than the source does. If the
     source does not say it, change the entry or delete it.
   - **Is it in the reader's voice?** It speaks to "you" and may say "you will", about love, work, recognition, prosperity in
     general, creativity, journeys and change. Time stays soft ("soon", "in time"): never a date, an age or "within six months".
   - **Is it in plain words?** Short sentences, everyday words, nothing a normal person would have to look up. The words a
     language model likes to reach for ("tapestry", "resonate", "energies", "temperament", "trajectory") are listed as `FANCY`
     in `../guard.py`, and `tests/test_kb.py` fails if one gets in. Say what a line stands for, then what it predicts.
   - **Does it stay out of what the reader never foretells?** Health, lifespan, children, money amounts, which job to take, other
     people's hearts, accidents, loss and "unlucky" signs. If it drifts in, rewrite it.
2. Where several sources disagree (the hand-shape scheme is the clearest case), the entry should say "differs between sources"
   or follow the scheme named in S3, as the shape entries do. Do not hide a disagreement.
3. Edit the entry in place. Keep the `id`, and keep the two fields that a test depends on (`text` and `basis`) filled.
4. Raise `KB_VERSION` in `__init__.py` (for example `palm-kb 3.1`). It is written into every reading's `meta.knowledgeBase`,
   so a reading says which version of the notes it was written from.
5. Run the tests from the `backend` folder: `python -m pytest tests/test_kb.py tests/test_retrieval.py tests/test_guard.py`. A test
   fails if an edited entry breaks a safety rule, loses its source, or no longer covers a finding.
6. Write the result in the review log below.

To add an entry, follow the pattern of its neighbours, give it a new `id`, and name its `basis`. `tests/test_kb.py` has a test
that counts the entries (it currently expects 68), so update that number too.

## What the entries leave out on purpose

Health and illness, how long anyone will live, children and pregnancy, money amounts and investments, which job to take or
whether to leave it, advice on what to do about another person, accidents and every kind of misfortune (loss, betrayal, failure,
heartbreak), ages and dates, "unlucky" signs and curses. Older palmistry books say a great deal about all of these. This app
does not, and its safety checks (`../guard.py`) reject any sentence that does. What it does say is a confident prediction about
love, work, recognition, prosperity, creativity, journeys and change, in soft time.

## Review log

| File | Entries | Checked against | Checked by | Date | Changes made |
| --- | --- | --- | --- | --- | --- |
| `lines.json` | 45 | S1, S4 | not yet | | |
| `shape.json` | 5 | S2, S3, S4 | not yet | | |
| `themes.json` | 5 | S1, S3, S4 | not yet | | |
| `compare.json` | 4 | S1, S2 | not yet | | |
| `limits.json` | 9 | S1, S4 | not yet | | |
