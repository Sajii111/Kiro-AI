# Kiro AI: how the language model is used

This note explains the "specialised LLM" and the chatbot: which model, how a general model is made into a palmistry
writer, what it is told, what it may write, what stops it from writing something it should not, and what leaves the
computer. Every claim here is backed by code in `backend/app/llm/` and by tests in `backend/tests/`; the file names are given
so a marker can check.

**In one paragraph.** Kiro AI first measures the two palm photos with image processing (OpenCV and NumPy, plus MediaPipe to
find the hand). That produces *findings*: which of five lines were found on each hand, how long, how curved, how clear, and
the hand's shape. Google's **Gemini** then reads the palm like a fortune teller: it turns those findings into confident
predictions about love, work, prosperity, creativity, journeys and change, and answers questions about the reading in a chat.
Gemini never sees a photo. It is given the findings as a few fixed words, the entries of a curated **knowledge base** that fit
them, and a list of rules. Whatever it writes is checked by plain code before anyone reads it. Several Gemini models on the one
key take turns, so a model that is busy does not stop a reading, and if every one of them fails the app falls back to fixed
wording written from the same knowledge base. A reading and a chat answer always finish.

## 1. The choices

| Question | Choice | Why |
| --- | --- | --- |
| Which model? | Gemini, through Google's `google-genai` library, with one key. Several models take turns: `GEMINI_MODEL` (default `gemini-3.5-flash-lite`) first, then `GEMINI_FALLBACK_MODELS` (default `gemini-3.1-flash-lite`, `gemma-4-31b-it`, `gemma-4-26b-a4b-it`), and the app also asks Google which models the key may use, leaves out the ones it cannot, and adds up to three more Flash models | Flash-Lite models are quick and have a free allowance, so no card is needed. Google's "high demand" answer and its free allowances belong to each model separately, so when one is busy or used up another usually answers. A less capable model is fine: the knowledge base and the checks do the steering. The names are settings, because Google renames and retires models (one key was told that `gemini-2.5-flash-lite` does not exist); `run.bat gemini --probe` says which ones a key can use |
| Why no other AI provider? | Everything goes through the Gemini API, with the author's one key | The fall-backs are other models of the same API (the Gemma 4 models are served by it too), so there is one key, one privacy story (section 6) and one library. An earlier plan to add other providers was dropped |
| How is a general model made specific to palmistry? | **Retrieval-augmented generation (RAG)**: a curated knowledge base, retrieved per question, plus a versioned system prompt and a fixed output shape | See section 2 |
| Why not fine-tuning? | There is no palmistry data set worth training on, no budget for it, and a fine-tuned model would still need the same checks. RAG keeps every sentence the model leans on in a file a person can read and correct | A wrong claim is fixed by editing one entry, not by retraining |
| What goes in? | The **findings** (words from short fixed lists), the matching knowledge-base entries, and for the chat the report text, the question and the last few messages | Section 6 lists exactly what is sent |
| What comes out? | **JSON** in a schema the model must follow: a key for every passage asked for (report), or `intent`, `answer`, `lines`, `side`, `section` (chat) | A shape that can be checked passage by passage |
| What if it misbehaves, or is unavailable? | Each passage is checked; a failed one is asked for once more and then replaced by the fixed wording. A busy or used-up model hands over to the next Gemini model; only when all of them fail, or there is no key or no network, is the fixed wording used throughout | Sections 4, 5 and 7. The user always gets a reading |

## 2. How the model is specialised

### 2.1 The knowledge base (`app/llm/kb/`)

68 short entries in JSON, each one a statement in the project's own words, in a palm reader's voice and in plain everyday
words ("A long heart line means an open, generous heart. Love comes to you easily, and you give plenty back."):

| File | Entries | Holds |
| --- | --- | --- |
| `lines.json` | 45 | for each of the five lines: what it is linked with, then one entry per length, curve and clarity |
| `shape.json` | 5 | the four hand shapes (earth, air, water, fire) and a general entry |
| `themes.json` | 5 | the five themes of the report (your nature, career and calling, fortune and prosperity, love and relationships, what lies ahead): what each is read from |
| `compare.json` | 4 | how two hands are read together: the general idea, hands that match, hands that differ, and a line that shows on one hand only |
| `limits.json` | 9 | what the reading never claims or foretells, and what it never does |
| `sources.json` | 4 sources | the books and pages the entries were written from (S1 to S4), named in each entry's `basis` |

The entries leave out, on purpose, what older books say about health, length of life, accidents, children, loss and dated
events; what they keep is what each line promises about love, work and recognition, prosperity, creativity, journeys and change.
They are a **draft to be checked by the author against the named sources** (`app/llm/kb/README.md` says how). Tests make sure
each entry is in the reader's voice, names a source (the one entry about the app's own photos excepted), and itself passes the
same safety rules that the model's output must pass (`tests/test_kb.py`).

### 2.2 Retrieval (`app/llm/retrieval.py`)

Two strategies, one for each job:

- **Report: a lookup.** The findings say exactly which entries apply (heart line, long, gently curved, clear ...), so they are
  picked by key. No guessing; the same findings always give the same entries.
- **Chat: a keyword search (BM25)**, because a question is free text. BM25 is written out in about thirty lines (k1 = 1.5,
  b = 0.75) so no extra package is needed and it can be explained line by line. The search is then **filtered by the
  reading**: an entry about a line that was not clearly seen, or about a length or curve these hands do not show, is never offered.
  The model cannot be handed something that is not in the findings.

### 2.3 The prompts (`app/llm/prompts.py`)

A system prompt for the report writer and one for the chat, both versioned (`report-prompt 3.0`, `chat-prompt 3.0`) and written
into every reading's `meta.prompt`. Both open with the same voice: a confident palm reader who talks straight, speaks to "you"
and foretells with conviction, and who never says that this is a joke. A second block, "your words", asks for plain everyday
words and short sentences, the way one talks to a friend, and names what to avoid (spiritual or technical words such as
"tapestry", "resonate", "energies", "temperament", "trajectory"). A passage about a line first says in a few plain words what
the line stands for, then makes one clear prediction. Then come the rules: use only the
findings and knowledge; write about a line only if it was detected; foretell in soft time only ("soon", "in time", "before
long"), never an age, a date or a count of months; foretell only love, work and recognition, prosperity in general, creativity,
journeys, change and growth; never health, children, how long anyone will live, sums of money, investments or any misfortune;
no orders and no advice; say plainly when the two hands differ; plain text only. The user's request goes in the prompt, never
the system prompt, and the findings are labelled "these are the only facts you have". The one honest line that palmistry is an
old art and not a science is added by the app (`copy.py`), so the model need not hedge every sentence.

### 2.4 The output shape

The model is asked for `application/json` with a JSON schema (`response_json_schema`): for the report a key for each passage
asked for, for the chat the five fields above, where `intent` is one of `answer`, `medical`, `lifespan`, `financial_advice`,
`employment_advice`, `relationship_advice`, `advice`, `off_topic`. Asking for a shape lets the app check each passage on its
own.

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
| Which lines were found, which were unclear or missing | What each detected line foretells, per hand |
| How the two hands compare (the sentence that says they match or differ) | What a match or a difference foretells |
| The uncertainty list, the disclaimer, the "Left out ..." sentence, the theme closing lines | The hand-shape passages, and the five theme passages |

A reading's `meta` says honestly which words came from where: `provider: "gemini"` and the name of the Gemini model that actually
wrote them (it may be a fall-back model, section 7) when at least one passage was accepted, otherwise `provider: "knowledge-base"` with `meta.note` giving the reason in one sentence ("Gemini was not used
for this reading because its free allowance is used up for now, so the app’s own wording was used"). The website shows
the writer ("Gemini · model name", or "The app’s own fixed wording (no AI)") and the note under "How this reading was made". `run.bat live` goes further
and labels every passage as written by the app, by Gemini, or by the fixed wording after a refusal. A built-in sample reading
never calls Gemini.

## 4. The checks (`app/llm/guard.py`, `guard 2.1`)

A request in a prompt is not a guarantee, so every passage is judged by plain rules that do not depend on the model. The
reading speaks like a fortune teller, with conviction, so the rules guard not the voice but what the voice may be used for: a
prediction may be as sure as it likes, but it names no time, touches no sensitive subject, gives no orders and claims no proof.
The same test is used everywhere: a sentence that is only allowed "to say there is none" must contain a word of denial. It is
deliberately simple, because a rule that is easy to explain is easy to trust.

| Check | Catches |
| --- | --- |
| plain | empty, too long, a link or e-mail address, a number (invented ages, dates and percentages come from numbers), a list where sentences were asked for |
| anchor | words that are not about the palm: a passage must name a line, the hand, the palm or the fingers |
| timing | an age, a year, a month, a date, "next year", "within six months", "in your thirties". Soft time ("soon", "in time", "before long", "one day") is the reader's own and is allowed |
| advice | orders and recommendations ("you should ...", "you must ...", "I recommend ...", "be sure to ..."): a reader foretells and does not decide for anyone |
| sensitive | health, illness, injury, pregnancy and children, how long anyone will live; money in sums and instruments (investing, crypto, lotteries, salaries, debts, loans, tax); every misfortune (betrayal, divorce, accident, bankruptcy, curses, heartbreak, doom, failure, poverty ...). Such a word is allowed only in a sentence that says the reading does not speak of it |
| overclaim | "guaranteed", "proven", "scientific", "infallible": the reading is an old art and says so, and makes no claim of proof |
| invented | marks and signs that are not among the findings (marriage lines, islands, mounts, forks, other creases) |
| claims to see | "I have analysed your photo ...": the model never sees the photos. (The reader's own "I see a generous heart" is a figure of speech and is fine) |
| not seen | a line that was not clearly seen may only be mentioned to say so |
| other hand | a passage about one hand does not talk about the other |
| dominant | nothing may assume which hand is dominant: the reading does not know |
| plain words | a short list of fancy, spiritual or technical words that a normal person does not use ("tapestry", "resonate", "energies", "temperament", "trajectory", "grounded" ...). A report passage that has one is asked for again once, with the word named, and then the plain fixed wording is used. The chat is exempt, because it has no second try and the instructions already ask for plain words |
| consistency | a passage must not say "short" when the findings say long, "deep" when they say faint, and so on; in a chat answer the same test is applied to every sentence about one line on one hand |

The guard is **heuristic**. It is a set of word and pattern rules, not a proof. It can miss something unusual and it can raise a
false alarm; a false alarm costs only a fallback to the fixed wording, never a wrong reading. `tests/test_guard.py` (94 tests)
runs it against passages that are good (confident predictions about love, work, prosperity, creativity, journeys and change),
and against passages that each break one rule.

## 5. The chat (`app/llm/chat_llm.py`)

Every message goes through these steps, in order:

1. **Boundaries, no model.** Plain rules decline, in the reader's own voice and fixed wording, another person's name, health,
   pregnancy and children, how long anyone will live, investing, job events ("will I be fired") and other people's hearts
   ("will he leave me"), and any "should I ..." (a reader foretells and does not decide). These never reach Gemini. "Will I ...?"
   about love, work and recognition, prosperity in general, creativity, journeys or the road ahead is **not** a boundary: it is
   what the reader is for, and it goes to Gemini.
2. **Eligibility.** Gemini is asked only for a real reading, when a key is set, when this chat has answers left
   (`GEMINI_CHAT_LIMIT`, default 40 per session), and when the message is not just "hello" or "thanks".
3. **Context, built by the server.** The findings (words only), the report as the person reads it, the knowledge-base entries
   that fit the question (BM25, filtered to what this reading shows), and the last six messages (500 characters each). The
   question and the earlier messages are scrubbed first (section 6).
4. **One JSON answer.** Every Gemini model gets its turn (section 7), and a busy spell is repeated once after a short wait, but a
   chat should feel quick, so a chat call waits half as long as a report call (never under ten seconds).
5. **Intent.** Anything other than `answer` means the model recognised a boundary the plain rules missed (medical, lifespan,
   financial, job or relationship advice, advice, off topic). Its words are dropped and the app's own fixed wording for that
   boundary is shown.
6. **Checks.** `guard.py` judges the answer, with the chat's extra test (a sentence about one line on one hand must agree
   with the findings for it).
7. **Fallback.** Whatever goes wrong, the rule-based answer is used and a small note says why. A question always gets an answer.

Each assistant message carries `source` (`"gemini"` or `"knowledge-base"`) and, when Gemini was expected but did not answer,
a `note`. The website labels them. When the fixed wording answers a "Will I ...?" question it speaks from the themes of the
report, so that it too is a prediction in the reader's voice.

## 5a. Sinhala and Tamil (`app/llm/translate.py`, `translate 1.1`)

The website can be shown in English, Sinhala or Tamil, and a new reading or chat answer is shown in the chosen language. Every
check in section 4 works on English words, so the order never changes: **write and check in English, then translate.**

1. The report (or the chat answer) is written exactly as above, in English, and every passage Gemini wrote has passed the guard.
2. One more request asks Gemini to translate the finished texts into Sinhala or Tamil: faithfully, adding nothing, in plain
   everyday words for people in Sri Lanka, keeping "Kiro" and "Gemini" as they are, never adding a number, a date or a link, and
   using a small glossary so the terms match the website (හෘදය රේඛාව / இதய ரேகை for the heart line, හස්ත රේඛා කියවීම / கைரேகை பலன் for a reading, and so on). It is also told to write natural Sinhala or Tamil rather than word for word. The texts go
   as one JSON object (identical texts once, in parts of about 3,500 characters) and come back with the same keys.
3. Each translation is checked: it must be mostly in the right script (Sinhala U+0D80–U+0DFF, Tamil U+0B80–U+0BFF), add no digit
   or link that the English did not have, and be neither far longer nor far shorter than the English. A text that fails is asked
   for once more; after that the English stays for that text, and `meta.note` (or the chat message's `note`) says so.

For a reading this covers all of the report's texts, also the ones the server wrote (what the photos show, the disclaimer), so
the page reads in one language. `meta.language` records it. A busy Gemini, no key, or repeated failures leave the English
reading as it was, with a note; a sample reading is never sent. For a chat answer (Gemini's or the fixed wording) the profiles'
names are swapped for placeholders (NAME1, ...) before the request and put back afterwards, so a name in a fixed answer never
leaves the server. The person's question may be in Sinhala or Tamil; Gemini still answers in English first, and the plain-code
boundaries in `chat.py` (English word patterns) may miss such a question, but the model's `intent` field still sends health,
lifespan and advice questions to the fixed wording.

**Limits.** The translation is Gemini's and is not reviewed by a native speaker; the checks only make sure it is in the right
script and adds no numbers or links. A translation can still soften or shift a sentence's meaning. The website's own words
(menus, buttons, notes) are a fixed Sinhala and Tamil dictionary in `src/i18n/` and need a native speaker's review too.

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
detail, file name or photo bytes reach the model. The name a person may give a reading is added to the reading only after the
report is written and is not used by any prompt, so it never reaches the model either; a test names a reading and checks the
report and chat requests for it. A translation request (section 5a) carries only texts that already passed these rules, with
the profiles' names swapped out (`tests/test_translate.py` checks both).

**Free tier.** On Google's free Gemini tier, what is sent may be used to improve Google's products, and reviewers may read it.
That is the price of the free key, so it is said on screen (the report's "How this reading was made", the chat box, Settings,
the landing page FAQ) and in the README. Turning on billing changes that, and is not needed for this project.

MediaPipe, which finds the hand, is a separate matter. It runs on the computer, but the library contacts Google the first time
it runs, to report usage. See the main README, "Privacy".

## 7. Limits, cost and resilience (`app/llm/gemini.py`)

Two layers stand between the app and Gemini so a free key is not used up, a reading never waits for ever, and one busy model
does not stop a reading. `ModelService` looks after the key's allowance; underneath it, `Failover` lets several Gemini models on
the one key take turns.

**Several Gemini models, one key (`Failover`).**

- `GEMINI_MODEL` names the model that is tried first (it may name several, separated by commas), and `GEMINI_FALLBACK_MODELS`
  (default `gemini-3.1-flash-lite,gemma-4-31b-it,gemma-4-26b-a4b-it`; the word `none` turns it off) names the ones that take
  over, in order. The first that can answer does. Nothing but the Gemini API and the one key is involved: the Gemma 4 models are
  hosted on it (https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api), with limits of their own. Whether they take a JSON
  schema is not documented, so a model that refuses one (HTTP 400 that speaks of JSON, a schema or instructions) is asked again once
  with everything in plain text, and from then on that way; the JSON is then found in the text (`unwrap_json`) and checked like any
  other answer.
- **Fitted to the key.** The first time a question is asked, the app lists the models Google offers this key (`models.list`, one
  quick request with a 10 s limit that does not count against the answer). A model that was asked for and is not on the list is left
  out (it would only cost a failed request on every pass), and up to three more Flash models, or Gemma 4 models, from the list are
  added after the others: Flash-Lite before Flash, stable before preview, never an alias such as `-latest`, a Pro model (they
  are slower, and their free allowance is small or none: the free tier is shown only in Google AI Studio) or one that makes pictures
  or speech. If the list cannot be fetched, the models are used as they are and it is
  asked again a minute later. `GEMINI_DISCOVER=0` turns it off (and `none` in `GEMINI_FALLBACK_MODELS` adds nothing).
- Why: Google's "high demand" answer (HTTP 503) and its free allowances belong to each model, per project. The first check the
  author ran after the readings stopped working showed exactly that: the key and the model were accepted (a tiny request
  answered in 4.1 s), but the report request got "This model is currently experiencing high demand" twice, and the chat answers
  gave up and used the fixed wording. Another model on the same key was very likely free.
- A model that is busy (503 or a connection error) is left alone for 3 s, doubling each time it fails again, but never for more
  than 10 s: Google says "busy" within a second or two, and a longer rest would make a pass go by without asking it. One that is used up,
  or fails some other way, rests for 15 s, doubling up to 300 s (or as long as Google asks). One that is refused outright (a bad
  key, an unknown model name, an unsupported region) rests for 300 s, because trying again will not help until the file is
  fixed. So a model that is down does not slow down every request, and it is tried again soon enough.
- An answer that cannot be used (blocked, cut off, empty, not in the shape asked) does not make a model rest: the next model is
  simply asked.
- The first model may use at most 60 % of the time that is left while another can still take over, so a model that hangs cannot
  use up the time the next one needs; each model gets at least three seconds, and no model more than 75 s.
- When every model fails, the failure that is raised is the one that says what to do: a busy spell (worth waiting out) before a
  used-up allowance, and before the missing models. The first failure alone would have said "no such model" and rested the whole
  service for five minutes because the first of five models was retired. The log lists what each model said, one line each (what Google
  said, except for the busy message, which is always the same), and one line for the whole.
- `meta.model` and the chat's answers say which model really wrote the words. `GEMINI_THINKING`, if set, is sent only to models
  that take it, and a model that refuses it is asked again without it.

**The key's allowance (`ModelService`).**

- a per-minute budget (`GEMINI_MAX_PER_MINUTE`, default 12) and at most three calls at once;
- when **every** Gemini model fails in a way that is about the service (a rate limit, "high demand", a timeout, a server error,
  a bad key, an unknown model name, an unsupported region), every call pauses, for longer each time it repeats (15 s, 30 s,
  60 s ... up to 300 s), and a "retry in N seconds" from Google is respected; a bad key, an unknown model or an unsupported
  region rest for the full 300 s;
- an identical report request is answered from memory (`GEMINI_CACHE_SIZE`, default 32), so the same findings are not paid for
  twice; an answer that could not be used is never remembered;
- each request has a time limit (`GEMINI_TIMEOUT_SECONDS`, default 150 for a report, half of it for a chat answer but at most 45 s)
  that covers **all** the models and the repeats together; the library's own retries are switched off, so the app's back-off is the
  only one;
- when every model answered "high demand" (kind `overloaded`) or failed in a way that tends to pass (kind `error`), **the request
  is repeated**: a report up to eight times, after 4, 8, 12, 16 and then 20 s each time, a chat answer twice (4 s, 8 s), as long as
  the time limit allows. This was three tries (4 s, 8 s) until a log showed two models busy at once: all three rounds were over in
  about twenty seconds. Each repeat counts towards the per-minute budget. If a repeat works, nothing is remembered as a failure; if
  the last one fails too, the service rests once (a few seconds for a busy spell, longer for the rest), as above. A rate limit that
  says "retry in a few seconds" (twelve at most) is waited out the same way; a longer one is not (Google says how long to wait),
  and neither is a timeout;
- the key is read once from `backend/.env`, never logged, never put in an error message, and removed from any text that
  might hold it (the key itself and anything shaped like `AIza...`);
- every way a call can fail becomes one error, `ModelUnavailable`, with a kind (`rate_limited`, `overloaded`, `timeout`,
  `error`, `bad_key`, `bad_model`, `region`, `bad_request`, `blocked`, `cut_off`, `empty`, `bad_output`, `busy`, `chat_limit`,
  `no_key`) and a plain sentence for the person. When every model failed, the error is the first one's, and its detail says what
  each model said.

## 8. How it is tested without the network

No test can reach Google. A fixture in `tests/conftest.py` blanks the key for every test and replaces `google.genai.Client`
with a function that fails the test if anything calls it, so a real key in `backend/.env` can never leak into a test run. The
model is replaced by `tests/fake_gemini.py`, a fake that can be made to answer well, to break each rule, to return nonsense,
or to fail in every way Google can. The suite has 1314 tests, of which these concern the language model:

| File | Tests | What it proves |
| --- | --- | --- |
| `test_kb.py` | 150 | every entry is complete, cautious, sourced, in plain words and passes the guard; the knowledge base covers every finding the analysis can produce; the whole fixed-rule report is in plain words too |
| `test_retrieval.py` | 11 | the lookup and the BM25 search pick the right entries, and never an entry the findings do not support |
| `test_guard.py` | 94 | each safety check, with good passages (confident predictions) and bad ones (dates, ages, health, money, misfortune, orders, claims of proof, fancy words) |
| `test_gemini_service.py` | 51 | budget, back-off, the repeat when Google is busy, cache, failure classification, and the real `GeminiModel` against a fake client (the request it builds, its timeout, thinking setting and error handling) |
| `test_gemini_failover.py` | 67 | the models taking turns: the first that answers wins, a busy or used-up model rests and is tried again, a model refused outright rests longest, an unusable answer is passed to the next, no model hangs the others, the time limit covers everything, and which model wrote is recorded; the patience (eight repeats with longer waits, a busy rest that stays short, the failure that is worth waiting out is the one raised); the models fitted to the key's list (and the real library's habit of closing a client that nothing refers to); a model that takes no JSON schema asked in plain text; what the log says |
| `test_report_writer.py` | 50 | what the model is shown and asked, which passages are used, retry, fallback, how firm the hand shape is, and that the report is never worse than the fixed wording |
| `test_chat_llm.py` | 65 | the chat's seven steps: boundaries, eligibility, context, intent, checks, fallback, limits; and that "Will I ...?" about love or work reaches the model |
| `test_gemini_api.py` | 14 | the whole API with a fake Gemini: a reading and a chat, with and without a key, with failures |
| `test_privacy.py` | 13 | no name, contact detail, file name or photo reaches the model (including the name a person gave a reading, which is never part of any prompt) |
| `test_config.py` | 8 | `backend/.env` is read however Windows saved it (with a byte-order mark, as UTF-16, with Windows line endings) |
| `test_check_gemini_script.py`, `test_live_report_script.py` | 47, 17 | the two scripts below, with a fake model, including a real `Failover` of two fake models |

## 9. Checking it for real

The fake proves the code; only Google can prove the key, the model name and the wording it produces. Two scripts do that on
the author's own computer and print what they find (they never print the key):

- `run.bat gemini` (`scripts/check_gemini.py`): shows the settings (the models, in the order they are tried), asks for one tiny
  answer and says which model gave it, then writes a report from a made-up pair of hands and answers five questions and three
  boundary questions, saying plainly which passed and which model wrote what. `--model NAME` tests one model alone (no other
  model may answer for it). `--probe` sends one tiny request to each model, one at a time: the app's own models first, then
  other Flash and Flash-Lite models from Google's list (eight at most), and says which of them answer for this key. A text copy
  of everything it prints is saved as `E:\Project\debug\check_gemini.txt` (made-up hands only, never the key), so a long
  screen need not be copied by hand.
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
  written entirely from the knowledge base and said so. That is what led to the repeat described in section 7.

On 23 November 2026 the readings stopped coming from Gemini again: `run.bat gemini` showed the key and `gemini-3.5-flash-lite`
accepted a tiny request, but the report request got "high demand" twice and the chat waited and fell back. The answer was not
another provider but more Gemini models on the same key, taking turns (section 7), with patient repeats, and a new voice
(sections 2.3 and 4). **That change was tested with a fake Gemini only: the development environment cannot reach Google.** Run
`run.bat gemini` (and `run.bat gemini --probe`) on the author's computer to see which models the key can use and what they write.

Later that evening Gemini was working, but the author found the readings still full of words a normal person would not use and
asked for plain, direct wording. Everything the reader says was rewritten in plain everyday words: the 68 entries (`palm-kb 3.0`),
the sentences the app writes itself, the instructions to Gemini (`report-prompt 3.0`, `chat-prompt 3.0`), the chat's fixed
answers, the notes under a reading, and the text on the website, including the built-in sample. The checks gained one rule
(`guard 2.1`, "plain words" in section 4). The checks for dates, ages, health, money, misfortune, orders and unseen lines were not
touched. **This too was tested with a fake Gemini only.** How real Gemini writes under the new instructions, and how often the new
rule sends a passage back, can only be seen with `run.bat live` on the author's computer.

Still to do: read the Gemini-written passages for the author's own photos as an examiner would, and mark any sentence that gives
a date or an age, speaks of health, money or bad luck, gives an order, or shows a mark the hands do not have.

## 10. Honest limits

- **Palmistry is an old art, not a science.** The reading speaks like a fortune teller, and the app says plainly, wherever it
  shows words, that this is a story about who a person may become and not a promise. It makes no claim about accuracy, and the
  checks keep it away from health, children, how long anyone will live, money amounts, misfortune and dates.
- **The knowledge base is a draft.** It must be read and checked against its named sources before it is presented as reviewed.
- **The guard is heuristic**, as section 4 says.
- **Gemini's output varies.** The same findings can be worded differently on another day or another model. The temperature is low
  (0.2 for the report, 0.3 for the chat), the checks hold the content to the knowledge base, and the app labels what Gemini wrote,
  but the wording is not fixed.
- **Free tier.** Limits are per key, change over time, and are shown only in Google AI Studio. Content sent may be used by Google.
- **The model names are settings** because Google renames and retires models. A `bad_model` failure says so on screen, and with
  several models in the list a retired name costs only a moment, because the next model answers.
- **A less capable model may write plainer words.** The fall-back models are chosen for being available, not for being the
  smartest; the knowledge base and the checks keep what they write inside the same limits, and `meta.model` says which one wrote.
- **The findings are only as good as the photo analysis.** A line the analysis misses is simply not described.
- **Sinhala and Tamil are translations.** They are written by Gemini from the checked English and are not reviewed by a native
  speaker (section 5a). Each one costs one more Gemini request, so on a busy day a reading may stay in English.

## 11. Where things are

| What | Where |
| --- | --- |
| The Gemini client, the models taking turns, and the care around them | `backend/app/llm/gemini.py` (`GeminiModel`, `Failover`, `ModelService`) |
| The rules and prompts, the findings payload, the output schemas | `backend/app/llm/prompts.py` |
| The knowledge base and its loader | `backend/app/llm/kb/` (README there), `kb/__init__.py` |
| Retrieval | `backend/app/llm/retrieval.py` |
| The safety checks | `backend/app/llm/guard.py` |
| The report writer | `backend/app/llm/writer.py`, with the fixed wording in `report.py` and `knowledge.py` |
| The chat | `backend/app/llm/chat_llm.py`, with the fixed rules in `chat.py` |
| What is removed from a question | `backend/app/llm/privacy.py` |
| Readings and chat answers in Sinhala or Tamil | `backend/app/llm/translate.py` |
| The website's own words in Sinhala and Tamil | `src/i18n/` (`si.json`, `ta.json`; `npm run i18n:check` lists what is missing) |
| Settings (`GEMINI_*`) | `backend/app/core/config.py`, `backend/.env.example` |

**To change something.** A different model: set `GEMINI_MODEL` in `backend/.env` (one name, or several separated by commas); the
models that take over are `GEMINI_FALLBACK_MODELS` (`none` turns them off), and `GEMINI_DISCOVER=0` stops the app from checking the names against Google's list for the key. A wrong or missing claim: edit the entry in
`kb/*.json`, raise `KB_VERSION`, and run the tests (they fail if the entry breaks a rule). A new rule: add it to `guard.py`,
raise `GUARD_VERSION`, and add a test that breaks it. A change to a prompt: raise its version (`REPORT_PROMPT_VERSION`,
`CHAT_PROMPT_VERSION`), because the version is written into every reading.
