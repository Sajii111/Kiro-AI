# Kiro AI: the backend

The FastAPI server behind the website. It lives in the same folder as the website, hands the built website out from
the same address as the API, and follows [`docs/API_CONTRACT.md`](../docs/API_CONTRACT.md) exactly.

## Run it

Windows: double-click **`run.bat`** in the folder above (see the main [README](../README.md#run-it-with-the-real-server-windows)).
By hand, from the folder that holds `package.json`:

```bash
python scripts/serve.py            # installs and builds what is missing, then starts the server and opens the browser
python scripts/smoke.py            # in a second window: checks the running server from the outside
python scripts/smoke.py --expect-real   # the same, and it fails unless the server really reads photos
python scripts/contact_sheet.py    # draws what the analysis finds in your own test photos (run.bat sheet on Windows)
python scripts/check_gemini.py     # tests the Gemini key and setup with made-up hands (run.bat gemini on Windows)
python scripts/check_firebase.py   # tests the Firebase key and the online database with one test document (run.bat firebase)
python scripts/live_report.py ../test-photos/person1   # a report for your own photos, each passage labelled (run.bat live)
python scripts/smoke.py --expect-gemini   # the same as smoke, and it fails unless Gemini really writes the words
python scripts/preflight.py        # one check of everything before a demonstration, with the app started by itself (run.bat preflight)
python scripts/package.py          # makes the zip to hand in, in ../submission, and refuses a key, a private file or a photo (run.bat package)
python scripts/fresh_copy.py       # starts that zip in another folder with no Node.js and no key, like a lecturer (run.bat fresh)
```

**How `run.bat` knows whether the website has to be built again.** After each build, `serve.py` writes `dist-server/source.sha256`: a fingerprint of
everything the website is built from (the files under `src` and `public`, `index.html`, `package.json`, `package-lock.json`, the Vite and TypeScript
settings, and a `.env` or `.env.local` if there is one), by name and by content, with line endings ignored. If the fingerprint still fits, the build is
used and **Node.js is not needed**. File dates play no part, because copying, zipping and cloning all change them. That is what lets the zip from
`run.bat package` start on a computer that has only Python. `--no-build` uses `dist-server` as it is and never builds.

Without the launcher (the Python packages already installed, the website already built with `npm run build:server`):

```bash
cd backend
python -m uvicorn app.main:app --port 8000
```

The server prints one line per request (the method, the path, the status) and never a body or a photo. `/v1/docs` shows
the interactive API page while `APP_ENV` is not `production`.

## What is real today, and what is a stand-in

This is **phase 4**: the lines are found in the photo itself, Gemini writes the words about them when a key is set, and accounts are kept in Cloud Firestore when a Firebase key is in place. Each phase replaced one piece and nothing else.

| Part | Today | Replaced by |
| --- | --- | --- |
| Every endpoint, errors, sessions, guest mode, ownership checks, deletes, export | **Real** | stays |
| Photo checks (file type, opens, size, focus, lighting) | **Real** (OpenCV and NumPy on the real photo) | stays |
| "Palm in view" | **Real**: the hand model finds the hand (21 landmark points) and says whether it is a palm, which hand it is, and whether it is whole, flat and big enough. A built-in sample drawing is judged by a skin-colour guess instead | stays |
| The six processing pictures (grayscale, Gaussian smoothing, CLAHE, Canny, adaptive threshold, morphology) | **Real** (OpenCV on the real photo) | stays |
| The reading stream (ten steps, live, one request) | **Real** | stays |
| Finding the hand | **Real**: MediaPipe's hand landmarker, a small neural network that runs on this computer (`app/cv/hand.py`) | stays |
| Finding the five lines, the hand shape and other creases | **Real**: classical image processing in `app/cv/palm.py` and `app/cv/lines.py`, no trained network (see below) | stays |
| The report and the chat | **Real** when `GEMINI_API_KEY` is set: Gemini writes the interpretive passages from the findings and a curated knowledge base, and every passage is checked (`app/llm/`, see "How the words are written" below). With no key, or whenever Gemini cannot answer, the same knowledge base writes them by fixed rules | stays |
| Where accounts are kept | **Real** when the Firebase key is in `secrets/`: every account, its hand profiles, readings and chats are saved in Cloud Firestore and are still there after a restart (`app/store/persist.py`, see "Where accounts are kept" below). Without the key, server memory: gone when the server stops. Guest sessions are never saved, and photos never are | stays |

A reading made from a person's own photos says what it is: `meta.mock` is `false`. `meta.provider` is `"gemini"` (and `meta.model`
names the model) when Gemini wrote at least one passage of the report, and `"knowledge-base"` when the fixed rules wrote all of it,
because there is no key or Gemini could not be used; `meta.note` then says why, in one sentence. Each chat answer says the same
through `source`. A reading made by a stand-in
(the website's built-in sample drawings, or a server that has no hand model) says so too: `meta.mock` is `true`, `meta.provider`
is `"sample"`, and the pages show a **Sample reading** label and draw the lines on a sketch, not on the photo.

## How the real analysis works

For every photo, in `app/cv/`:

1. **Find the hand** (`hand.py`). MediaPipe's hand landmarker returns 21 points (the wrist and four joints along each finger)
   and calls the hand left or right. That is the only trained model in the project. The same points decide the "palm in
   view" check: no hand found, the back of the hand (the model's left/right call and where the thumb is disagree), too small,
   edge-on, the wrong side for the slot, two hands, tilted, cut off by the edge, curled fingers.
2. **Cut the hand out** (`palm.py`). GrabCut, seeded by the landmarks, separates the hand from the background. The result
   keeps the crease search inside the skin and gives the outline.
3. **Straighten it** (`palm.py`). An affine warp puts every palm in the same frame: wrist at the bottom, fingers up, thumb to the
   right, one unit equal to the wrist-to-knuckles distance (400 pixels). A left and a right palm then look alike, and the
   photo's size, angle and distance stop mattering.
4. **Map the creases** (`palm.py`). The green channel (where skin lines show best) is divided by its own local average, so a shadow
   does not hide a crease. At three scales the Hessian (second derivatives) gives how strongly each pixel sits in a dark valley,
   and which way the valley runs. The strength is judged against the palm's own strongest creases, and the absolute strength
   (`contrast`) says whether the photo shows creases at all.
5. **Trace the lines** (`lines.py`). A dynamic-programming (Viterbi) tracer walks the best path through the ridge map, once for each
   of the five lines, in the zone where tradition puts it (the zones follow the knuckle positions). A line that was found is
   excluded from the next search, and the fate and sun lines are kept off the life line. The life, fate and sun lines also
   stay on the palm side of the thumb's base: the fold where the thumb meets the palm is a deep, straight crease that the
   tracer otherwise took for the life line (it did on two of six real hands; fixed in `palm-lines 1.1`).
6. **Judge each line** (`lines.py`). `detected` needs enough contrast in the photo, the line's own minimum length, and a strong,
   unbroken crease along its whole path. A weaker or shorter one is `uncertain`. Otherwise it is `not_visible`, and nothing is
   said about it. Traits (length, curve, clarity) and a confidence come from the traced path, never from a fixed table.
7. **Measure the hand's shape** (`lines.py`): palm width to length, and middle-finger length to palm length, from the silhouette and
   the landmarks. A hand that is turned, curled, cut off, or a poor photo gets an `uncertain` shape and no numbers.

`python scripts/contact_sheet.py` (`run.bat sheet`) draws every one of these steps for the photos in `..\test-photos`, so you
can see why a line was found, or not.

**What it will not do.** It does not guess: a palm with no visible lines gets no lines, and a blurred photo loses them, instead of
getting invented ones (tests in `test_lines.py` draw such hands and check). It finds the five principal lines, not
every crease. Some real palms have lines too faint for a phone photo, and the analysis says "not visible" for those.

## Modes: real, sample, auto

`ANALYSIS_MODE` (in `.env`, or an environment variable) chooses how photos are read:

| Mode | What happens |
| --- | --- |
| `auto` (the default) | Real analysis when the MediaPipe package and the model file `models/hand_landmarker.task` are there. Otherwise every reading is a labelled sample, and the server says so when it starts |
| `real` | Real analysis only. The server refuses to start without the package or the model, so a missing model is never mistaken for working analysis |
| `sample` | Never looks at a photo's content. Every reading is a labelled sample (what the tests use) |

`run.bat` prints which one is in force before the server starts. `GET /v1/health` answers `"analysis": "real"` or `"sample"`.
`run.bat models` downloads the hand model once (about 7 MB, checked before it is saved).

**The website's sample photos.** "Try a sample" makes drawings of a hand, which a hand finder rightly cannot find a hand in. So the
website marks them (`sample=1` on `POST /photos/validate`; `leftSample` and `rightSample` on `POST /readings`), and the server
judges those by the skin-colour guess and gives a clearly labelled sample reading. Marking a photo as a sample can only make a
result less real, never more: one sample photo makes the whole reading a sample. A real photo never carries the mark.

## How the words are written: Gemini, a knowledge base and checks

Full design and reasons: [`docs/LLM_DESIGN.md`](../docs/LLM_DESIGN.md). In short:

1. **Findings in, words out.** The image work produces findings (which lines, how long, how curved, how clear, the hand shape).
   Gemini turns what *traditional palmistry says* about them into plain English. The server writes every fact itself (what was
   seen, which lines were unclear, how the two hands differ, the disclaimer), so the model cannot get those wrong.
2. **A knowledge base, not memory.** `app/llm/kb/` holds 68 short entries in the project's own words from four named sources. For
   the report the matching entries are looked up by key; for the chat they are found by a keyword search (BM25) and filtered by
   what this reading shows. Gemini is told to stay close to them. It is a curated draft until the author has checked it against
   the sources (`app/llm/kb/README.md`).
3. **Every passage is checked** (`app/llm/guard.py`): no prediction, advice, health, money or lifespan talk, no invented marks, no
   "I can see", no unseen line described, no contradiction of the findings, no numbers, and everything put as the tradition's
   reading. A passage that fails is asked for once more, then replaced by the fixed wording. The guard is heuristic: it can miss
   something unusual and can refuse a good passage, which only costs a fallback.
4. **A reading and a chat always finish.** No key, a used-up allowance, a timeout, nonsense or a failed check give the fixed
   wording and a one-sentence reason. Calls are counted per minute, back off after a failure, and identical requests are remembered
   (`app/llm/gemini.py`).
5. **The boundaries do not depend on the model.** Questions about health, money, jobs, relationships, lifespan, the future and other
   people's profiles are declined by plain rules before Gemini is asked.

Turn it on with a key in `backend\.env` (see below); the settings are in `.env.example`. `run.bat gemini` checks the key and the
setup, `run.bat live` writes a report for your own photos with each passage labelled, and `GET /v1/health` answers
`"writer": "gemini"` or `"knowledge-base"`.

## Where accounts are kept: memory, and Cloud Firestore

The in-memory store (`store/memory.py`) is always the working copy: every route reads and changes it exactly as before. With a
Firebase key, `store/persist.py` keeps a copy of every **account** in the project's Cloud Firestore database as well:

- **Loaded when first wanted.** After a restart, a sign-in finds the account through `emails/{sha256 of the e-mail}`, a returning
  browser's cookie through `sessions/{sha256 of the token}`, and the account's profiles, readings and chats are read once, the first
  time they are needed.
- **Saved after every change.** After every request that can change something (any `POST`, `PATCH` or `DELETE` under `/v1`, the
  reading stream included, once it has finished), the server compares each loaded account's data with what it last wrote and writes
  only the documents that changed, and deletes the ones that went (a chat's messages before the chat). Each account is written in a
  batch of its own, so one account's problem cannot hold up another's. A periodic save and one at shutdown catch anything left.
- **What is never written:** a photo, the password (only its salted scrypt hash), a cookie (only its SHA-256 fingerprint), and
  anything from a guest session. A guest who signs up and copies their readings across makes them the account's, and they are
  saved from then on.
- **When the database cannot be reached.** Signing up or in needs it, so that answers `503` with *"The account database could not
  be reached just now. Please try again in a moment."* and leaves no half-made account; so does the first request for an account that
  has not been read since the server started. Everything else is answered from memory as usual, and what could not be saved is tried
  again after the next request (the server's log says so).
- **One message, one document.** A chat's messages are documents of their own under the chat, so a long chat never meets
  Firestore's limit of 1 MiB per document. A reading is one document: its findings, report and `meta`, a few tens of kilobytes.

The connection (`store/firestore.py`) uses Firestore's REST API, signed in with the service account key through `google-auth`,
which the Gemini library already installs: nothing extra to download, and nothing to compile on Windows. Requests from a server
signed in with a service account do not go through Firestore's security rules, which is why the database can be made in
*production mode* (no browser can reach it). Each document has a few plain fields to read in the Firebase console and the whole
object as JSON in `data`, because a reading holds lists of points and Firestore cannot store a list inside a list. The full list of
documents is in [`docs/API_CONTRACT.md`](../docs/API_CONTRACT.md#9-where-the-data-is-kept).

`run.bat firebase` (`scripts/check_firebase.py`) checks the key and the database before you rely on them. No test can reach a real
database: `conftest.py` sets `STORAGE=memory` for every test, and `tests/fake_firebase.py` stands in for Firestore (a dictionary that
refuses a document over 1 MiB, as Firestore does) with a throwaway key made while the tests run.

## Privacy: what leaves this computer

### What Gemini receives

**Only the findings, as words from short fixed lists** ("heart line: detected, long, gentle curve, clear"; "hand shape: square palm,
short fingers, earth"). A photo, a profile name, a file name, a score and a coordinate cannot be in them. In the chat, the person's
question and the last few messages go too, with e-mail addresses, links, runs of seven or more digits and the account's profile
names replaced by a bracketed word (`app/llm/privacy.py`). A person can still type something private, so the website says, next to
the chat box, that questions are sent to Gemini. `tests/test_privacy.py` runs the whole API and checks that no name, contact detail,
file name or photo reaches the model. **On Google's free Gemini tier, Google may use what it receives to improve its products, and
people may read it.** The website says so in the report, next to the chat box and in Settings. With no key, nothing is sent at all.

### What MediaPipe sends to Google

The hand model runs on this computer, in the server's process, from a file. No photo is sent to Google or anyone else. One
thing does leave: **the MediaPipe library itself contacts `play.googleapis.com` the first time a model runs**, to report that it
was used. We traced the library's network calls to check. Its own Python code hands over the name and version of the operating
system and the version of the library; a photo and the landmarks are not part of that call, and there is no switch to turn it off.
The connection is made by the library, not by this project, and the call is encrypted, so the claim is only about what the library is
built to send. It is listed here, in the website's privacy text, and in the report.

## Folder map

```
backend/
  app/
    main.py          The application: middleware, error handlers, the routes, and the website. create_app() builds it
    deps.py          What every route shares: who is calling, cookies, JSON answers
    schemas.py       Every shape in the contract, as Pydantic models (the same names and fields as src/api/types.ts)
    validation.py    Rules for names, emails, passwords and chat messages
    api/             One file per area: session, profiles, photos, readings (the stream), chat, account
    core/            Settings, errors, clock, random numbers, password hashing
    store/           memory.py (the data, in memory: one Bucket per account or guest session), persist.py (accounts also kept in
                     the online database), firestore.py (Cloud Firestore over its REST API), build.py (which of the two to use)
    cv/              Image work: images.py (photo checks), hand.py (finding the hand, the palm's coordinates), palm.py (silhouette,
                     straightening, ridge map), lines.py (tracing and judging the lines, hand shape, other creases),
                     findings.py (the sentences), pipeline.py (the steps and the stream), standin.py (the sample finder)
    llm/             Words. kb/ (the palmistry knowledge base as JSON, with its README), retrieval.py (lookup and BM25), prompts.py
                     (rules, what Gemini is told, output shapes), gemini.py (the Gemini client and its limits), guard.py (the safety
                     checks), writer.py (the report written by Gemini), chat_llm.py (the chat answered by Gemini), privacy.py,
                     and the fixed-rule writers that always stand behind them: knowledge.py, report.py, chat.py
  tests/             1056 tests, and the made-up palm photos, drawn hands, fake Gemini and fake Firestore they use
  requirements.txt   The packages the server needs, pinned
  requirements-dev.txt   And the ones the tests need
  .env.example       Optional settings: the Gemini key, where accounts are kept
  models/, secrets/  The hand model (`run.bat models` downloads it) and the Firebase key. Git ignores what you put there
```

## Settings

None are needed. To change one, copy `.env.example` to `.env` (same folder) and edit it. A real environment variable beats the file.
`.env` and everything in `secrets/` are ignored by Git, so a key can never be committed by accident. The most useful ones:
`PORT`, `GUEST_SESSION_MINUTES` (set 1 to show guest expiry in a demonstration), `STAGE_PAUSE_MS` (the pause between processing
steps so each can be seen; 0 for none), `ANALYSIS_MODE` (`auto`, `real` or `sample`, see above) and `HAND_MODEL` (where the hand model file is).

**Gemini** is switched on by one line in `.env`: `GEMINI_API_KEY=` followed by the key from <https://aistudio.google.com/apikey>
(no quotes, no spaces, no billing). Without it, the fixed wording writes everything. The file is read however Windows saved it (with a
byte-order mark, as UTF-16, with Windows line endings), and the key is never printed, logged or put in an error message. The others:
`GEMINI_MODEL` (default `gemini-3.5-flash-lite`), `GEMINI_THINKING` (`MINIMAL`, `LOW`, `MEDIUM`, `HIGH`, or empty for the model's own
default: try `LOW` if an answer is cut off), `GEMINI_TIMEOUT_SECONDS` (60), `GEMINI_CHAT_LIMIT` (40 Gemini-written answers per
session), `GEMINI_MAX_PER_MINUTE` (12) and `GEMINI_CACHE_SIZE` (32).

**Cloud Firestore** is switched on by a file, not a line: the service account key from the Firebase console (*Project settings >
Service accounts > Generate new private key*), saved as `secrets/firebase-service-account.json`. `STORAGE` chooses: `auto` (the
default: the database whenever that file is there), `memory`, or `firestore` (the server refuses to start without a usable key).
`FIREBASE_KEY` points to the key somewhere else, and `FIRESTORE_DATABASE` names the database if it is not the project's first,
`(default)`. The server window says which it uses (`Storage: FIRESTORE (Firebase project ...)` or `Storage: MEMORY`), and so does
`GET /v1/health`. The key is a password to the database: it is never printed, and `run.bat package` refuses to pack it.

## Tests

```bash
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest                       # 1056 tests, about three minutes
python -m ruff check app tests ../scripts   # the code checker
```

What they cover, in the order a marker would ask:

- **Every endpoint**, its status codes, and one error body for every failure (`test_session`, `test_profiles`, `test_photos`, `test_readings`, `test_chat`).
- **Isolation** (`test_isolation`): two people use the same server, and neither can read, change or delete the other's profiles, readings or chats. An id that belongs to someone else answers exactly like an id that does not exist, so ids cannot be probed.
- **Photos are never kept** (`test_photos`): uploads stay in memory, a photo that fails stops the reading before any step runs, and a test fails if a photo ever reaches the disk.
- **The stream** (`test_readings`): ten steps in order, six pictures, the reading last and only after it is saved, and what happens when a step fails, the browser disconnects, the profile is deleted mid-way or a guest session ends mid-way.
- **The chat rules** (`test_chat`): 33 questions checked against what it must refuse (medical, money, work, relationships, how long someone will live, predictions) and what it must answer.
- **The website** (`test_site`): the built site and its client-side routes, the security headers, no inline scripts, the right file types.
- **The hand and its coordinates** (`test_hand_geometry`): a hand drawn at any angle, on either side, gives the same palm coordinates; the "palm in view" check fails, warns or passes for each situation it names, most serious first; the mode switch refuses to start without the model in `real` mode.
- **Straightening** (`test_palm_view`): a point lands at its palm coordinates whatever the size, angle and side, and a tiny hand in a huge photo is not enlarged to fit.
- **Finding the lines** (`test_lines`): hands are drawn with creases at known places (`tests/synth.py`), turned, mirrored, shrunk, dimmed and JPEG-squeezed, and each traced line must lie on the crease that was drawn, cover all of it, and get the right words. A palm with no lines gets none, a blurred or faint one loses them, and the tracer and the rules for detected, uncertain and not visible are tested on their own.
- **Real analysis through the API** (`test_real_mode`): a stand-in for the hand model answers with the drawn hands' landmarks, so the whole route is tested (validate, the stream, the saved reading, a photo with no hand, the wrong slot, the sample flags) without the model file.
- **The hand-model downloader** (`test_fetch_models`): a download is checked before it gets its real name, a web page or damaged file saved by mistake is refused, and nothing half-finished is left behind.
- **The knowledge base** (`test_kb`, `test_retrieval`): every entry is complete, cautious, sourced and passes the safety checks, every length, curve and clarity of every line has an entry, and retrieval never offers an entry the findings do not support.
- **The safety checks** (`test_guard`): each rule (prediction, advice, health, invented marks, claims to see, an unseen line, the other hand, the dominant hand, numbers, contradicting the findings) is tested with good passages and with passages that break only that rule.
- **The Gemini client** (`test_gemini_service`, `test_config`): the per-minute budget, back-off, the cache, the one repeat after Google says it is busy, every kind of failure turned into one error, the request the real client builds (checked against a fake client), and a `.env` read however Windows saved it. A fixture in `conftest.py` makes any test that tries to reach Google fail, and blanks the key, so a real key on your computer can never leak into a test run.
- **The report writer and the chat with a fake Gemini** (`test_report_writer`, `test_chat_llm`, `test_gemini_api`, `test_privacy`): what the model is shown and asked, which passages are used, the retry, the fallback, the limits, that a reading and a chat always finish whatever the model does, and that no photo, name, file name or contact detail ever reaches it.
- **The two Gemini scripts** (`test_check_gemini_script`, `test_live_report_script`): they are run with a fake model, so what they print, and that they never print the key, is tested before you run them on a real one.
- **Accounts in the online database** (`test_storage`, `test_check_firebase_script`): against a stand-in for Firestore, an account, its sign-in and everything it owns are there after a restart, in the same order; deletes really delete; a guest is never written; no photo, password or cookie is ever written; a long chat never makes a document too big; a database that is down costs an error message and never a half-made account, and a change that could not be saved is saved on the next request; one account's refused batch never holds up another's. The REST calls are checked against a fake connection (paging, a missing database, a refused key), and `run.bat firebase` is run against the stand-in, so what it prints, and that it never prints the key, is tested before you run it for real.

`python scripts/smoke.py` is a different kind of check: it needs a running server and nothing else, so you can run it on a
computer that has no test packages and show a marker that the whole thing works.

## Decisions worth knowing

- **One address.** The server hands out the built website and the API together. A cookie set by one address and used by another is a
  third-party cookie, which Safari, Firefox and private windows block, and sign-in would seem to work and then be forgotten.
- **Isolation by structure, not by care.** Everything a person owns sits in one `Bucket`. A route gets the caller's bucket and can only ask *it*,
  so there is no query that could forget a "where owner = me". The tests then check it anyway.
- **Passwords** are hashed with scrypt (a slow, memory-hungry hash made for passwords) with a random salt for each account, and a wrong email
  takes as long to answer as a wrong password, so the answer does not tell anyone which emails have accounts.
- **Sessions** are random 32-byte tokens in `HttpOnly` cookies (`kiro_session`, `kiro_guest`). The website never sees one. The guest cookie
  outlives the guest session by a day so the server can still say "your guest session ended" (a browser deletes an expired cookie
  at once, and the server would never know).
- **Photos** are read into memory, checked, processed and dropped. Python's upload parser normally spills anything over 1 MB to a temporary file;
  the server raises that limit so it never does.
- **The stream** is one `POST` whose answer is server-sent events (`stage`, `reading`, `error`, and `: ping` while a step is slow). The image work runs in
  a worker thread, so the server keeps answering other people, and the work stops at once if the browser goes away.
- **Heavy work stays off the main loop**: OpenCV and password hashing run in threads; the data is only ever touched on the main loop, so it needs no locks.
- **The database is a copy, not the working store.** Routes never wait for Firestore except to sign up, in or out, and the first time an
  account's data is wanted after a restart. Saving happens after the answer has gone, in one batch per account, so a slow or missing database
  costs a retry, not a broken page. The price is that a change made in the last moments before a crash could be lost; for a palm-reading
  app that is an acceptable trade.

## If something goes wrong

| What you see | Why, and what to do |
| --- | --- |
| `Python 3.12 or newer was not found` | Install it from python.org and tick *Add python.exe to PATH*, then run `run.bat` again |
| The packages fail to install | Usually no internet. If it says `No matching distribution`, the Python is too old or 32-bit: install 64-bit 3.12 or newer, delete `backend\.venv`, run again |
| `Port 8000 is used by another program` | `run.bat` picks the next free port by itself. Or choose one: `run.bat --port 8100` |
| The page says *the website has not been built yet* | Run `run.bat --rebuild`, or `npm install` then `npm run build:server` |
| `Node.js is needed once, to build the website, and was not found` | This folder has no built website (it is a Git clone, not the zip). Install the LTS version from nodejs.org and run `run.bat` again. The zip from `run.bat package` carries a built website and does not need Node.js |
| `Node.js was not found, so the older build of the website will be used` | The sources changed after the last build, and there is no Node.js to build it again. The older website still works, but it may not show the newest screens |
| A blank page | Press F12 and look at the console. If it names a file under `/assets` that cannot be found, the build is out of date: `run.bat --rebuild` |
| Signed in, then asked to sign in again after a restart | The server keeps accounts in memory only (its window says `Storage: MEMORY`). Put the Firebase key in `backend\secrets` and check it with `run.bat firebase` (the main README says how) |
| `run.bat firebase` fails | It says what to do for each failure: no database yet (create it in the Firebase console), the Firestore API switched off, a key from another project or a deleted key, a wrong computer clock, no internet |
| `The account database could not be reached just now` when signing up or in | The server has the key but cannot reach Firestore: check the internet, then `run.bat firebase`. Guest mode works without it |
| The server window says `Analysis: SAMPLE ONLY, because the hand model file is missing` | Run `run.bat models` once, then start `run.bat` again. Until then every reading is a labelled sample |
| `ANALYSIS_MODE=real, but the hand model is missing` and the server stops | Same fix: `run.bat models`. Real mode never falls back to samples on its own |
| `We could not find a hand in this photo` | The hand model found nothing: hold the whole palm flat to the camera in even light, with the fingers apart and the whole hand in the frame |
| A line the palm clearly has is `not visible` | The photo's creases are too faint at its size and focus (the contact sheet shows the ridge map). Try a closer, sharper photo in even daylight |
| `run.bat sheet` says the private environment is not there | Run `run.bat` once first (it makes `backend\.venv`), then close it and run `run.bat sheet` |
| `run.bat gemini` says the key is missing | There is no `backend\.env`, or its `GEMINI_API_KEY=` line is empty or still has a `#` in front. Make the file as the README says (Notepad is fine) and save it as plain text |
| `Gemini did not accept the key` | The key is wrong, was copied with a space or quotes, or was deleted in AI Studio. Make a new one and paste it after `GEMINI_API_KEY=` |
| `Gemini does not know the model name` | Google renamed or retired it. Run `run.bat gemini --probe`, then put a name it lists in `GEMINI_MODEL` |
| `Gemini is very busy right now` | Google answered "high demand" twice in a row, a temporary spell on the free tier. The reading used the fixed wording and said so; the server tries again by itself after a pause. Run `run.bat live` again in a few minutes |
| `Gemini's free allowance is used up for now` | Wait (the server tries again by itself after a pause, and the reading and chat carry on with the fixed wording meanwhile), or try another model with `--probe` |
| `Gemini is not offered from this location without billing` | The free tier is not offered where the request comes from. Without a key everything still works with the fixed wording; the other fix is Google's billing, which this project does not need |
| `Gemini's answer was cut off` | Set `GEMINI_THINKING=LOW` in `.env` and restart |
| A reading says `Gemini wrote 5 of 7 passages` | Two passages broke a safety rule twice and use the fixed wording: that is the checks working. `run.bat live` shows which, and why |
