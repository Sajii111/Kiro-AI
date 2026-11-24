# Kiro AI

*Upload both palms and meet a calm, traditional reading you can actually talk to.*

This is the website for the Palmistry AI project (NIBM Digital Image Processing, ICA 01): a landing page, accounts and
guest mode, hand profiles, the photo upload and processing flow, the annotated analysis, the report with a left-versus-right
comparison, a chat about the reading, history, and settings with data controls.

It runs in two ways. On its own, a built-in **sample backend** answers every request, so every screen works with no server
(`npm run dev`). Or together with the **real FastAPI backend**, which lives in [`backend/`](backend/README.md) in this same
folder: double-click `run.bat` and the website and the server start together from one address. Both speak the contract in
[`docs/API_CONTRACT.md`](docs/API_CONTRACT.md), so no screen changes between them.

> **What the sample backend is, and is not.** It lets you see and test every screen. It does *not* do real image
> processing: the photo checks are rough, and the lines it draws are generated to fit the built-in sample photos. Every
> reading made this way is labelled *Sample reading*. The real analysis belongs to the backend, and it arrives in phases.
> Today, with the hand model installed (`run.bat models`), the server finds the hand in each photo, runs the real photo
> checks, makes the six processing pictures with real OpenCV and traces the five lines in the photo itself. The words of the
> report and the chat are written by Google's Gemini when a key is set (see [Gemini, the language model](#gemini-the-language-model)),
> and otherwise by fixed rules from the same knowledge base. The built-in sample photos (drawings) still get a labelled
> stand-in (see [`backend/README.md`](backend/README.md)).

---

## Run it

You need [Node.js](https://nodejs.org) 20.19 or newer (22 LTS is a good choice).

```bash
npm install
npm run dev          # opens on http://localhost:5173
```

| Command | What it does |
| --- | --- |
| `npm run dev` | Starts the site for development, with instant reload |
| `npm run build` | Checks the types, then builds the site into `dist/` (with the sample backend inside) |
| `npm run build:server` | Builds the site for the real server into `dist-server/` (no sample backend inside). `run.bat` does this for you |
| `npm run preview` | Serves the built `dist/` locally, to try the real build |
| `npm run lint` | Runs the linter (no output means no problems) |

### Run it with the real server (Windows)

You need **Python 3.12 or newer** from [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH*). If you start from **the zip** that was handed in, that is all: the zip carries the built website and the hand model, so **Node.js is not needed** (`run.bat` can tell, by a fingerprint of the sources, that the website in the zip is the one they make). If you start from a Git clone, you also need Node (above), because the website is built on the first run.

1. Double-click **`run.bat`**. The first time, it makes a private Python environment in `backend\.venv`, installs the packages (a few minutes, and it needs the internet), builds the website for the server and opens <http://127.0.0.1:8000>. Later runs start in seconds. Nothing is installed outside this folder.
2. Leave its window open while you use the app. Press `Ctrl+C` in it to stop.
3. To check the server from the outside, start it, then run **`run.bat smoke`** in a second window (or `python scripts\smoke.py`). It plays two browsers, prints one `PASS` or `FAIL` line per check, and ends with `RESULT: PASS`.

`run.bat --port 8100` uses another port, `--no-browser` does not open the browser, `--rebuild` builds the website again. Reading real photos needs one more download, the MediaPipe hand model (about 7 MB): run **`run.bat models`** once and it is saved in `backend\models\`. Without it the server still works, but every reading is a labelled sample, and the server window says so when it starts. **`run.bat sheet`** draws what the analysis finds in the photos in `..\test-photos` (the pictures go to `..\debug`; they contain your photos, so they stay outside the project and are never committed), and **`run.bat smoke --expect-real`** fails unless the server really reads photos. The MediaPipe library reports its own version and the operating system to Google when it first runs; no photo goes with that (details in [`backend/README.md`](backend/README.md#privacy-what-mediapipe-sends-to-google)). Accounts live in the server's memory, and are gone when it stops, until you give it a Firebase key: see [Accounts in an online database](#accounts-in-an-online-database-firebase). Guest sessions are meant to be temporary anyway.

### Before a demonstration, and handing in

Three commands (Windows) check the whole project and make what is handed in. Each prints one `PASS`, `WARN` or `FAIL` line per check
and ends with `RESULT: PASS` or `RESULT: FAIL`.

| Command | What it does |
| --- | --- |
| `run.bat preflight` | Everything that has to be true before a demonstration, in one go: the Python version, every package at the version the tests used, one OpenCV, the hand model loaded for real, the settings (the Gemini key is only ever reported as *present* or *missing*) and where accounts are kept (the Firebase key is checked, never shown), the built website against its sources, no key or private file written anywhere in the project (and, when the folder has a Git history, in no old commit either), what Git ignores, exact package versions, forgotten packages, and your photos in `..\test-photos` (the brief asks for three pairs and a photo that should fail). With a key it makes one small request to Gemini. Then it **starts the app by itself** on a spare port, runs the whole smoke check against it, and tries five things that go wrong: a page closed in the middle of a reading (nothing may be saved), two browsers reading at once, two tabs of one session (both readings are kept, and a session ended in one tab stops the reading in the other with nothing saved), your bad photos, and Google unreachable (the reading must still finish, with the fixed wording and a plain note). Last, a **privacy audit**: the app ran with its own empty temporary folder and its log in a file, and after your photos went through it, no picture, file name, name or e-mail address may be found in the log, in that folder or in a new file in the project. A text copy is saved as `..\debug\preflight.txt`. It describes your photos in words, so it is never committed. |
| `run.bat package` | Makes the zip to hand in, in `..\submission`. It builds the website first if that is out of date, then **refuses to make a zip** if a file looks like it holds a key, if a private file (`backend\.env`, `backend\secrets\*`) would be packed, if any picture is in it other than the project's own drawn sample hands (a photo of a palm, or anything with camera data, may never travel), if the website is not the one the sources make, or if the hand model is damaged. Afterwards it opens the finished zip, unpacks it into a temporary folder and checks it a second time. It also names any line in the README or the docs still marked `[AUTHOR TO ...]`, for you to write before you hand it in (a warning, not a refusal). `--dry-run` only checks; `--no-model` leaves the hand model out. |
| `run.bat fresh` | Starts the newest zip the way a lecturer will: in another folder, with Node.js and the Gemini key taken out of the environment, and none of your files. It does the first run (makes the private environment, installs every package from the internet, uses the website in the zip), then runs that copy's own `preflight` with your photos, then deletes the copy. It takes a few minutes and about 700 MB of disk. `--keep` keeps the copy; `--quick` stops after the first run. |

The zip holds one folder, `kiro-ai`: the source, the tests, the docs, `run.bat`, the built website (`dist-server`) and the MediaPipe hand model
(Google's, [Apache 2.0](docs/licenses/Apache-2.0.txt); its notice is in `backend\models\NOTICE.txt`). It never holds `backend\.env`, the packages,
your photos, or anything in `..\debug`. These checks look for the shapes that real keys have, so they lower the risk of a slip; they cannot
prove there is no secret anywhere.

### Screenshots for the report

**`run.bat evidence`** takes the screenshots that the report and the viva need, with a real browser going through the real app the
way a person would. It starts its own copy of the app (your own window is not touched) and uses the Microsoft Edge that every Windows
computer has (or Chrome), out of sight. For every pair of photos in `..\test-photos` it saves, numbered in order: the upload page, both
photos with their checks, the reading being made, every processing step as a before/after picture of each hand, the lines marked on
each palm, the reading page, the report by theme and by line, what was unclear, how the reading was made, and the chat (five questions
it answers and two it must decline). Then come the photos meant to fail, and three wrong files it makes on the spot: a text file named
`.jpg`, an iPhone HEIC photo and a file over 15 MB. The pictures go to `..\evidence`, outside the project, with `index.html`, which says
what each one shows. **They show real palms, so never commit them.** The first run installs Playwright, the tool that drives the
browser (about 40 MB, listed in `backend\requirements-evidence.txt`). A run takes a few minutes and asks Gemini to write six to eight
times for each pair of photos. `--light` uses the light theme, which prints better; `--no-gemini` shows the fixed wording; `--show`
lets you watch.

### Gemini, the language model

Gemini reads the palm like a fortune teller: it writes the passages of the report that foretell what the findings promise, and the
chat answers. It needs a key. **Without one everything still works**: the fixed wording from the knowledge base writes the words
(in the same voice), and the reading says so. Set it up before a demonstration,
because the language model and the chatbot are marked.

1. Get the free key at <https://aistudio.google.com/apikey> (a Google account, no card). **Do not turn on billing.**
2. Put it in `backend\.env`, which Git ignores. In Command Prompt run `cd /d E:\Project\kiro-ai\backend`, then `notepad .env` (answer *Yes* to create the file), type `GEMINI_API_KEY=` and paste the key straight after the `=` (no quotes, no spaces), and save. [`backend/.env.example`](backend/.env.example) lists the other settings. Never paste the key anywhere else: not into a chat, a report, a screenshot or a commit. Everything goes through the Gemini API with this one key. Google's "high demand" answer and its free allowances belong to each model separately, so the app does not rely on one model: `GEMINI_MODEL` (the first choice) and `GEMINI_FALLBACK_MODELS` (the ones that take over, by default `gemini-3.1-flash-lite`, `gemini-2.5-flash-lite` and `gemini-2.5-flash`) name the Gemini models that take turns, and the first that can answer does. You need to change nothing.
3. Run **`run.bat gemini`**. It prints the settings (never the key, and the models in the order they are tried), makes one tiny request, writes a report for a made-up pair of hands, asks five questions and three that the app must decline, and says plainly what worked and which Gemini model wrote what. A text copy of everything it prints is saved in `..\debug\check_gemini.txt` (made-up hands only, and never the key). `run.bat gemini --probe` tries each model on its own and says which ones your key can use.
4. Run **`run.bat live test-photos\person1`** to see a report for your own photos: what was found, exactly what Gemini is told, the whole report with each passage marked as written by the app, by Gemini or by the fixed wording, and a text copy saved in `..\debug` (it describes your palms, so it is never committed).
5. With the server running, **`run.bat smoke --expect-gemini`** fails unless Gemini really writes the words.

**What Google receives.** Only the findings, as words from short fixed lists (for example "heart line: long, gentle curve, clear"), and, in the chat, your question and the last few messages with e-mail addresses, links, phone numbers and profile names removed. **Never a photo**, a name or contact details. **On Google's free tier, Google may use what it receives to improve its products, and people may read it.** The app says so on the report, next to the chat box and in Settings. If you would rather nothing leaves the computer, leave the key out.

How the model is made to write about palmistry, what checks every passage, and what happens when Gemini cannot answer are in
[`docs/LLM_DESIGN.md`](docs/LLM_DESIGN.md). The palmistry notes it draws on, and how to check them, are in
[`backend/app/llm/kb/`](backend/app/llm/kb/README.md).

### Accounts in an online database (Firebase)

Without a database, accounts live in the server's memory and are gone when it stops. With **Cloud Firestore**, Google's database in a
Firebase project, an account and everything it owns stay: its hand profiles, every reading (the findings and the report, **never a
photo**) and every chat with its messages. **Guest sessions are never saved**, as the website promises. The password is kept only as
its salted scrypt hash, and a sign-in only as a fingerprint of the cookie, never the cookie itself. It takes about ten minutes, once.

1. At <https://console.firebase.google.com> make a project (Google Analytics is not needed). Then, in the left panel, **Databases &
   Storage > Firestore > Create database**: the Standard edition, a location near you (from Sri Lanka, `asia-south1`, Mumbai; it
   cannot be changed later), and **production mode**, which shuts every browser out (only the server, signed in with the key below,
   can reach it). **Do not turn on billing**: the free tier allows 50,000 reads and 20,000 writes a day, far more than this app uses.
2. **Project settings (the gear) > Service accounts > Generate new private key.** Rename the downloaded file to
   `firebase-service-account.json` and put it in `backend\secrets\`. Git ignores that folder and `run.bat package` refuses to pack it.
   **The file is a password to your database: never paste it into a chat or send it to anyone.**
3. Run **`run.bat firebase`**. It names the project (never the key), writes one test document, reads it back and deletes it, counts
   the accounts, and ends with `RESULT: PASS`. When something fails, it says what to do.
4. Start **`run.bat`** again. Its window now says `Storage: FIRESTORE (Firebase project ...)`, and **Settings** in the app says the
   account is saved in the online database. Sign up, stop the server, start it again: you are still signed in, with everything there.
   The documents appear in the Firebase console under Firestore, one per account, profile, reading, chat and message.

`STORAGE` in `backend\.env` chooses: `auto` (the default: the database whenever the key file is there), `memory`, or `firestore` (the
server refuses to start without a usable key). If you gave the database its own name, add `FIRESTORE_DATABASE=that-name`. The checks
(`preflight`, `fresh`, `evidence`) run their own copy of the app with `STORAGE=memory`, so they never write made-up accounts into your
database, and no automated test can reach it. What each document holds is in
[`docs/API_CONTRACT.md`](docs/API_CONTRACT.md#9-where-the-data-is-kept); how the server keeps the database up to date, and what
happens when it cannot be reached, is in [`backend/README.md`](backend/README.md#where-accounts-are-kept-memory-and-cloud-firestore).

## Try it in two minutes

1. Open the site. A loading screen draws a hand and counts up to 100%, then a film of about seven seconds plays: the hand lights up, a great wheel of the zodiac is drawn around it, and you fly through the wheel past a ringed planet and a turning galaxy, in streaks of stars, to land on the hero hand, so the landing page seems to open out of the film. A small **Skip** button sits at the bottom (Esc does the same) and plays the rest about four times as fast. Then scroll: the landing page is a journey through a night sky and a 3D world. Move the mouse as you go, and see [Things to touch on the landing page](#things-to-touch-on-the-landing-page) and [The opening, the music and moving between pages](#the-opening-the-music-and-moving-between-pages).
2. At the end choose **Begin as a guest**. A guest can do everything, but nothing is saved.
3. Press **Load sample profiles** (the demo gives you two people with readings), or create a profile of your own.
4. Choose **New reading**, then **Use sample palms for both**. Watch the photo checks, then the processing steps: grayscale, Gaussian smoothing, CLAHE contrast, Canny edges. Each one has an original-versus-processed slider.
5. Open the reading. Switch between the photo and the sketch, click a line to see what was found, read the report, and ask the chat a question.
6. Back on the **Dashboard**, press **Chat about a reading**. The chat opens with that reading's saved findings imported; **Import reading data** switches it to any other reading (see the readings rule below).
7. Visit **Settings**: theme, sound, privacy, export, delete everything. At the bottom, **Demo tools** can make the next reading fail or end the guest session on the spot.

The default look is the dark **Night Sky**. The light theme is **Golden Hour**, a dawn version of the same sky. The switch is in the header, and the new theme spreads out from the button like a sunrise (or the lights going down). Browsers without View Transitions get a short fade instead, and with "reduce motion" switched on the theme simply changes. The logo, on every screen, takes you back to the landing page.

## Things to touch on the landing page

The landing page is built around the night sky: a starfield, a galaxy, a zodiac wheel and a ringed planet. Nothing here is needed to use the site, and it never sits on top of text.

| Where | What to do | What happens |
| --- | --- | --- |
| Any open sky, on any screen | Move the mouse | Stars near the pointer brighten and drift away a little, and a short trail of sparkles follows |
| The top of the page | Move the mouse around the hand | A spiral galaxy behind the hand leans towards the pointer, and the stars under it wake up |
| Anywhere in the 3D scene | Move the mouse over the glowing lines | A soft lamp follows the pointer and the lines near it glow |
| The hero hand | Hover one of its five palm lines (on a phone, tap one) | That line lights up and a small label names it and says what tradition links it to ("Heart line · tradition: feelings"). It is the tradition, not a claim about you |
| Any open sky | Click or tap | A shooting star streaks across the sky from where you pointed, with a few sparkles and, if the music is on, one soft note. It never takes a click from text, a button, a card, a palm line, the planet or a zodiac sign, and quick clicks do not pile up |
| "How it works" | Hover a constellation on the wheel round the hand | The sign lights up, light runs along its lines, the wheel pauses, and a label names it ("Capricorn · Dec 22 – Jan 19"). Click it and its stars flare. Scrolling also turns the wheel |
| The very end | Hover the ringed planet, then drag | The label says "Drag to spin". Drag to spin and tilt it, let go mid-flick and it keeps turning and slows down, click it for a nudge, and watch the moon speed up |

- Over text, cards, buttons and the header the scene stays quiet: no labels, no glow, no dragging.
- **On a phone** there is no hover, so these become taps: tap a palm line (its label stays for a couple of seconds), a constellation or the planet, or the open sky to make a wish. Scrolling always still scrolls.
- **With "reduce motion"** the scene is a still picture and nothing reacts: no lit lines, no shooting stars.
- **In Golden Hour** the galaxy and planet are not there (a rising sun takes their place), and the constellations are drawn in amber.
- The twelve signs are stylised decoration, not accurate star charts.
- The scene is kept uncluttered on purpose: the curved ribbons that used to wind around the hand (the tunnel behind it and the scanner's rings) are gone. What is left is the hands themselves, the chat bubbles, the zodiac constellations, the galaxy, the planet and the dust. The two new things to touch (the palm lines and the shooting stars) add nothing to the picture until you use them, and a shooting star lasts about a second.

## The opening, the music and moving between pages

**The opening.** The first time you open the site in a tab, a loading screen draws a hand and counts up to 100% (it follows real loading, and lasts at least about 2.6 seconds). Nothing needs a click. When it reaches 100% the film plays, about seven seconds, as **one camera move through the real 3D scene**:

1. the percentage steps aside and the hand lights up;
2. the loader's drawing melts away. Under it the 3D hero hand has been waiting in exactly the same place, as big as the drawing, with its lines drawn in step with the loading bar, so nobody sees one swapped for the other (this is what makes the hand-over unnoticeable);
3. the camera sets out. A great wheel of the zodiac is drawn around the hand, sign by sign, and the camera flies through it; a ringed planet rises up in the corner (a sun in Golden Hour), the galaxy begins to turn, shooting stars cross the sky and the stars streak past;
4. the camera slows into the hero view, the wheel and planet fade, and the header and headline come in, so the landing page seems to open out of the film.

A small **Skip** button sits at the bottom of the screen, quiet and without a frame until you point at it (pressing Esc does the same). It does not cut anything: it plays the rest of the film about four times as fast, or, if you press it while loading, drops the short hold that lets the drawing finish. A click on the sky does *not* skip. The film is drawn live by the code (not a video file), so it is sharp on any screen and costs nothing to download; its props exist only while it plays. On a phone the camera hardly has to move, so the zodiac wheel stands behind the hand and the planet sits low on the left. It plays once per tab; open `/?intro` to see it again. With "reduce motion" switched on there is no film, only a short fade (the Skip button is still there during loading).

**The music.** It is generated in the browser (no audio files) and is **on by default**. Browsers do not allow any website to make sound until the visitor has clicked, pressed a key or tapped on it (scrolling and moving the mouse do not count), so on a first visit the music starts by itself at your first click, key press or tap, and not before. That is a browser rule that no website can get around. The sound button in the bottom-left corner of the landing page (its bars breathe softly while the music is waiting for that first click), the speaker in the header of the app and of the sign-in page, and the **Ambient sound** switch in Settings turn it off and on, and the choice is remembered on this device. If you turn it off it stays off on later visits. It goes quiet in a background tab and returns when you come back.

**Moving between pages.** Switching pages has a short, calm animation (a little under a second, with no progress bar): the sky-coloured veil fades in with a small orbiting star, the next page is swapped in underneath it (and starts at the top), and the veil lifts as the page eases in. If the next screen's code is still arriving, the veil simply waits for it. A redirect (to the sign-in page, or from the guest set-up step to the app) plays under the same veil, and the page that is leaving is told so, so it cannot send the visitor somewhere else in that moment. Nothing happens for a link to a section of the same page, and with "reduce motion" the page just changes.

## Sample backend or real backend

Everything is controlled by environment variables. Copy [`.env.example`](.env.example) to `.env.local` and change what you need.

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_USE_MOCK` | `true` | `true` = the sample backend. `false` = call the real backend. |
| `VITE_API_URL` | *(empty)* | Where the backend is. Empty means "the same address as this site". |
| `DEV_API_TARGET` | `http://127.0.0.1:8000` | Development only. Where Vite forwards `/v1` calls when `VITE_API_URL` is empty. |
| `VITE_GUEST_SESSION_MINUTES` | `120` | How long a sample guest session lasts. Set `1` to show expiry quickly. |

**To use the real backend on your own computer:** double-click `run.bat` (see above). It builds the site with
`npm run build:server`, which switches `VITE_USE_MOCK` off by itself (it is set in [`vite.config.ts`](vite.config.ts), so a line in `.env.local` cannot undo it), and the
server hands that site out from the same address as the API, so there is nothing to set up for CORS or cookies.
If you would rather keep editing screens with instant reload, run `run.bat --no-browser`, put `VITE_USE_MOCK=false` in
`.env.local`, and run `npm run dev`: Vite then passes every `/v1` call on to the server.

**Before deploying for real:** use `npm run build:server`. The plain `npm run build` still has the sample backend inside, which
is what you want for a static demo that needs no server, and it writes to a different folder (`dist/`), so the two never get mixed
up (`dist-server/build-info.json` says which kind a folder holds). How to host the site and the API (and the one
cookie trap to avoid) is in [section 10 of the contract](docs/API_CONTRACT.md#10-hosting-the-website-and-the-api).
The [`Dockerfile`](Dockerfile) builds both into one image for a hosting service. It keeps accounts in your Firebase database
and needs the key in a setting called `FIREBASE_KEY_JSON` on the host (the notes at the top of the Dockerfile list every setting).

Where the sample data lives: a guest session is kept in the tab (`sessionStorage`) and disappears when it closes; a signed-in
sample account is kept in this browser's `localStorage`. No password is stored in plain text, and no real account is created anywhere.

## How the code is organised

```
src/
  brand.ts            The product name. Change it here and everything follows (header, title, footer)
  config.ts           The environment variables above, in one place
  api/
    types.ts          THE CONTRACT: every shape the backend returns
    index.ts          Picks the sample backend or the real one
    http.ts           The real backend: every endpoint call, in one file
    sse.ts            Reads the live "processing steps" stream from the backend
    errors.ts         One error type, with a plain sentence for the person
    mock/             The sample backend (accounts, profiles, readings, chat, delete cascades)
  state/              Session (guest / signed in), the active profile, theme, and the photos held in memory
  landing/            The cinematic landing page and its 3D scene: hand, galaxy, zodiac wheel, planet, shooting stars (loaded only on that page).
                      scene/film.ts is the opening film's timeline and camera path, scene/FilmSet.tsx its props
  pages/              Sign in, create account, start as guest
  app/                The app screens: dashboard, new reading, processing, reading, history, settings
    new/              Photo slots, photo checks, the processing stepper and the before/after slider
    reading/          The annotated hand, line table, report and chat
  components/         Shared pieces: buttons, dialogs, the hand drawings, the starry sky and sparkle trail, menus, toasts,
                      the opening loader and film (IntroGate) and the page-change veil (RouteStage, TransitionMark)
  lib/                Small helpers: photo preparation, validation rules, formatting, the generated music (ambient),
                      the intro's star streaks (warp) and the page-change signals (veil)
backend/              The FastAPI server (Python): the API under /v1, photo checks, the OpenCV processing steps, the line finder,
                      guest and account sessions, accounts kept in Cloud Firestore, the report and chat (the knowledge base,
                      Gemini and its safety checks). Has its own README, tests and requirements
scripts/
  serve.py            What run.bat runs: installs and builds what is missing, starts the server, opens the browser
  smoke.py            Checks a running server from the outside (run.bat smoke)
  fetch_models.py     Downloads the MediaPipe hand model into backend/models (run.bat models)
  contact_sheet.py    Draws what the analysis finds in your own test photos (run.bat sheet)
  check_gemini.py     Tests the Gemini key and setup with made-up hands (run.bat gemini)
  check_firebase.py   Tests the Firebase key and the online database with one test document (run.bat firebase)
  live_report.py      Writes a report for your own photos, labelled passage by passage (run.bat live)
  preflight.py        The one check before a demonstration: computer, project, Google, the running app, a privacy audit (run.bat preflight)
  repo_checks.py      Keys left in files, what Git ignores, exact package versions, forgotten packages (part of preflight and package)
  package.py          Makes the zip to hand in, and refuses a key, a private file or a photo (run.bat package)
  fresh_copy.py       Starts that zip in another folder with no Node.js and no key, like a lecturer (run.bat fresh)
  capture_evidence.py The screenshots for the report, taken by a real browser going through the app (run.bat evidence)
run.bat               Double-click to start everything (Windows)
docs/
  API_CONTRACT.md     The agreement between the website and the backend
  LLM_DESIGN.md       How the language model is used: knowledge base, prompts, checks, privacy, limits
```

Built with React 19, TypeScript, Vite, Tailwind CSS 4, GSAP and Lenis for motion, and React Three Fiber for the 3D landing
scene (react-router for the pages). Fonts (Fraunces and DM Sans) are bundled, not loaded from Google.

**Motion rule:** the landing page is cinematic; the app screens are calm and readable (they get the starry sky and the
sparkle trail, and nothing else moves; changing screen is one short veil). With "reduce motion" switched on in the operating
system, the 3D scene holds still, the opening film is a short fade, the page-change veil is off, the stars stop twinkling, the
sparkle trail and the theme animation are off, smooth scrolling and magnetic buttons are off, and chat answers appear whole
instead of being typed out.

## Rules the screens keep

These come straight from the project plan and are built into how the site behaves, not just what it says.

- **Photos are never stored.** They are read in the browser, shrunk, sent for analysis, and then forgotten. They live only in the open tab, are thrown away when the session ends, on sign-out and on "delete everything", and a reload clears them. What is kept is only the findings, the report and the chat. A saved reading redraws a sketch from the saved outline.
- **One account, many hand profiles.** A reading belongs to one profile; a chat belongs to one reading. Switching profile or reading starts a fresh chat, so context cannot leak. If you ask about someone else's hands, the chat asks you to switch. Each hand profile is drawn as its own little planet (18 different ones: six colours, three shapes), so profiles can be told apart at a glance and are never confused with the account icon or the Dashboard icon. Two profiles in one account never share a planet.
- **Several readings per profile, exactly one per chat.** A new reading is *added* to the profile's history rather than replacing the last one, so a poor photo can never destroy a good reading and two readings can be compared. This does not cause a clash in the chat, because a chat is tied to one reading: by default the profile's newest, and **Import reading data** on the Chat page picks any reading of any profile. Choosing a different reading starts a fresh chat. (To keep a single reading per profile instead, delete the old one from History.)
- **A reading can have a name.** A box on the New reading screen ("Name this reading (optional)") lets you call it something like "Before my trip"; without one, a reading goes by whose it is and its date. The name shows in History, the Dashboard, the Chat page and as the title of the reading, and the **Rename** button on the reading page changes or clears it at any time, so a typo never means doing the photos again. It is kept as simple as a profile name (up to 40 characters; letters, numbers, spaces and a few marks; emails, links and phone numbers are refused), and it is never sent to Gemini.
- **Guest mode is the full workflow, but temporary.** It is never listed as saved history. A guest who later signs up is *offered* an import with exact counts, and nothing moves unless they say yes.
- **Deleting cascades, and says what went.** Profile → readings → chats → messages → derived data. The confirmation names the counts first.
- **No guessing.** Each line is *detected*, *uncertain* or *not visible*, drawn in three different ways (not by colour alone). A line that was not seen is never described. What was seen is kept apart from what the tradition says.
- **A fortune teller's voice, honestly framed, in plain words.** Reports and chat talk straight, in everyday words and short sentences, and foretell with confidence about love, work, prosperity, creativity, journeys and change, in soft time ("soon", "in time"), and say in one line that palmistry is an old art and not a science. They never give an age, a date or an amount, never speak of health, children or how long anyone will live, and decline medical, financial, job-decision and relationship-advice questions.
- **Consent.** A profile for someone else needs a tick to confirm they agreed. Profile names stay simple (a first name or nickname; emails and phone numbers are refused).
- **No secrets in the browser.** The site holds no API keys. Sessions are an httpOnly cookie set by the server, and the server checks ownership of every profile, reading and chat.

## Where the assessment checks show up

How to see each test-plan case with the sample backend:

| Test | How to see it |
| --- | --- |
| A valid pair of palms | New reading → **Use sample palms for both** |
| One palm blocks the reading | Replace one hand with **Try a sample → A blurry palm**, **A very small photo** or **Not a palm**. It shows what failed and how to retake it, and **Start reading** stays off |
| A corrupt file is refused | Choose a text file renamed to `.jpg`. HEIC and files over 15 MB get their own plain explanations |
| Blurred, dark or cropped photos warn | **A palm in dim light** and **A cropped palm** warn but allow the reading, which then marks lines *uncertain* |
| Uncertain and not-visible lines are not claimed | Reading → the annotated hand (dashed = uncertain, dotted box = not visible), the line table, and the report, where unseen lines carry no tradition text |
| A reading can be named and renamed | New reading → type a name in **Name this reading (optional)** (try an email address or 41 letters: it says what is wrong and **Start reading** stays off). The name titles the reading and shows in History, the Dashboard and the Chat page. **Rename** on the reading page changes it, and saving it empty goes back to the date |
| Follow-up chat uses the reading | Ask "Which line was unclear?" or "How do my hands differ?"; answers name the lines and sides they lean on |
| The language model is held to rules | With a Gemini key: ask "Will I be rich?" or "Should I change jobs?" and the app declines in its own words; ask what your heart line means and the answer is labelled *Written by Gemini from your findings and the knowledge base, and checked*. **How this reading was made**, the fold-out at the end of the report, names the writer and says how many passages fell back to the fixed wording and why |
| Switching profile isolates the chat | Open a reading, switch profile or reading: a fresh chat starts. Ask about the other person and it asks you to switch |
| Delete cascades | Dashboard → delete a profile; History → delete a reading or chat; Settings → delete everything |
| A guest session is not saved history | Guest → History is headed "This session". **Settings → Demo tools → End the guest session now** shows the "nothing was saved" notice |
| A low-quality / failed run | **Settings → Demo tools → Make the next reading fail**, then run a reading |

Suggested demo order: landing → sign in with two or more profiles → upload both palms → validation and the processing
steps with before/after → annotations including uncertain and not-visible lines → report and comparison → a few chat turns →
switch profile → history and delete → one low-quality case.

## Checks that were run

- **Type-check and lint:** `npm run build` and `npm run lint` pass with no warnings (run again on 19 November 2026: no warnings or errors in 130 files).
- **About the next three bullets.** The browser tests, the real-backend connection and the accessibility audit describe checks made while the website was being built, and so do the remarks on the 3D scene and on browsers further down. **Their test files are not in this folder**, so they cannot be re-run from it and were not re-run for this submission. What can be re-run from this folder is the line above and everything under *Backend* below.
- **Browser tests:** about 545 automated checks (13 of them on the finished production build) drive the screens in a real browser, in light and dark themes, on a wide screen and a phone, with reduced motion, and with the keyboard only. They cover sign-in and guest flows, profiles, the upload and processing flow, the reading, chat, history, settings and the delete cascades. Four suites cover the newest work: one for the animated theme switch, the logo link, the planet profile icons (no two profiles alike), the Dashboard-to-Chat import and the several-readings rule; one for the 3D night sky (hover a constellation, drag and flick the planet, taps on a phone, reduced motion, and the scene staying quiet over text and buttons); one for the new things to touch (the five palm lines lighting up with their label on hover and on a tap, and the shooting-star wishes: that they fly from the point you clicked, that a click on text, a button, a card, a palm line, the planet or a zodiac sign never makes one, that quick clicks do not pile up, that they work on a phone, and that reduced motion has none); and one for the opening and the page changes (a loader whose only button is the small Skip, the film that starts by itself and ends on the ordinary hero view, Skip and Esc playing the rest about four times as fast while a click on the sky does not skip, the scene left exactly as it was before once the film is over, music that waits for the first click and then plays, can be muted and stays muted, reduced motion, the veil between pages including Back and forward, redirects and ending a session, and a scene free of stray ribbons).
- **Real-backend connection:** the production build made with `VITE_USE_MOCK=false` was tested against a pretend server written to the contract (42 checks): the exact requests sent, the live progress stream (including `\r\n` line ends and chunks cut at every byte), failed and cancelled readings, an expired session, and a server that cannot be reached.
- **Accessibility:** an automated axe-core audit of 54 screen states finds no violations. Text contrast was measured in both themes (AA): 874 pieces of text on the landing page, on a wide screen and a phone, over the moving 3D scene, the galaxy, the constellations and the planet. The small Skip button on the loading screen was measured on its own, because it fades in after the audits run: its word reads at 7.8:1 in Night Sky and 5.7:1 in Golden Hour (4.5:1 is the minimum), on a wide screen and a phone, and it is 44 px tall to tap. The focus ring is at least 3:1 everywhere, every control works with the keyboard, dialogs trap and return focus, and the processing steps and chat replies are announced to screen readers. Automated checks cannot catch everything, so a pass with a real screen reader is still worth doing.
- **Backend:** 1314 automated tests (`backend/tests`) cover every endpoint, the error format, guest and account sessions, the guest-to-account import, the photo checks, the reading stream (including failure, cancelling and a guest session ending mid-reading), what happens while a slow answer is on its way (a guest session ending, or a profile or chat deleted in another tab, in the middle of a reading or a chat answer: nothing is saved, and the error says so; two tabs of one session reading and asking at the same moment), the chat rules, serving the built site, the hand-model downloader, and that one account never sees another's data. Accounts in the online database are tested against a stand-in for Firestore: everything an account owns is there after a restart, deletes really delete, a guest, a photo, a password and a cookie are never written, and a database that is down costs an error message, never a half-made account. The language-model part is tested against a fake Gemini that is made to behave well and badly, and no test can reach Google: the knowledge base, the retrieval, the safety checks (a date or an age, advice, health, money, misfortune, a claim of proof, invented marks, an unseen line, a contradiction of the findings), the Gemini models taking turns, the fallback when every one of them fails or runs out, the limits, and that no photo, name or contact detail is ever sent. They also cover the real analysis: hands drawn with creases at known places (turned, mirrored, shrunk, dimmed, squeezed, blurred, or with no lines at all) must give lines that lie on the drawn creases, and nothing that was not drawn. The checking scripts are tested too (the preflight, with drills that are made to fail on purpose to show they can; the packaging, fresh-copy and screenshot scripts; the scan for keys, including old Git commits; and `run.bat` itself). A smoke check (`run.bat smoke`, 17 checks) tests a running server from the outside, including a real reading of your own photos when they are in `..\test-photos`. The whole flow was also clicked through in a real browser against the real server: guest start, profile, photo checks, the ten live processing steps with the before/after sliders, the report by theme and by line, chat, sign-up with the guest import offer, sign-in and sign-out, a reload on a deep link, and a guest session ending (with its notice). `run.bat evidence` repeats the guest part of that walk, from the upload to the chat, on any computer, and keeps the screenshots.
- **On the author's Windows computer (21 November 2026):** `run.bat preflight` passed 23 checks with none failed, including a real reading of the author's photos written by Gemini, the five failure drills and the privacy audit. `run.bat fresh`, which unpacks the zip elsewhere with no Node.js and no key, passed 21 with the 2 expected warnings (no key, so no Gemini). `run.bat evidence` took 107 screenshots and missed none: three consenting pairs, two poor photos and three wrong files. `run.bat live` had Gemini write all 17 interpretive passages of a real report, after one repeat because Google was busy. The same morning `run.bat gemini` met Google's "high demand" error throughout and fell back to the fixed wording, as designed.
- **Production build:** the 3D code (about 260 kB compressed) is a separate chunk that only the landing page loads. The app screens never download it.

## Notes and known limits

- **Browser console:** the landing page may log a harmless `THREE.Clock` deprecation notice, from the 3D library. It does not affect anything.
- **The 3D night sky asks a lot of a graphics chip.** The galaxy is several thousand stars and the planet is drawn by a small shader. Recent laptops and phones should cope, and the operating system's "reduce motion" setting turns the scene into a still picture. The tests ran it on a software renderer (no graphics chip), which is slow but shows the same picture, so how smooth it feels on your own computer is still worth a look. The opening film is the same live scene, so it is only as smooth as the scene is; that is one more reason for the Skip button.
- **The sample photos are drawings.** The website marks them as samples, and the server gives them a labelled sample reading. Photos of real hands get the real analysis. The limits of the photo checks and of the line finder were set on a small number of real photos and many drawn hands, so they are starting points that more photos will move.
- **Palmistry is an old art, not a science.** The reading speaks like a fortune teller, and the app says plainly, wherever it shows words, that it is a story about who you may become and not a promise. It never gives an age, a date or an amount, never speaks of health, children or how long anyone will live, and declines questions about medical matters, investing, job decisions and advice about other people. It makes no claim that it is accurate. The project has not measured accuracy, and there is nothing to measure it against.
- **Gemini has been tried with a real key, on one computer, a few times.** On 19 November 2026, with `gemini-3.5-flash-lite` on the free tier, `run.bat gemini` passed (all 20 report passages for the made-up hands passed the safety checks; Gemini wrote 4 of the 5 chat answers, and the fifth fell back to the knowledge base) and `run.bat smoke --expect-gemini` passed 17 of 17 checks with the report and a chat answer written by Gemini. One `run.bat live` report got Google's "high demand" error and fell back to the fixed wording, as designed. On 23 November 2026 the readings stopped coming from Gemini again: the key and the model were accepted, but `gemini-3.5-flash-lite` answered "high demand" for the report and the chat gave up. The request is not too big for the free tier (on 21 November the same key and model wrote a 17-passage report in 14.8 s, 80 seconds after another run of the check had been told "high demand" for its report); Google was busy. A later log showed `gemini-3.1-flash-lite` busy at the same moment and `gemini-2.5-flash-lite` answered as not found for that key, and the app gave up after three rounds, about twenty seconds in all. The app now asks several Gemini models on the same key in turn (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, then the two Gemma 4 models, which the same API serves, so they may answer while the Gemini ones are busy; a model that is busy rests for a few seconds), asks Google once which models the key may use (it leaves out the ones that are not offered and adds up to three more Flash models), asks a model that takes no JSON schema again in plain text, and repeats a report's request up to eight times (after 4, 8, 12, 16 and then 20 seconds, all inside 150 seconds) before it falls back to the fixed wording. **That change has been tested against a fake model only** (the development environment cannot reach Google), and whether the Gemma 4 models accept the request, and how much free allowance they have, is not known from here: run `run.bat gemini --probe` on your own computer to see which models your key can use. Everything else is tested against a fake model. Gemini's wording can differ from run to run, and the safety checks are heuristic: they are plain word and pattern rules, which can miss something unusual and sometimes refuse a good passage (that only costs a fall back to the fixed wording). Each passage is labelled by who wrote it.
- **The online database has passed its real check once, on one computer.** On 21 November 2026 `run.bat firebase` passed against a real Cloud Firestore project. Everything else about it is tested against a fake connection and a fake database (including a missing database, a refused key and no network), and "sign up, restart the server, sign in again" has not been written down as passed on the real project yet, so try it once. Signing in after a restart reads the account from the database once, so the first page after a restart can take a second longer.
- **The knowledge base is a curated draft.** Its 68 entries were written in the project's own words from four named sources and have not yet been checked against them by a person. [`backend/app/llm/kb/README.md`](backend/app/llm/kb/README.md) says how, and has a log for the result.
- **The free Gemini tier has limits that change** (requests per minute and per day, and which models are included). They are shown only in Google AI Studio. When the allowance runs out the reading and the chat carry on with the fixed wording and say why.
- **The name "Kiro".** It may clash with other products called Kiro. Check before a public launch. It is one constant in `src/brand.ts`.
- **The sample backend is rough on purpose.** Its photo checks are simple heuristics, and each sample reading varies a little from run to run.
- **Hosting free tiers change.** Re-check Cloud Run and Render terms before launch.

**Browsers:** everything was tested in Chromium (the engine behind Chrome and Edge). Firefox and Safari should work but have not
been tested yet. The app screens do not use WebGL at all. If WebGL is missing, the landing page is written to lose only its 3D
backdrop and keep its text and buttons, but that has only been checked in the code, not in a browser without WebGL.

## Acknowledgements

Kiro AI uses other people's software, models and writing, and an AI helped to build it. This section says what is whose.

### Software and models it uses

Each one is used under its own licence, and none is edited. The licences are what the installed copies say about themselves (the `license` field of each website package, the metadata of each Python package), read on 19 November 2026. Exact versions of everything, including the packages these depend on, are in `package-lock.json` and [`backend/requirements.txt`](backend/requirements.txt).

**The website (runs in the browser)**

| Package | Used for | Licence |
| --- | --- | --- |
| React, React DOM, React Router | the screens, and moving between them | MIT |
| Vite, Tailwind CSS, TypeScript, oxlint | building, styling, type-checking and checking the website's code | MIT (TypeScript: Apache-2.0) |
| three.js, React Three Fiber | the 3D night sky on the landing page | MIT |
| Lenis | smooth scrolling | MIT |
| GSAP, @gsap/react | the landing page's motion | GSAP's own ["no charge" licence](https://gsap.com/standard-license). It is free to use, but it is **not an open-source licence**: read it before this project is published or sold |
| Fraunces, DM Sans (as Fontsource packages) | the two typefaces, bundled with the site | SIL Open Font License 1.1 (© The Fraunces Project Authors, © The DM Sans Project Authors) |

**The server (runs on this computer)**

| Package | Used for | Licence |
| --- | --- | --- |
| FastAPI, Starlette, Uvicorn, Pydantic | the server, and checking what it is sent | MIT (FastAPI, Pydantic), BSD-3-Clause (Starlette, Uvicorn) |
| python-multipart | receiving the uploaded photos | Apache-2.0 |
| NumPy | the arrays and arithmetic under the image work | BSD-3-Clause, with some parts under other permissive licences (0BSD, MIT, Zlib, CC0-1.0) |
| OpenCV (`opencv-contrib-python`) | the processing steps and the line finder | Apache-2.0. The package also contains other libraries under their own licences, listed in the `LICENSE-3RD-PARTY.txt` inside it |
| MediaPipe | runs the hand model | Apache-2.0 |
| google-genai | Google's library for talking to Gemini | Apache-2.0 |
| google-auth, requests, cryptography | signing in to Google Cloud with the Firebase key, and talking to Cloud Firestore (they come with google-genai) | Apache-2.0 (cryptography: Apache-2.0 or BSD-3-Clause) |
| pytest, httpx, ruff | the tests and the code checker (not needed to run the server) | MIT, BSD-3-Clause, MIT |
| Playwright (with greenlet and pyee) | driving the browser for `run.bat evidence` (not needed to run the server or the tests) | Apache-2.0 (greenlet: MIT and PSF-2.0; pyee: MIT) |

The other packages in `backend/requirements.txt` are pieces these depend on (Pillow, matplotlib and others). Each keeps its own licence. They are permissive (MIT, BSD, Apache-2.0, PSF and similar), except `certifi`, which is MPL-2.0 and is used unchanged.

**Two things that are not code**

- **The hand model.** MediaPipe's Hand Landmarker (`hand_landmarker.task`) was made by Google and is under Apache-2.0; the text is in [`docs/licenses/Apache-2.0.txt`](docs/licenses/Apache-2.0.txt). It finds where the hand and its fingers are in a photo, on this computer, and it says nothing about palmistry. `run.bat models` downloads it from Google, and the zip to hand in carries it unchanged with a notice file (`backend\models\NOTICE.txt`). The MediaPipe library tells Google once that it was used (the operating system and the library's version, never a photo): see [what MediaPipe sends to Google](backend/README.md#what-mediapipe-sends-to-google).
- **Gemini.** The interpretive passages of the report and the chat answers are written by Google's Gemini (`gemini-3.5-flash-lite` first, with other Gemini and Gemma 4 models on the same key taking over when it is busy; free tier) through Google's Gemini API, under [Google's terms](https://ai.google.dev/gemini-api/terms). It is sent the findings as words, never a photo or a name: see [Gemini, the language model](#gemini-the-language-model).
- **Cloud Firestore.** With a Firebase key, accounts and their findings, reports and chats are kept in Google's Cloud Firestore, in the person's own Firebase project on the free tier, under [Google's terms](https://firebase.google.com/terms). Never a photo, and never a guest session: see [Accounts in an online database](#accounts-in-an-online-database-firebase).

### Where the palmistry comes from

What the reading and the chat say about palmistry comes from a knowledge base of 68 short entries ([`backend/app/llm/kb/`](backend/app/llm/kb/README.md)). Each entry names the source it was written from:

1. **S1:** Cheiro (Count Louis Hamon), *Palmistry for All*, 1916 (public domain), [Project Gutenberg ebook 20480](https://www.gutenberg.org/ebooks/20480)
2. **S2:** HowStuffWorks, [Palm Reading: A Comprehensive Guide to Unlocking the Secrets of Your Hand](https://science.howstuffworks.com/science-vs-myth/extrasensory-perceptions/palm-reading.htm) (undated)
3. **S3:** Palmistry Path, [Palmistry Hand Shapes: Earth, Air, Fire, and Water Hands](https://palmistry-site.pages.dev/blog/beginner/hand-shapes/), 1 May 2026
4. **S4:** Wikipedia, [Palmistry](https://en.wikipedia.org/wiki/Palmistry)

The entries are in the project's own words, not copied, and are written the way a palm reader speaks. They leave out what the sources say about health, length of life, accidents and dated events. **They were drafted by an AI, and no person has yet checked them against the sources**, so the knowledge base is a curated draft, not a reviewed one. Palmistry is an old art, not a science: S4 notes that it is widely viewed as a pseudoscience.

### Pictures and sound

No photograph of a person is part of this project. The sample palms on the website are drawn by code (`src/lib/demoPalm.ts`), and so are the two sample hands that the backend tests use (`backend/tests/photos.py`). The music is made in the browser by code (`src/lib/ambient.ts`); there are no sound files. Photos of real hands, for testing, stay in `test-photos`, outside this folder, and are never packed, committed or sent to Gemini.

### Help from an AI

This was built with **Claude**, an AI assistant made by Anthropic, in one long working conversation with the author. In plain terms:

- **Written by Claude, then run and checked by the author on their own computer:** the server in `backend/` (the photo checks, the OpenCV processing steps, the line finder, sessions, the report and the chat, and the Gemini connection with its safety checks); the draft of the palmistry knowledge base; every test in `backend/tests`; `run.bat` and everything in `scripts/`; the documents in `docs/` and the READMEs; and the changes to the website that connect it to the server (for example the types and the real-server client in `src/api/`, and the processing, report, chat and settings screens, with the privacy wording on them).
- **Done by the author:** choosing what to build and in what order, supplying the test photos, creating the Gemini key and keeping it private, running the app and every check on their own computer, and deciding what is handed in.
- **[AUTHOR TO COMPLETE before handing in, then delete this line: who made the website in `src/` before the server work began (a person, or an AI tool and which one), including its icons and `public/favicon.svg`, and what you changed yourself.]**

An AI can be wrong, so each check in this README says what was actually run, and the one part that no person has checked yet (the knowledge base) is marked as a draft.
