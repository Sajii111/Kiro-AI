# Kiro AI: API contract

This is the agreement between the website (this repository) and the FastAPI backend. Build the backend to this and the
website works without any change to the screens.

- **The source of truth is [`src/api/types.ts`](../src/api/types.ts).** Every shape below is copied from it. If this
  document and that file ever disagree, the file wins.
- The website's built-in sample backend (`src/api/mock/`) returns exactly these shapes, so you can compare your server's
  answers with the sample ones screen by screen.
- The website's HTTP client is [`src/api/http.ts`](../src/api/http.ts). It is the only code that calls the server.
- **The backend that follows this contract is in [`backend/`](../backend/README.md)** (FastAPI). Its tests check every
  endpoint and that one account never sees another's data (`backend/tests`), and `python scripts/smoke.py` checks a
  running server from the outside. Where this document says "the server", that is the code in `backend/`.

Switching over: double-click `run.bat`. It builds the website for the server (`npm run build:server`, which switches
`VITE_USE_MOCK` off for you, see [`vite.config.ts`](../vite.config.ts)) and starts the backend, and the website is then served from
the same address as the API. To keep working on the screens with `npm run dev` against the real server instead, set
`VITE_USE_MOCK=false` in `.env.local` (see [`.env.example`](../.env.example)) and run `run.bat --no-browser` beside it.

---

## 1. At a glance

Base address: `{origin}/v1`. JSON in, JSON out, except photo uploads (multipart) and the reading stream (server-sent events).

| Area | Method and path | Returns |
| --- | --- | --- |
| Session | `GET /session` | `RestoreResult` |
| | `POST /auth/signup` | `Session` |
| | `POST /auth/signin` | `Session` |
| | `POST /auth/guest` | `Session` |
| | `POST /auth/signout` | 204 |
| | `GET /auth/guest/summary` | `DataCounts` or `null` |
| | `POST /auth/guest/import` | `DataCounts` |
| | `DELETE /auth/guest` | 204 |
| Hand profiles | `GET /profiles` | `HandProfile[]` |
| | `POST /profiles` | `HandProfile` |
| | `PATCH /profiles/{id}` | `HandProfile` |
| | `DELETE /profiles/{id}` | `DeleteSummary` |
| Photos and readings | `POST /photos/validate` | `ValidationResult` |
| | `POST /readings` | event stream, ending in a `Reading` |
| | `GET /readings?profileId=` | `ReadingSummary[]` |
| | `GET /readings/{id}` | `Reading` |
| | `DELETE /readings/{id}` | `DeleteSummary` |
| Chat | `GET /conversations?readingId=&profileId=` | `Conversation[]` |
| | `POST /readings/{id}/conversations` | `Conversation` |
| | `GET /conversations/{id}` | `ConversationWithMessages` |
| | `POST /conversations/{id}/messages` | `{ user, assistant }` |
| | `DELETE /conversations/{id}` | `DeleteSummary` |
| Account data | `GET /account/export` | `ExportBundle` |
| | `DELETE /account/data` | `DeleteSummary` |
| Health | `GET /health` | `{ ok, service, version, analysis, writer, writerModel?, storage }` |

The website accepts any success status in the 200 range. The server answers `201` to `POST /profiles` and
`POST /readings/{id}/conversations`, `204` to `POST /auth/signout` and `DELETE /auth/guest`, and `200` to everything else.
Ids are opaque strings. `GET /health` is for people and scripts, not for the website. It answers
`{ "ok": true, "service": "kiro-ai", "version": "0.1.0", "analysis": "real", "writer": "gemini", "writerModel": "gemini-3.5-flash-lite", "storage": "firestore" }`,
where `analysis` is `"real"` when the server has the hand model loaded (the lines are found in the photos) and `"sample"` when it
has not (every reading is then a labelled stand-in), and `writer` is `"gemini"` when a Gemini key is set (so the language model
writes the report and the chat, and `writerModel` names the model) or `"knowledge-base"` when it is not (fixed wording writes
them, and `writerModel` is left out). `storage` is `"firestore"` when accounts and everything they own are also kept in the online
database (see [Where the data is kept](#9-where-the-data-is-kept)) and `"memory"` when they last only until the server stops; the
Settings page reads it to tell a signed-in person where their account is kept. It never contains a key.

---

## 2. Ground rules

### Conventions

- Field names are `camelCase`. Timestamps are ISO 8601 in UTC, for example `"2026-11-08T09:30:00Z"`. The one exception is a
  guest's `expiresAt`, which is milliseconds since 1 January 1970 (a number).
- Positions on a photo are **fractions of its width and height from 0 to 1, origin at the top left**. See
  [normalised points](#normalised-points).
- Send `Cache-Control: no-store` on every response. Everything here is personal.

### Sessions

- The session lives in an **httpOnly cookie** that the server sets. The website never sees a token, never stores one,
  and sends no `Authorization` header. Every request is sent with `credentials: "include"`.
- Two cookies: **`kiro_session`** (signed in, lasts 14 days) and **`kiro_guest`** (guest). Both are `HttpOnly; SameSite=Lax; Path=/`, and `Secure` in production only, so plain `http://127.0.0.1` works on your own computer. Each holds a random token and nothing else. If both are present, the signed-in session wins.
- **The guest cookie outlives the guest session by 24 hours.** A browser deletes a cookie the moment it expires. If that were the same moment the session ends, the next `GET /session` would arrive with no cookie at all, and the server could never say "your guest session ended" (`guestExpired`, below). The data behind the cookie is deleted at `expiresAt` regardless.
- **The site and the API must share one site for this to work.** A cookie that one address sets for another (for example a
  site on `kiro.pages.dev` calling an API on `kiro-api.onrender.com`) is a *third-party cookie*, and Safari, Firefox's
  default protection and every private window block or isolate those. Sign-in would appear to work and then be forgotten.
  Three layouts that do work:
  1. **One service** (what the project plan describes): FastAPI serves the built website and the API from one address. No CORS, no cookie problem. See [section 10](#10-hosting-the-website-and-the-api).
  2. **Two subdomains of one domain you own**, for example `app.example.com` and `api.example.com`, with the cookie set for `.example.com` (`Domain=.example.com`) and the API allowing the website's origin for CORS (`Access-Control-Allow-Origin: https://app.example.com`, never `*`, plus `Access-Control-Allow-Credentials: true`, and `OPTIONS` preflight answered).
  3. **A proxy in front** that makes `/v1` look like part of the website (a rewrite rule on the static host). Check first that the proxy streams `text/event-stream` and allows a request to last a minute; some do not.
- In development Vite does the proxying (see the README), so none of this is needed on your own computer.
- If the site and the API will live on unrelated domains, cookie sessions are the wrong tool. The fix is a bearer token in a header instead of a cookie: a small change to `src/api/http.ts` and one extra field in the sign-in responses. Ask for it before choosing that hosting.

### Ownership

Every profile, reading and conversation belongs to exactly one account (or one guest session). **Check ownership on every
read and every write**, and never trust an id sent by the browser. Answer `404 not_found` both for ids that do not exist
and for ids that belong to someone else, so nobody can probe for other people's records.

How the objects belong to each other: one account owns many hand profiles. A reading belongs to one profile. A
conversation belongs to one reading. A message belongs to one conversation.

### Errors

Every failure has the same body, and `message` is a plain sentence the website shows to the person as it is. Write it for a
person, not for a developer.

```json
{ "error": { "code": "invalid", "message": "Keep it to 24 characters or fewer." } }
```

| `code` | Usual status | When |
| --- | --- | --- |
| `invalid` | 400, 422 | The request is wrong: a bad field, a missing photo, a duplicate profile name |
| `unauthorised` | 401 | Not signed in, or wrong email or password |
| `forbidden` | 403 | Signed in, but not allowed to do this |
| `not_found` | 404 | No such thing, or not yours |
| `expired` | 410 | A guest session has ended and its data is gone |
| `processing_failed` | 500 and anything else | The server could not finish. Say what was and was not saved |

If the body is missing, the website falls back to the status: 400 and 422 mean `invalid`, 401 `unauthorised`, 403
`forbidden`, 404 `not_found`, 410 `expired`, anything else `processing_failed` with a generic sentence. When the server
cannot be reached at all, the website says so itself (`network`).

A `401` or `410` on any route other than `/auth/*` and `/session` makes the website look the session up again and, if it
has ended, send the person to the sign-in page with a short notice.

### Never stored

Palm photographs are sensitive. **No photo is ever written to permanent storage**, not as a file, not in a database, not in a
log. The backend processes photos in memory or in a per-request temporary directory and deletes every temporary copy when
the request ends, **including when it fails or the browser disconnects**. What is stored is only: structured findings, the
report, and the chat.

**How `backend/` keeps this promise.** It reads uploads into memory only. (Starlette would normally spill any upload over
1 MB into a temporary file, so the server raises that limit to the size of a request, and a test, `test_no_photo_is_ever_written_to_disk`,
fails if a photo ever reaches the disk.) Nothing it logs contains a body: an unhandled error logs the method and the path only.

---

## 3. Sessions and accounts

### `GET /session`

Called on every page load. **Never answers 401.**

```json
{ "session": { "kind": "user", "user": { "id": "usr_1", "email": "saji@example.com", "displayName": "Saji" } } }
```

| Situation | Body |
| --- | --- |
| Signed in | `{ "session": { "kind": "user", "user": { "id", "email", "displayName" } } }` |
| Guest | `{ "session": { "kind": "guest", "guestId": "gst_1", "expiresAt": 1789000000000 } }` |
| Nobody | `{ "session": null }` |
| A guest session ended since the last visit | `{ "session": null, "guestExpired": true }`, and clear the stale guest cookie so this is only said once |

At `expiresAt` the website asks `GET /session` again, so the server should have deleted the guest data by then. A
`kiro_guest` cookie that matches no live guest session (it ended, the sweeper already deleted it, or the server was restarted)
counts as ended: the answer is `guestExpired: true`, once, and the cookie is cleared.

### `POST /auth/signup`

Body: `{ "email": "...", "password": "...", "displayName": "..." }`. Creates the account, signs the person in (sets the
session cookie) and returns a `user` `Session`.

- `422 invalid` with a sentence for: bad email, password under 8 characters, empty or over-long display name (24 characters), an email that is already registered.
- **Signing up does not end a guest session.** See [guest import](#get-authguestsummary-post-authguestimport-delete-authguest).

### `POST /auth/signin`

Body: `{ "email": "...", "password": "..." }`. Returns a `user` `Session`. Wrong email or password: `401 unauthorised` with one sentence that does not say which of the two was wrong. Signing in does not end a guest session either.

### `POST /auth/guest`

No body. Starts a guest session and returns `{ "kind": "guest", "guestId": "...", "expiresAt": <ms> }`. A guest can do the
**whole** workflow (profiles, readings, chat), but everything is temporary:

- it is never listed as saved history,
- it is deleted when the session ends, when the lifetime is reached (the server decides: 2 hours by default, `GUEST_SESSION_MINUTES` in `backend/.env`), or on sign-out,
- after it is gone, calls answer `410 expired`.

### `POST /auth/signout`

`204`. Clears the session cookie. For a guest this also **deletes everything from the guest session straight away**; the
website warns the person first.

### `GET /auth/guest/summary`, `POST /auth/guest/import`, `DELETE /auth/guest`

What happens when a guest later signs in or signs up. The website never copies guest data silently.

1. Right after sign-in or sign-up the website calls `GET /auth/guest/summary`. It answers `DataCounts` for the guest session that is still attached to this browser (its cookie is still there), or `null` when there is nothing to offer.
2. If there is something, the person is asked. "Yes" calls `POST /auth/guest/import`; "No" calls `DELETE /auth/guest`.
3. `import` (needs a signed-in session) copies the guest's profiles, readings, conversations and messages into the account with **new ids** (a profile whose name already exists in the account is renamed, for example "Nimal 2"), then deletes the guest data and clears the guest cookie. It returns the counts it copied.
4. `DELETE /auth/guest` deletes the guest data and clears the guest cookie. `204`.
5. If the person does neither, the guest data simply expires on its own.

```json
{ "profiles": 2, "readings": 3, "conversations": 1, "messages": 4 }
```

---

## 4. Hand profiles

```ts
type HandProfile = {
  id: string
  name: string                  // a first name or nickname
  owner: 'self' | 'other'       // "self" = my own hands, "other" = someone who agreed
  consent: boolean              // for "other": they agreed to their palms being uploaded
  createdAt: string
  readingCount: number
  lastReadingAt: string | null
}
```

| Request | Notes |
| --- | --- |
| `GET /profiles` | Every profile of the caller, **oldest first**. |
| `POST /profiles` | Body `{ "name", "owner", "consent" }`. Returns the new profile. |
| `PATCH /profiles/{id}` | Body `{ "name" }`. Returns the profile. |
| `DELETE /profiles/{id}` | **Cascades**: the profile, its readings, their conversations and every message in them, and all derived feature data. Returns what was removed (`DeleteSummary`). |

Rules to enforce (the website checks the same ones first, so these only matter if someone bypasses it):

- `name`: trimmed, 1 to 24 characters, only letters, numbers, spaces and `' ’ . -`. Nothing that looks like an email or a phone number (no run of five or more digits). Unique within the account, ignoring case.
- `owner: "other"` needs `consent: true`, otherwise `422 invalid`. For `"self"`, store `consent: true`.
- At most **12 profiles** per account.

```ts
type DeleteSummary = { profiles: number; readings: number; conversations: number; messages: number }
```

---

## 5. Photos, readings and the processing stream

### `POST /photos/validate`

`multipart/form-data` with `side` (`left` or `right`), `photo` (a file) and, optionally, `sample` (`1`). Checks one photo, **discards it straight after**,
and always answers `200` with a `ValidationResult`, even when the photo is bad. Use an error status only when the request
itself is broken (a missing part, an unknown `side`, a file over the size limit).

```ts
type ValidationResult = {
  side: 'left' | 'right'
  ok: boolean                   // false when at least one check failed. Warnings never block.
  width: number                 // size of the photo that was checked, in pixels
  height: number
  checks: PhotoCheck[]          // always all six, in this order
}
type PhotoCheck = {
  id: 'file_type' | 'integrity' | 'dimensions' | 'blur' | 'lighting' | 'palm_visible'
  label: string                 // "File type", "File opens", "Size", "Focus", "Lighting", "Palm in view"
  status: 'pass' | 'warn' | 'fail'
  message: string               // plain language, and for warn/fail it says what to do next
}
```

`sample=1` says the photo is one of the website's built-in sample drawings ("Try a sample"). A hand finder cannot find a hand
in a sketch, so the server judges a marked photo by the simple skin-colour guess instead. The mark can only make a result less real, never
more, and a real photo never carries it. The website marks every built-in sample except the "not a palm" one, which is meant to be refused.

Examples of the sentences the sample backend uses (yours should be just as direct): *"This photo is too blurry to see the creases. Tap the palm to focus, hold still, and retake it."*, *"The light is uneven, with strong shadow on part of the hand. Even light works best."*

- A corrupt or unreadable file is `ok: false` with a failing `integrity` check, not an HTTP error.
- `file_type`: look at the first bytes of the file (JPEG or PNG), not at the name or the `Content-Type` the browser sent.
- A `fail` blocks the reading. A `warn` does not, but the findings will usually include `uncertain` lines.

**How `backend/` decides each check** (`backend/app/cv/images.py`; the numbers are measured on a copy of at most 320 px, and they are starting points to tune against real photos, not laws):

| Check | `fail` when | `warn` when |
| --- | --- | --- |
| `file_type` | the first bytes are not a JPEG or a PNG | |
| `integrity` | the file cannot be opened, or holds more than 24 million pixels | |
| `dimensions` | the short side is under 500 px | the short side is under 800 px |
| `blur` | sharpness under 14 (the variance of the Laplacian of the brightness: fine contrast) | under 40 |
| `lighting` | average brightness under 38 or over 238 (too dark, washed out) | under 70, over 205, or one quarter of the picture more than 3.4 times brighter than another |
| `palm_visible` | With the hand model: no hand found; the back of the hand; a palm under 120 px long; a palm turned edge-on (width across the knuckles under 0.30 of its length). Without it (a sample drawing, or a server with no model): skin-coloured pixels (a YCbCr range) under 0.5 % of the picture | With the hand model: the photo is added as the wrong hand; two hands; the palm tilted (under 0.45); part of the palm or the thumb cut off by the edge; a palm under 260 px; curled fingers. Without it: skin under 9 %, or skin touches the top or a side edge |

**What the browser has already done:** it only accepts JPG or PNG up to 15 MB, shrinks anything over 1600 px on the longest
side, and re-encodes it as a JPEG (quality 0.9) with the camera's rotation already applied and the EXIF data removed.
Do not trust that. Validate again on the server, cap the decoded pixel count, and do not rotate the picture again.

### `POST /readings`

`multipart/form-data` with `profileId` (text), `left` (file), `right` (file) and, optionally, `leftSample` and `rightSample` (`1`, with the same meaning as `sample` above). Runs the whole pipeline on both photos and
answers with a **stream of server-sent events** on one response. The website reads it with `fetch`, so it is an ordinary
`POST`, not an `EventSource`.

Before the first byte of the stream, problems are ordinary JSON errors: `404` unknown profile, `422` a missing or invalid
photo (or a request over the size limit), `401` not signed in, `410` a guest session that has ended. The server must **check
both photos again** (the same checks as `/photos/validate`); a photo that fails stops the reading, with its sentence in the
`422`. `backend/` works on at most three readings at once, and the rest wait their turn.

Headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`, and (behind nginx) `X-Accel-Buffering: no`.
Do not gzip this route and do not buffer it. Send a comment line (`: ping`) every 10 seconds or so if a step is slow;
the website ignores comments.

Each event is a few lines followed by a **blank line**. Lines may end in `\n` or `\r\n`.

```
event: stage
data: {"stage":"validate","state":"running"}

event: stage
data: {"stage":"validate","state":"done","detail":"Both photos passed the checks"}

event: stage
data: {"stage":"gray","state":"done","detail":"Colour removed, brightness kept","previews":{"left":"data:image/jpeg;base64,...","right":"data:image/jpeg;base64,..."}}

event: reading
data: {"id":"rdg_9","profileId":"prf_2", ... the whole Reading ...}

```

| Event | `data` | Meaning |
| --- | --- | --- |
| `stage` | `ProcessingEvent` | A step started, finished or failed |
| `reading` | `Reading` | The finished reading. **Always last, and only after it has been saved.** |
| `error` | `{ "code", "message" }` | The reading failed. Close the stream. Nothing was saved. |

```ts
type ProcessingEvent = {
  stage: 'validate' | 'resize' | 'gray' | 'blur' | 'contrast' | 'edges' | 'threshold' | 'morphology' | 'lines' | 'reading'
  state: 'running' | 'done' | 'failed'
  detail?: string                                  // one short line, e.g. "Located 4 lines on the left hand"
  previews?: { left?: string; right?: string }     // small pictures of this step, as data URLs
}
```

- **Order and meaning of the stages.** Ten, always in this order. `validate` (photos checked), `resize` (both brought to one working size, 640 px on the long side), `gray` (grayscale), `blur` (Gaussian smoothing), `contrast` (CLAHE), `edges` (Canny), `threshold` (adaptive thresholding: each pixel against its own neighbourhood, leaving a black-and-white map of crease-like marks), `morphology` (opening, then closing: specks removed, broken pieces joined), `lines` (the lines are located, named and given a status), `reading` (the report is written). Send `running` when a step starts and `done` (or `failed`) when it ends. The screen shows them as a stepper, and the six image steps feed the **original-versus-processed slider**.
- **`previews`** go on the `done` event of the six image steps (`gray`, `blur`, `contrast`, `edges`, `threshold`, `morphology`): one small JPEG per hand, as a data URL, about 400 px on the longest side. They exist only for the length of this request and are never stored. The slider compares them with the person's original photo, which never leaves their browser tab. In `backend/` these six pictures come from real OpenCV calls on the real photos.
- The `detail` text is shown as it is. Be specific and honest, for example *"Located 4 lines on the left hand"*. Do not claim a step helped when it did not. `backend/` says *"6 of 10 lines detected, 2 uncertain, 2 not visible"* when the lines were found in the photos, and puts *"Sample result: "* in front when a stand-in made them.
- **Failure.** Send the failing `stage` event (`"state":"failed"`) and then `event: error`. Use `processing_failed` for a crash, `invalid` for a photo that did not pass the checks. Say what was and was not saved: *"We could not finish analysing these photos. Nothing was saved and your photos have been discarded. Please try again."*
- If the stream ends with no `reading` event, the website treats it as a failed reading.
- **If the browser disconnects** (the person cancelled or closed the tab), stop, save nothing, and delete the temporary files.
- The server must not send the photos anywhere except to the image-processing code. The processing screen tells the person that **only the findings, never the photos, go to the language model.** If you ever give a photo to a vision model, change that sentence first.

### `GET /readings?profileId=`

`ReadingSummary[]`, newest first. `profileId` is optional.

```ts
type ReadingSummary = {
  id: string
  profileId: string
  profileName: string
  createdAt: string
  counts: { detected: number; uncertain: number; not_visible: number }   // across both hands: 10 lines in total
  headline: string                                                       // one line, e.g. "Heart and head lines clear on both hands"
  conversationCount: number
}
```

**A profile can hold any number of readings.** `POST /readings` always *adds* a reading to the profile; it never replaces an
earlier one (a poor new photo must not be able to destroy a good reading, and two readings can be compared in History). A
person who wants only one reading per profile deletes the old one with `DELETE /readings/{id}`. The website treats the **first
item** of this list (newest first) as the profile's *newest reading*, which is what the Chat page opens on by default, so keep
that order.

### `GET /readings/{id}` and `DELETE /readings/{id}`

`GET` returns the full `Reading` (below). `DELETE` removes the reading, its conversations and every message in them, and
returns a `DeleteSummary`.

---

## 6. The reading

```ts
type Reading = {
  id: string
  profileId: string
  createdAt: string
  hands: { left: HandAnalysis; right: HandAnalysis }     // both, always
  report: Report
  meta: ReadingMeta
}
```

### Findings: the feature result format

The project plan asks for a structured result per hand: feature name, status, normalised coordinates, confidence, a short
visual observation and the method version. This is where each one lives:

| The plan asks for | Field |
| --- | --- |
| feature name | `FeatureResult.name` (and the stable `id`) |
| status: detected, uncertain, not visible | `FeatureResult.status`: `"detected"`, `"uncertain"` or `"not_visible"` |
| normalised coordinates or path points | `FeatureResult.path` and `searchArea` |
| confidence or quality indicator | `FeatureResult.confidence` and `HandAnalysis.quality` |
| short visual observation | `FeatureResult.observation` |
| processing and detection method version | `FeatureResult.method` and `HandAnalysis.methodVersion` |
| reading version, model and provider, prompt and knowledge-base version | `Reading.meta` |

```ts
type HandAnalysis = {
  side: 'left' | 'right'
  photo: { width: number; height: number }   // the size of the photo that was analysed (what the browser uploaded)
  quality: { sharpness: 'good'|'fair'|'poor'; lighting: 'good'|'fair'|'poor'; resolution: 'good'|'fair'|'poor'; palmVisible: boolean; score: number /* 0..1 */ }
  outline: [number, number][] | null         // the hand's outline as a closed shape, so a sketch can be redrawn after the photo is gone
  features: FeatureResult[]                  // exactly five, in this order: heart, head, life, fate, sun
  palmShape: PalmShape                       // the overall shape of the hand
  otherCreases: OtherCrease[]                // strong creases left over once the five lines were named. May be empty.
  methodVersion: string
}

type FeatureResult = {
  id: 'heart' | 'head' | 'life' | 'fate' | 'sun'
  name: string                               // "Heart line"
  status: 'detected' | 'uncertain' | 'not_visible'
  path: [number, number][]                   // 12 to 40 points along the line. EMPTY when not_visible.
  searchArea: { x: number; y: number; w: number; h: number }   // the area that was searched
  confidence: number | null                  // the DETECTION SCORE, 0..1: how strongly the detector matched this line. Not the chance a reading is right. null when not_visible.
  observation: string                        // one or two sentences, visual only
  traits: { length?: 'short'|'medium'|'long'; curve?: 'straight'|'gentle'|'pronounced'; clarity?: 'faint'|'clear'|'deep' }
  method: string                             // e.g. "opencv-ridge 0.4.1"
}
```

A detected line:

```json
{
  "id": "heart", "name": "Heart line", "status": "detected",
  "path": [[0.82, 0.37], [0.78, 0.36], [0.74, 0.355], "...12 to 40 points..."],
  "searchArea": { "x": 0.18, "y": 0.30, "w": 0.66, "h": 0.14 },
  "confidence": 0.81,
  "observation": "A clear, gently curved line crosses the upper palm and ends below the index finger.",
  "traits": { "length": "long", "curve": "gentle", "clarity": "clear" },
  "method": "opencv-ridge 0.4.1"
}
```

A line that could not be seen (**nothing is invented**):

```json
{
  "id": "fate", "name": "Fate line", "status": "not_visible",
  "path": [], "searchArea": { "x": 0.42, "y": 0.45, "w": 0.16, "h": 0.40 },
  "confidence": null,
  "observation": "No line could be picked out in this part of the photo.",
  "traits": {},
  "method": "opencv-ridge 0.4.1"
}
```

The rules the screens rely on:

- The screens draw by `status`, never by the number. **Detected** is a solid line, **uncertain** is dashed and labelled as a best guess, **not visible** shows only the dotted search area. Use `uncertain` whenever you are not sure; never promote a guess to `detected`.
- `traits` holds only what could actually be judged. An `uncertain` line may carry `clarity` and nothing else; a `not_visible` line carries `{}`.
- `confidence` is shown as a **"detection score"** (for example "detection score 85%") next to detected and uncertain lines. It says how strongly the detector matched the line, never how likely a reading is to be right, and the screens never call it "sure" or "accuracy".
- `outline`: with `null`, the sketch shows the lines without a hand silhouette.

### Hand shape and other creases

Besides the five lines, every hand has a **shape** and may have **other creases**. They follow the same rules as a line: only
what was seen is described, and the tradition's words about it stay in the report.

```ts
type PalmShape = {
  status: 'detected' | 'uncertain' | 'not_visible'
  traits: { palm?: 'square' | 'long'; fingers?: 'short' | 'long' }   // only what could be judged. Empty when uncertain or not visible.
  palmRatio: number | null       // palm width divided by palm length
  fingerRatio: number | null     // finger length divided by palm length
  confidence: number | null      // the detection score, 0..1. null when not_visible.
  observation: string            // visual only: "A square palm (width to length 0.98) with long fingers (...)"
  method: string
}

// A crease that was found but matches none of the five lines: shown as a thin dotted mark and counted, never named,
// and nothing at all is said about what it means.
type OtherCrease = { id: string /* "c1" */; path: [number, number][] /* 8 to 40 points */; confidence: number; observation: string }
```

The traditional "element" of a shape (earth, air, water, fire) is said in `report.shape`, never in `palmShape`.

### Normalised points

Every position is a pair `[x, y]` with both numbers from 0 to 1: `x` is the fraction of the photo's width, `y` the fraction
of its height, measured from the top-left corner of the photo **as the server received it**. `{ x, y, w, h }` boxes use the
same space. Because everything is a fraction, the same numbers land correctly on the full-size photo, on the small preview
and on the redrawn sketch.

### The report

```ts
type Report = {
  summary: string
  sections: ReportSection[]       // exactly five, one per line, in the order heart, head, life, fate, sun. The "by line" view.
  themes: ThemeSection[]          // exactly five, in the order personality, career, financial, relationships, future. The "by theme" view.
  shape: ShapeSection             // the shape of the hand, both hands
  uncertainty: string[]           // plain statements about anything unclear or missing, and about photo quality
  disclaimer: string
  generatedAt: string
}

type ReportSection = {
  featureId: 'heart' | 'head' | 'life' | 'fate' | 'sun'
  title: string
  observed:    { left: { status: FeatureStatus; text: string }; right: { status: FeatureStatus; text: string } }   // what was SEEN. Visual only.
  traditional: { left: string | null; right: string | null }   // what the TRADITION says. null where the line was not seen.
  comparison: string | null                                     // how the two hands compare. null when they cannot be compared.
}

// The shape of the hand. Same rule as a line: what was seen is kept apart from what the tradition says.
type ShapeSection = {
  observed:    { left: { status: FeatureStatus; text: string }; right: { status: FeatureStatus; text: string } }
  traditional: { left: string | null; right: string | null }   // the "element" (earth, air, water, fire). null where the shape was not judged.
  comparison: string | null
}

// One life theme, read the traditional way from the lines (and the hand shape) that WERE detected.
type ThemeSection = {
  themeId: 'personality' | 'career' | 'financial' | 'relationships' | 'future'
  title: string                       // "Personality", "Career and professional life", "Financial and prosperity themes", "Relationships and emotional life", "Future outlook"
  label: 'traditional'                // always. The screens print it on every theme, so a theme can never pass for a finding or a forecast.
  traditional: string | null          // what the tradition says, written ONLY from `basedOn`. null when nothing it rests on was clearly seen.
  basedOn: ('heart'|'head'|'life'|'fate'|'sun'|'shape')[]   // sources detected on at least one hand and used, in the order the tradition lists them
  leftOut: ('heart'|'head'|'life'|'fate'|'sun'|'shape')[]   // sources the theme normally rests on, but they were only uncertain or not visible on both hands, so they were not used
}

type ReadingMeta = {
  provider: string        // who wrote the words: "gemini" when Gemini wrote at least one passage of the report, "knowledge-base" when the fixed rules wrote all of it (no key, or Gemini could not be used), "sample" for a stand-in.
  model: string           // the Gemini model's name when provider is "gemini", "rule-based-writer" for the fixed rules, "stand-in-writer" for the stand-in
  knowledgeBase: string   // version of the curated palmistry knowledge base, e.g. "palm-kb 1.0"
  prompt: string          // versions of the instructions and of the safety checks, e.g. "report-prompt 1.0 + guard 1.0" ("fixed-rules 1.0" when the fixed rules wrote all of it)
  pipeline: string        // version of the image-processing pipeline
  mock: boolean           // true when this reading came from the sample backend or from the stand-in analysis. false when the lines were found in the person's own photos
  note?: string           // one plain sentence on how the words were written: which passages Gemini wrote, and why any came from the knowledge base instead. Left out when there is nothing to say (no key, or a sample reading)
}
```

**Two views of one report.** The report page opens **by theme** (what a person usually wants to know) and a switch shows it **by
line** (what the examiners listed). Both are built from the same findings, and a theme never mentions a line that was not clearly
seen: that line goes into `leftOut`, and a theme with nothing to rest on has `traditional: null`.

**Who writes which words.** Every report is first written completely by fixed rules from the knowledge base. With a Gemini key the
server then asks Gemini for the *interpretive* passages only (the summary overview, what each detected line is linked with, the
tradition's reading of a match or difference between the hands, the hand shape, the five themes), checks each one, and swaps in
the ones that pass. The `observed` text, the list of what was unclear, the comparison of what the two hands show, the "left out"
sentence, the closing reminders and the `disclaimer` are always written by the server, because they are measured or fixed. The
response has the same shape either way; only `meta` (and the wording) differs. See [`LLM_DESIGN.md`](LLM_DESIGN.md).

Rules for the report text (the language model must be held to these by the prompt and by checks on its output):

- **What was seen is kept apart from what the tradition says.** The `observed` text describes the image; the `traditional` text is the tradition's reading of a line that was seen.
- **Never write about a line that was not seen.** Where `status` is `not_visible`, `traditional` is `null`. Where it is `uncertain`, say so in the text.
- The model gets the structured findings, not an invented list of lines.
- `disclaimer` always says that palmistry is a traditional practice for reflection and entertainment, and that nothing in the reading is medical, financial, employment or relationship advice.
- **Every theme is labelled `traditional`, names what it rests on (`basedOn`) and what it left out (`leftOut`).** It is for reflection. It never gives advice and never predicts: *"It says nothing about money, income or financial decisions"*, *"Nothing predicts what will happen"*.
- `meta.mock` is `true` when the reading was made by the stand-in analysis (provider `"sample"`: the website's built-in sample photos, or a server with no hand model). It is `false` when the lines were found in the person's own photos: provider `"gemini"` (with the model's name in `meta.model`) when the language model wrote at least one passage, `"knowledge-base"` when the fixed rules wrote all of it, in which case `meta.note` says why when Gemini was expected to write it. When it is `true` the pages label the reading **"Sample reading"** and draw the lines on a sketch of the hand unless the photos are the built-in sample photos. When it is `false` they draw the lines on the person's own photo.

---

## 7. Chat

```ts
type Conversation = { id: string; readingId: string; profileId: string; title: string; createdAt: string; updatedAt: string; messageCount: number }
type ConversationWithMessages = Conversation & { messages: Message[] }      // messages oldest first

type Message = {
  id: string
  conversationId: string
  role: 'user' | 'assistant'
  text: string
  createdAt: string
  refs?: {                      // which part of the reading the answer leaned on. The page shows these as "Based on" chips.
    featureIds?: ('heart'|'head'|'life'|'fate'|'sun')[]
    side?: 'left' | 'right'
    section?: 'heart'|'head'|'life'|'fate'|'sun'|'summary'|'comparison'|'uncertainty'|'themes'|'shape'
  }
  flags?: {
    disclaimer?: boolean        // this answer carries the traditional / entertainment reminder
    boundary?: 'medical' | 'financial' | 'employment' | 'relationship' | 'lifespan' | 'prediction' | 'not_seen' | 'off_topic'
    switchProfileId?: string    // the question was about someone else: the page offers a "Switch to {name}" button
  }
  source?: 'gemini' | 'knowledge-base'   // assistant messages only. "gemini": the language model wrote the answer and it passed the checks. "knowledge-base": Gemini was expected to answer and did not, so the fixed wording answered (see note). Left out when the model was never involved: a boundary, a greeting, a sample reading, or no Gemini key.
  note?: string                          // why Gemini did not answer, in one sentence ("Gemini's free allowance is used up for now ..."). Left out when there is nothing to say.
}
```

| Request | Notes |
| --- | --- |
| `GET /conversations?readingId=&profileId=` | Both filters optional. Most recently updated first. |
| `POST /readings/{id}/conversations` | No body. Creates an empty conversation titled `"New chat"`. |
| `GET /conversations/{id}` | The conversation with its messages. |
| `POST /conversations/{id}/messages` | Body `{ "text": "..." }`, 1 to 500 characters (otherwise `422 invalid`). Stores the question, asks the model, stores the answer, returns **both**: `{ "user": Message, "assistant": Message }`. |
| `DELETE /conversations/{id}` | Removes the conversation and its messages. Returns a `DeleteSummary`. |

When the first question is sent to a chat titled `"New chat"`, the title becomes that question (cut at 48 characters).

### Importing reading data into the chat

The Chat page's **Import reading data** button (and the dashboard's **Chat about a reading**) does exactly one thing: it
chooses a `readingId`. **Nothing about the reading is sent from the browser.** The findings are stored in your database, and on
every message the server attaches the stored findings and report of that conversation's reading to the model's context.

- With no choice made, the chat uses the **newest reading of the active profile**: the first item of `GET /readings?profileId=`.
- Any reading of any profile the caller owns can be chosen. Choosing a different reading starts a **fresh** conversation: the
  website calls `POST /readings/{id}/conversations` for the chosen reading. It never moves an existing conversation to another
  reading, and `Conversation.readingId` never changes after it is created.
- Because a conversation is tied to one reading, a profile with several readings has no clash: the model sees the findings of
  one reading only. Do not merge or average a profile's readings for the chat.
- A reading id that does not exist, or belongs to someone else, gets `404 not_found` like everywhere else, so an id cannot be
  used to read another person's features.

**The server builds the model's context. The browser sends only the question.** On every message the server loads the
conversation's reading (findings and report), the earlier messages of this conversation, and the matching passages of the
knowledge base. The browser never sends a prompt, a history, a model name or a key.

Rules the chat must keep:

- **One conversation, one reading, one profile.** Only that reading's data goes into the model's context; never another profile's. Switching profile or reading in the website starts a fresh conversation, so context cannot leak.
- If the person asks about **someone else's** hands (another profile name), do not answer from this reading. Reply that they need to switch to that profile's reading, and set `flags.switchProfileId` to that profile's id (only if the caller owns it).
- **Do not claim what was not found.** A question about a line that is `not_visible` or `uncertain` gets a plain answer that it was not clearly seen (`flags.boundary: "not_seen"`), with no tradition-based claims about it.
- **Stay in bounds.** Medical, financial, employment and relationship questions, and questions about how long someone will live, are politely declined and redirected to a suitable professional: set the matching `flags.boundary` (`medical`, `financial`, `employment`, `relationship`, `lifespan`). Unrelated questions get `off_topic`.
- **A reading describes themes. It does not say what will happen.** "Will I be rich?", "What will happen next year?" get `flags.boundary: "prediction"`: the answer says what the tradition links the line with and that a palm does not fix the future. Words that are plainly about a relationship (marry, divorce, soul mate, boyfriend, girlfriend, husband, wife, partner...) always get `relationship`, even when phrased as a prediction: *"Will I get married?"* is a `relationship` question, not a `prediction`.
- The fixed-rule chat in `backend/app/llm/chat.py` and the sample one in `src/api/mock/chat.ts` apply the same rules in the same order, and `backend/tests/test_chat.py` checks 33 questions against them. **The language model is held to the same table**: the server runs these boundary rules first, in plain code, and a question they decline never reaches Gemini. For the rest, Gemini's reply must say what the question was (`intent`); if it names a boundary the rules missed, its words are dropped and the app's own wording for that boundary is shown. Its answer is then checked against the findings (no prediction, advice or health talk, no unseen line described, no contradiction of the findings), and any failure falls back to the fixed-rule answer, so a question always gets an answer.
- **What goes to Gemini with a question:** the findings (words only), the report as the person reads it, the matching knowledge-base passages, and the last six messages of this conversation, with e-mail addresses, links, runs of seven or more digits and the account's profile names removed. Never a photo. A conversation has a limit on Gemini-written answers (40 by default, `GEMINI_CHAT_LIMIT`); after that the fixed wording answers. That count is not part of the account export and is not something a person can read.
- Answers that go into palmistry repeat the traditional / entertainment reminder, with `flags.disclaimer: true`.
- Messages are stored one per record (not in one growing list) so a conversation cannot outgrow its record.

---

## 8. Account data

### `GET /account/export`

Everything the account holds, as one JSON document. The website offers it as a file download (`kiro-data-YYYY-MM-DD.json`).
It contains **no photos**, because none are kept.

```ts
type ExportBundle = {
  exportedAt: string
  profiles: HandProfile[]
  readings: Reading[]
  conversations: ConversationWithMessages[]
}
```

### `DELETE /account/data`

Deletes **all** profiles, readings, conversations and messages of the caller, and every piece of derived data. The account
itself stays, so the person can start again. Returns a `DeleteSummary` of what was removed. For a guest session it clears
the guest data.

### Deleting cascades

| Delete | Also removes |
| --- | --- |
| a profile | its readings, their conversations, all their messages, derived feature data |
| a reading | its conversations, all their messages, derived feature data |
| a conversation | its messages |
| account data | all of the above for every profile |

The counts in `DeleteSummary` are what was actually removed. The website quotes them back to the person.

---

## 9. Where the data is kept

The server always works on its own copy in memory. When it has a Firebase service account key (`backend/secrets/firebase-service-account.json`,
see the README), it also keeps every **account** in that project's **Cloud Firestore** database, so an account and everything it owns
are still there after a restart or on another copy of the server. **Guest sessions are never written there**, and **photos are never
written anywhere** (see [Never stored](#never-stored)). The website knows nothing about Firebase and needs no key for it.

| Document | Plain fields (easy to read in the Firebase console) | Also |
| --- | --- | --- |
| `users/{userId}` | `email`, `emailLower`, `displayName`, `createdAt`, `modelReplies` (Gemini-written chat answers used) | `salt` and `passwordHash`: the password's scrypt hash, never the password |
| `emails/{sha256 of the lower-cased e-mail}` | `userId`, `email` | so a sign-in needs one read, not a search |
| `sessions/{sha256 of the cookie token}` | `userId`, `expiresAt` (ms) | the token itself is never written; signing out deletes the document |
| `users/{userId}/profiles/{profileId}` | `name`, `createdAt` | `data`: the stored profile as JSON |
| `users/{userId}/readings/{readingId}` | `profileId`, `createdAt` | `data`: the reading as JSON (the two `HandAnalysis` objects, the report, `meta`) |
| `users/{userId}/conversations/{conversationId}` | `readingId`, `profileId`, `title`, `updatedAt`, `messageCount` | `data`: the conversation as JSON |
| `users/{userId}/conversations/{conversationId}/messages/{messageId}` | `role`, `createdAt` | `data`: the message as JSON |

`data` holds the whole object in the same shape as this contract, because a reading holds lists of points and Firestore cannot
store a list inside a list. Each message is a document of its own, so no chat can grow past Firestore's limit of 1 MiB per document.

- **When it is written.** After every request that can change something has been answered (the reading stream once it has finished),
  the server writes the documents that changed and deletes the ones that went, one batch per account. Deleting follows the table in
  [Deleting cascades](#deleting-cascades): a profile takes its readings, their conversations and their messages out of the database too.
- **When it is read.** An account is read the first time it is wanted after the server starts: at sign-in, or when a browser comes
  back with a sign-in cookie, and then its profiles, readings, conversations and messages once.
- **When the database cannot be reached.** `POST /auth/signup` and `POST /auth/signin` answer `503` with code `processing_failed` and
  the message *"The account database could not be reached just now. Please try again in a moment."*, and no half-made account is left.
  So does a request for an account that has not been read since the server started. Everything else is answered from memory as
  usual, and what could not be saved is tried again after the next request.
- **Who can reach it.** Only the server, signed in as the project's service account. The database is made in *production mode*, so
  its security rules refuse every browser.

`STORAGE` in `backend/.env` chooses `auto` (the database whenever the key is there, the default), `memory` or `firestore` (refuse to
start without a usable key). Firebase Authentication is not used: the server keeps its own accounts (scrypt-hashed passwords and
`HttpOnly` session cookies, as in [Sessions](#sessions)), which is what lets guest mode and accounts share one set of endpoints. If the
Firebase JavaScript SDK is wanted in the browser later (for example, Google sign-in), one endpoint, `POST /auth/session` taking
`{ "idToken": "..." }` and setting the same cookie, would be enough. Nothing else in this contract would change.

## 10. Hosting the website and the API

**Layout A, one service (matches the project plan, and works with the cookie sessions as they are).** FastAPI serves the
compiled website and the API from one address.

1. Build with the sample backend switched off: **`npm run build:server`**. It builds in the mode `server`, and [`vite.config.ts`](../vite.config.ts) sets `VITE_USE_MOCK=false` and an empty `VITE_API_URL` for that mode (the site then calls `/v1` on its own address, and a line in `.env.local` cannot change that), and it writes to **`dist-server/`**, so it never overwrites the sample-data build in `dist/` that `npm run build` makes. (A build made this way contains none of the sample-backend code. `dist-server/build-info.json` says which kind a folder holds: `{ "mock": false, "mode": "server", ... }`.)
2. Serve the files in `dist-server/` (`backend/` does: set `SITE_DIR` to serve another folder), with `/assets/*` cached for a long time (the file names change when the content does) and everything else `no-cache`.
3. The website uses client-side routes (`/signin`, `/start`, `/app/new`, `/app/readings/rdg_9`, and so on). **Every `GET` that is not under `/v1` and not a file in the build folder must answer with `index.html`** and status 200, otherwise a refresh on those pages shows "not found". A missing file under `/assets/` is a plain `404`, never the page: a script request answered with HTML is a confusing failure.
4. If you set a Content-Security-Policy, the site needs `img-src 'self' data: blob:` (processing previews are data URLs, photos are shown from `blob:` URLs), `style-src 'self' 'unsafe-inline'`, and `script-src 'self'`. Nothing is loaded from other sites: the fonts are bundled. **`script-src 'self'` forbids inline scripts**, so `index.html` has none (the saved light or dark theme is applied by `public/theme-init.js` before the first paint), and a test fails if one is added. `backend/` sends exactly this policy on the website and none on `/v1`.
5. Serve scripts as `text/javascript` and styles as `text/css`, and **set them yourself**. Python asks the operating system for the type of a file, and on Windows a registry entry left behind by another program can make that `text/plain`, after which the browser refuses to run the script and the page stays blank. `backend/` has its own table for what the build produces, with a test.
6. Do not let a compression or buffering layer hold back `POST /v1/readings`; it must reach the browser as it is produced. (`backend/` is plain ASGI middleware around the stream for this reason: nothing in it buffers a response.)
7. On Cloud Run: response streaming works, but set the request timeout above the longest reading (a few minutes is plenty), and keep temporary files small, because Cloud Run's file system is held in memory.

**Layout B, the site on a static host and the API somewhere else.** This keeps the 3D landing page from ever waking a
sleeping server, which matters on hosts that spin down when idle. It needs one of the arrangements under
[Sessions](#sessions) (a shared domain, or a proxy) for the cookie to work. The website's first request on every page load
is `GET /v1/session`, so a sleeping API starts waking as soon as someone opens the landing page, with no separate
"warm-up" call needed. Memory-light hosts also benefit from what the website already does: it shrinks photos to 1600 px
before upload, and a reading sends both photos in one request, so process one hand at a time on the server.
