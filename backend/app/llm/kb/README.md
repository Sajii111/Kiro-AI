# The palmistry knowledge base

The language model does not answer from memory. It is handed entries from this folder, and told to stay close to them
(`docs/LLM_DESIGN.md` explains why, in section 2). The fixed-rule writer, which takes over whenever Gemini is not used, writes
from the same entries. So whatever a reading says about palmistry, it says because an entry here says it.

## Status: a draft that the author must check

The 68 entries were **drafted for the project in its own words** from the four sources below, with the claims about health,
length of life, fortune and events left out on purpose. They have been checked by tests (every entry is cautious, names a
source, and passes the same safety rules the model's output must pass; every length, curve and clarity of every line has an
entry). **No person has yet checked them against the sources.** Until the author has, call it a *curated draft*, not a
reviewed knowledge base, in the report and in the viva. The review log at the bottom is where that gets recorded.

## What is in it

| File | Entries | What it holds |
| --- | --- | --- |
| `lines.json` | 45 | The five principal lines (heart, head, life, fate, sun): one entry on what each is linked with, then one for each length, curve and clarity the analysis can report |
| `shape.json` | 5 | The four hand shapes named for the elements (earth, air, water, fire), and a general note |
| `themes.json` | 5 | The five themes of the report (personality, career, financial, relationships, future): which lines and shapes each is read from, an introduction, and a closing reminder. The wording of the closing reminders is the app's, not Gemini's |
| `compare.json` | 4 | How the tradition reads two hands together: the general idea, hands that match, hands that differ, and a line shown on one hand only |
| `limits.json` | 9 | What palmistry does not claim (science, medicine, lifespan, money, careers, relationships, prediction) and what this reading never does (a missing line, a poor photo) |
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
  "short": "a long line is often read as openness and warmth in how feelings are shared",
  "text": "In traditional palmistry a long heart line is often read as openness and warmth in how feelings are shared. It describes a style of feeling, not how many relationships a person has.",
  "keywords": ["heart line", "heart", "emotions", "long", "length"],
  "basis": ["S1"]
}
```

- `text` is the full statement given to Gemini. It is always put as the tradition's reading ("In traditional palmistry ...",
  "is often read as ...") and often ends by saying what it does *not* mean.
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
| **S1** | Cheiro (Count Louis Hamon), *Palmistry for All*, 1916, public domain. [Project Gutenberg ebook 20480](https://www.gutenberg.org/ebooks/20480) | What each principal line is traditionally linked with, and comparing the two hands (one inherited, the other developed). The book also makes claims about health, length of life and fortune: **this knowledge base leaves those out on purpose** |
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
   - **Is it cautious?** It must say "in traditional palmistry", "is often read as", never "you are" or "you will".
   - **Does it stay out of health, lifespan, money decisions, jobs, predictions and other people?** If it drifts in, rewrite it.
2. Where several sources disagree (the hand-shape scheme is the clearest case), the entry should say "differs between sources"
   or follow the scheme named in S3, as the shape entries do. Do not hide a disagreement.
3. Edit the entry in place. Keep the `id`, and keep the two fields that a test depends on (`text` and `basis`) filled.
4. Raise `KB_VERSION` in `__init__.py` (for example `palm-kb 1.1`). It is written into every reading's `meta.knowledgeBase`,
   so a reading says which version of the notes it was written from.
5. Run the tests from the `backend` folder: `python -m pytest tests/test_kb.py tests/test_retrieval.py tests/test_guard.py`. A test
   fails if an edited entry breaks a safety rule, loses its source, or no longer covers a finding.
6. Write the result in the review log below.

To add an entry, follow the pattern of its neighbours, give it a new `id`, and name its `basis`. `tests/test_kb.py` has a test
that counts the entries (it currently expects 68), so update that number too.

## What the entries leave out on purpose

Health and illness, how long anyone will live, money and investments, which job to take, marriage and children, accidents and
other events, ages and dates, "lucky" and "unlucky". Older palmistry books say a great deal about all of these. This app does
not, and its safety checks (`../guard.py`) reject any sentence that does.

## Review log

| File | Entries | Checked against | Checked by | Date | Changes made |
| --- | --- | --- | --- | --- | --- |
| `lines.json` | 45 | S1, S4 | not yet | | |
| `shape.json` | 5 | S2, S3, S4 | not yet | | |
| `themes.json` | 5 | S1, S3, S4 | not yet | | |
| `compare.json` | 4 | S1, S2 | not yet | | |
| `limits.json` | 9 | S1, S4 | not yet | | |
