# Kiro AI: how the language model is used

This note explains the "specialised LLM" and the chatbot: which model, how a general model is made into a palmistry
writer, what it is told, what it may write, what stops it from writing something it should not, and what leaves the
computer. Every claim here is backed by code in `backend/app/llm/` and by tests in `backend/tests/`; the file names are given
so a marker can check.

**In one paragraph.** Kiro AI first measures the two palm photos with image processing (OpenCV and NumPy, plus MediaPipe to
find the hand). That produces *findings*: which of five lines were found on each hand, how long, how curved, how clear, and
the hand's shape. Google's **Gemini** model then puts what traditional palmistry says about those findings into words, and
answers questions about the reading in a chat. Gemini never sees a photo. It is given the findings as a few fixed words, the
entries of a curated **knowledge base** that fit them, and a list of rules. Whatever it writes is checked by plain code before
anyone reads it, and if anything goes wrong the app falls back to fixed wording written from the same knowledge base. A reading
and a chat answer always finish.

## 1. The choices

| Question | Choice | Why |
| --- | --- | --- |
| Which model? | Gemini, through Google's `google-genai` library. The default is `gemini-3.5-flash-lite`, set by `GEMINI_MODEL` | Flash-Lite is quick and has a free allowance, so no card is needed. The name is a setting, because Google renames models; `run.bat gemini --probe` lists the ones a key can use |
| How is a general model made specific to palmistry? | **Retrieval-augmented generation (RAG)**: a curated knowledge base, retrieved per question, plus a versioned system prompt and a fixed output shape | See section 2 |
| Why not fine-tuning? | There is no palmistry data set worth training on, no budget for it, and a fine-tuned model would still need the same checks. RAG keeps every sentence the model leans on in a file a person can read and correct | A wrong claim is fixed by editing one entry, not by retraining |
| What goes in? | The **findings** (words from short fixed lists), the matching knowledge-base entries, and for the chat the report text, the question and the last few messages | Section 6 lists exactly what is sent |
| What comes out? | **JSON** in a schema the model must follow: a key for every passage asked for (report), or `intent`, `answer`, `lines`, `side`, `section` (chat) | A shape that can be checked passage by passage |
| What if it misbehaves, or is unavailable? | Each passage is checked; a failed one is asked for once more and then replaced by the fixed wording; no key, no allowance or no network means the fixed wording throughout | Section 5. The user always gets a reading |

## 2. How the model is specialised

### 2.1 The knowledge base (`app/llm/kb/`)

68 short entries in JSON, each one a cautious statement in the project's own words ("In traditional palmistry a long heart
line is often read as ..."):

| File | Entries | Holds |
| --- | --- | --- |
| `lines.json` | 45 | for each of the five lines: what it is linked with, then one entry per length, curve and clarity |
| `shape.json` | 5 | the four hand shapes (earth, air, water, fire) and a general entry |
| `themes.json` | 5 | the five themes of the report (personality, career, financial, relationships, future): what each is read from |
| `compare.json` | 4 | how the tradition reads two hands together: the general idea, hands that match, hands that differ, and a line that shows on one hand only |
| `limits.json` | 9 | what palmistry does not claim, and what this reading never does |
| `sources.json` | 4 sources | the books and pages the entries were written from (S1 to S4), named in each entry's `basis` |

The entries leave out, on purpose, what older books say about health, length of life, fortune and events. They are a
**draft to be checked by the author against the named sources** (`app/llm/kb/README.md` says how). Tests make sure each entry
is cautious, names a source (the one entry about the app's own photos excepted), and itself passes the same safety rules that the model's output must pass (`tests/test_kb.py`).

### 2.2 Retrieval (`app/llm/retrieval.py`)

Two strategies, one for each job:

- **Report: a lookup.** The findings say exactly which entries apply (heart line, long, gently curved, clear ...), so they are
  picked by key. No guessing; the same findings always give the same entries.
- **Chat: a keyword search (BM25)**, because a question is free text. BM25 is written out in about thirty lines (k1 = 1.5,
  b = 0.75) so no extra package is needed and it can be explained line by line. The search is then **filtered by the
  reading**: an entry about a line that was not clearly seen, or about a length or curve these hands do not show, is never offered.
  The model cannot be handed something that is not in the findings.

### 2.3 The prompts (`app/llm/prompts.py`)

A system prompt for the report writer and one for the chat, both versioned (`report-prompt 1.0`, `chat-prompt 1.0`) and written
into every reading's `meta.prompt`. They state seven rules: use only the findings and knowledge; write about a line only if it
was detected; put everything as "the tradition's reading", never as fact about the person; never predict, never advise, nothing
about health, money, jobs or other people; say plainly when the two hands differ; plain text only; calm, plain English. The
user's request goes in the prompt, never the system prompt, and the findings are labelled "these are the only facts you have".

### 2.4 The output shape

The model is asked for `application/json` with a JSON schema (`response_json_schema`): for the report a key for each passage
asked for, for the chat the five fields above, where `intent` is one of `answer`, `medical`, `lifespan`, `financial_advice`,
`employment_advice`, `relationship_advice`, `prediction`, `advice`, `off_topic`. Asking for a shape lets the app check each
passage on its own.

## 3. The report: who writes what

Every reading is first written completely by fixed rules (`app/llm/report.py`). Gemini is then asked to put the **interpretive**
passages into its own words, and only the ones that pass are swapped in (`app/llm/writer.py`):

```
 findings ──► plan ──► ask Gemini ──► check each passage ──► retry the failures once ──► compose
              which     one request:     guard.py              only those passages,       accepted passage
              passages  findings,        (section 4)           with what was wrong         replaces the
              are worth knowledge                                                          fixed wording;
              asking    entries,                                                           one that failed twice
                        JSON shape                                                         keeps the fixed wording
```

**The server writes every fact; Gemini writes only the interpretation.**

| Written by the server (measured or fixed; the model cannot get these wrong) | Written by Gemini (what the tradition says) |
| --- | --- |
| What was observed on each hand ("Left hand: heart line detected, medium length ...") | The summary overview |
| Which lines were found, which were unclear or missing | What each detected line is linked with, per hand |
| How the two hands compare (the sentence that says they match or differ) | The tradition's reading of a match or a difference |
| The uncertainty list, the disclaimer, the "Left out ..." sentence, the theme closing reminders | The hand-shape passages, and the five theme passages |

A reading's `meta` says honestly which words came from where: `provider: "gemini"` and the model name when at least one passage
was accepted, otherwise `provider: "knowledge-base"` with `meta.note` giving the reason in one sentence ("Gemini was not used
for this reading because its free allowance is used up for now, so the words come from the knowledge base"). The website shows
the writer ("Gemini · model name", or "knowledge base") and the note under "How this reading was made". `run.bat live` goes further
and labels every passage as written by the app, by Gemini, or by the fixed wording after a refusal. A built-in sample reading
never calls Gemini.

## 4. The checks (`app/llm/guard.py`, `guard 1.0`)

A request in a prompt is not a guarantee, so every passage is judged by plain rules that do not depend on the model. The
same test is used everywhere: a sentence that is only allowed "to say there is none" must contain a word of denial. It is
deliberately simple, because a rule that is easy to explain is easy to trust.

| Check | Catches |
| --- | --- |
| plain | empty, too long, a link or e-mail address, a number (invented ages, dates and percentages come from numbers), a list where sentences were asked for |
| framing | a claim that is not put as the tradition's reading ("in traditional palmistry ...", "is often read as ...") |
| prediction | what will happen, timing, ages, destiny |
| advice | "you should ...", "I recommend ..." |
| sensitive | health, illness, lifespan, investing, big life events |
| invented | marks and signs that are not among the findings (marriage lines, islands, mounts, other creases) |
| claims to see | "I can see ...": the model never sees the photos |
| not seen | a line that was not clearly seen may only be mentioned to say so |
| other hand | a passage about one hand does not talk about the other |
| dominant | nothing may assume which hand is dominant: the reading does not know |
| consistency | a passage must not say "short" when the findings say long, "deep" when they say faint, and so on; in a chat answer the same test is applied to every sentence about one line on one hand |

The guard is **heuristic**. It is a set of word and pattern rules, not a proof. It can miss something unusual and it can raise a
false alarm; a false alarm costs only a fallback to the fixed wording, never a wrong reading. `tests/test_guard.py` (48 tests)
runs it against passages that are good, and against passages that each break one rule.

## 5. The chat (`app/llm/chat_llm.py`)

Every message goes through these steps, in order:

1. **Boundaries, no model.** Plain rules decline another person's name, health, lifespan, money, jobs, relationships, "will I ..."
   and "should I ..." in fixed wording. These never reach Gemini.
2. **Eligibility.** Gemini is asked only for a real reading, when a key is set, when this chat has answers left
   (`GEMINI_CHAT_LIMIT`, default 40 per session), and when the message is not just "hello" or "thanks".
3. **Context, built by the server.** The findings (words only), the report as the person reads it, the knowledge-base entries
   that fit the question (BM25, filtered to what this reading shows), and the last six messages (500 characters each). The
   question and the earlier messages are scrubbed first (section 6).
4. **One JSON answer.** No second try: a chat should feel quick. A chat call waits half as long as a report call (never under ten seconds).
5. **Intent.** Anything other than `answer` means the model recognised a boundary the plain rules missed. Its words are
   dropped and the app's own fixed wording for that boundary is shown.
6. **Checks.** `guard.py` judges the answer, with the chat's extra test (a sentence about one line on one hand must agree
   with the findings for it).
7. **Fallback.** Whatever goes wrong, the rule-based answer is used and a small note says why. A question always gets an answer.

Each assistant message carries `source` (`"gemini"` or `"knowledge-base"`) and, when Gemini was expected but did not answer,
a `note`. The website labels them.

## 6. What leaves the computer

Photos are **never** sent to Gemini. The report request carries:

- the findings: a line's status (detected, uncertain, not visible), and for a detected line its length, curve and clarity;
  the hand shape (palm, fingers, element). Every value comes from a short fixed list, so the findings **cannot** hold a photo,
  a name, a file name, coordinates, a score or anything a person typed (`findings_payload` in `prompts.py`);
- the knowledge-base entries that fit, and the rules.

A chat request adds the person's own question and the last few messages. A person can type anything, so before they are sent,
`app/llm/privacy.py` replaces e-mail addresses, links, runs of seven or more digits and the names of the profiles on the account
with a bracketed word. This is not a promise that nothing personal can ever be typed, which is why the website says, next to the
chat box, that questions are sent to Gemini. `tests/test_privacy.py` runs the whole API and checks that no profile name, contact
detail, file name or photo bytes reach the model.

**Free tier.** On Google's free Gemini tier, what is sent may be used to improve Google's products, and reviewers may read it.
That is the price of the free key, so it is said on screen (the report's "How this reading was made", the chat box, Settings,
the landing page FAQ) and in the README. Turning on billing changes that, and is not needed for this project.

MediaPipe, which finds the hand, is a separate matter. It runs on the computer, but the library contacts Google the first time
it runs, to report usage. See the main README, "Privacy".

## 7. Limits, cost and resilience (`app/llm/gemini.py`)

`ModelService` stands between the app and Gemini so a free key is not used up and a reading never waits for ever:

- a per-minute budget (`GEMINI_MAX_PER_MINUTE`, default 12) and at most three calls at once;
- after a rate limit, "high demand", timeout or server error, **every** call pauses, for longer each time it repeats (15 s,
  30 s, 60 s ... up to 300 s), and a "retry in N seconds" from Google is respected. A bad key, an unknown model name or an unsupported region rest
  for the full 300 s, because trying again will not help until the file is fixed;
- an identical report request is answered from memory (`GEMINI_CACHE_SIZE`, default 32), so the same findings are not paid for
  twice; an answer that could not be used is never remembered;
- each request has a time limit (`GEMINI_TIMEOUT_SECONDS`, default 60 for a report) and makes one attempt: the library's own
  retries are switched off, so the app's back-off is the only one;
- one exception, decided by the app and not by the library: when Google answers "This model is currently experiencing high
  demand" (HTTP 503, kind `overloaded`) or the call fails in a way that tends to pass (kind `error`), **the report's request is
  repeated once after four seconds**, because such a spell is usually over quickly. The repeat counts towards the per-minute
  budget. If it works, nothing is remembered as a failure; if it fails too, the service rests once, as above. A rate limit and a
  timeout are never repeated (Google says how long to wait, and a second timeout doubles the wait), and neither is a chat answer
  (the person is waiting, and a chat that falls back is still answered at once). The first live run on a real key showed why:
  Google's free `gemini-3.5-flash-lite` once answered "high demand" and the whole report fell back to the fixed wording;
- the key is read once from `backend/.env`, never logged, never put in an error message, and removed from any text that
  might hold it (the key itself and anything shaped like `AIza...`);
- every way a call can fail becomes one error, `ModelUnavailable`, with a kind (`rate_limited`, `overloaded`, `timeout`,
  `error`, `bad_key`, `bad_model`, `region`, `bad_request`, `blocked`, `cut_off`, `empty`, `bad_output`, `busy`, `chat_limit`,
  `no_key`) and a plain sentence for the person.

## 8. How it is tested without the network

No test can reach Google. A fixture in `tests/conftest.py` blanks the key for every test and replaces `google.genai.Client`
with a function that fails the test if anything calls it, so a real key in `backend/.env` can never leak into a test run. The
model is replaced by `tests/fake_gemini.py`, a fake that can be made to answer well, to break each rule, to return nonsense,
or to fail in every way Google can. The suite has 1056 tests, of which these concern the language model:

| File | Tests | What it proves |
| --- | --- | --- |
| `test_kb.py` | 76 | every entry is complete, cautious, sourced and passes the guard; the knowledge base covers every finding the analysis can produce |
| `test_retrieval.py` | 11 | the lookup and the BM25 search pick the right entries, and never an entry the findings do not support |
| `test_guard.py` | 48 | each safety check, with good and bad passages |
| `test_gemini_service.py` | 51 | budget, back-off, the one repeat when Google is busy, cache, failure classification, and the real `GeminiModel` against a fake client (the request it builds, its timeout, thinking setting and error handling) |
| `test_report_writer.py` | 44 | what the model is shown and asked, which passages are used, retry, fallback, how firm the hand shape is, and that the report is never worse than the fixed wording |
| `test_chat_llm.py` | 53 | the chat's seven steps: boundaries, eligibility, context, intent, checks, fallback, limits |
| `test_gemini_api.py` | 13 | the whole API with a fake Gemini: a reading and a chat, with and without a key, with failures |
| `test_privacy.py` | 12 | no name, contact detail, file name or photo reaches the model |
| `test_config.py` | 8 | `backend/.env` is read however Windows saved it (with a byte-order mark, as UTF-16, with Windows line endings) |
| `test_check_gemini_script.py`, `test_live_report_script.py` | 34, 14 | the two scripts below, with a fake model |

## 9. Checking it for real

The fake proves the code; only Google can prove the key, the model name and the wording it produces. Two scripts do that on
the author's own computer and print what they find (they never print the key):

- `run.bat gemini` (`scripts/check_gemini.py`): shows the settings, asks for one tiny answer, then writes a report from a
  made-up pair of hands and answers five questions and three boundary questions, saying plainly which passed. `--probe` sends one
  tiny request to up to eight Flash and Flash-Lite models (the chosen one first) and says which of them answer for this key. A
  text copy of everything it prints is saved as `E:\Project\debug\check_gemini.txt` (made-up hands only, never the key), so a
  long screen need not be copied by hand.
- `run.bat live test-photos\person1` (`scripts/live_report.py`): the same for the author's own photos. It prints what was
  found, exactly what Gemini is told, the full report with a label on each passage saying who wrote it, and saves a text copy
  in `E:\Project\debug\` (it holds the person's findings, so it is never committed).

`run.bat smoke --expect-gemini` then checks, from the outside, that the running server really writes with Gemini.

**Status.** First runs on a real key, on the author's computer, on 19 November 2026 (`gemini-3.5-flash-lite`, free tier, no
billing):

- `run.bat gemini` passed: 7 requests, all 20 report passages for the made-up hands passed the safety checks, and Gemini wrote 4
  of the 5 chat answers (the fifth fell back to the knowledge base; the reason is in `check_gemini.txt` from the next run on);
- `run.bat smoke --expect-gemini` passed 17 of 17, with the report and a chat answer written by Gemini;
- one `run.bat live` for the author's own photos got Google's "high demand" error (503) on its single request, so that report was
  written entirely from the knowledge base and said so. That is what led to the one repeat described in section 7.

Still to do: read the Gemini-written passages for the author's own photos as an examiner would, and mark any sentence that
predicts, advises, sounds medical or shows a mark the hands do not have.

## 10. Honest limits

- **Palmistry is a tradition, not a science.** The reading is for reflection and entertainment. The app says so on every
  screen that shows words, and it makes no claim about accuracy.
- **The knowledge base is a draft.** It must be read and checked against its named sources before it is presented as reviewed.
- **The guard is heuristic**, as section 4 says.
- **Gemini's output varies.** The same findings can be worded differently on another day or another model. The temperature is low
  (0.2 for the report, 0.3 for the chat), the checks hold the content to the knowledge base, and the app labels what Gemini wrote,
  but the wording is not fixed.
- **Free tier.** Limits are per key, change over time, and are shown only in Google AI Studio. Content sent may be used by Google.
- **The model name is a setting** because Google renames and retires models. A `bad_model` failure says so on screen.
- **The findings are only as good as the photo analysis.** A line the analysis misses is simply not described.

## 11. Where things are

| What | Where |
| --- | --- |
| The Gemini client and the care around it | `backend/app/llm/gemini.py` |
| The rules and prompts, the findings payload, the output schemas | `backend/app/llm/prompts.py` |
| The knowledge base and its loader | `backend/app/llm/kb/` (README there), `kb/__init__.py` |
| Retrieval | `backend/app/llm/retrieval.py` |
| The safety checks | `backend/app/llm/guard.py` |
| The report writer | `backend/app/llm/writer.py`, with the fixed wording in `report.py` and `knowledge.py` |
| The chat | `backend/app/llm/chat_llm.py`, with the fixed rules in `chat.py` |
| What is removed from a question | `backend/app/llm/privacy.py` |
| Settings (`GEMINI_*`) | `backend/app/core/config.py`, `backend/.env.example` |

**To change something.** A different model: set `GEMINI_MODEL` in `backend/.env`. A wrong or missing claim: edit the entry in
`kb/*.json`, raise `KB_VERSION`, and run the tests (they fail if the entry breaks a rule). A new rule: add it to `guard.py`,
raise `GUARD_VERSION`, and add a test that breaks it. A change to a prompt: raise its version (`REPORT_PROMPT_VERSION`,
`CHAT_PROMPT_VERSION`), because the version is written into every reading.
