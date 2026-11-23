# Kiro AI in one container, for Render or any other Docker host.
# The website and the API are served from ONE address (the same layout as run.bat), so there is no CORS to set up.
#
# Render settings (dashboard: New > Web Service > pick the repo):
#   Language           Docker
#   Instance Type      Free
#   Health Check Path  /v1/health        (Settings, after the service exists)
#   Environment        GEMINI_API_KEY = your key      (optional: without it the fixed wording writes every report)
#                      Never put the key in this file or in the repo.
#
# Things that must stay true:
#   * ONE worker. Accounts and guest sessions live in this process's memory, so a second worker would not see them.
#   * The hand model (about 7.8 MB) is not in Git (.gitignore). The build downloads it. If that download ever fails, put the
#     file in backend/models/ and add   !backend/models/hand_landmarker.task   to .gitignore: it is then used as it is.
#   * The built website (dist-server) is not in Git either. Stage 1 builds it.

# ---------------------------------------------------------------- stage 1: build the website (Node is not kept)
FROM node:22-slim AS site
WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY index.html vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY public ./public
COPY src ./src
# the website that talks to the Python server on its own address (the sample-data build is off in this mode)
RUN npm run build:server


# ---------------------------------------------------------------- stage 2: the server
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

# What OpenCV and MediaPipe need from the operating system and a slim image does not have: OpenGL and EGL/GLES (MediaPipe),
# GLib, and the small X11 libraries the OpenCV wheel links against. (Found with readelf on the installed wheels.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libegl1 libgles2 libglib2.0-0 libsm6 libice6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# packages first, so a change to the code does not install them all again
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# the server's code (backend/tests, .env and secrets never come in: see .dockerignore)
COPY backend/app backend/app

# the hand model: used as it is when it is in the repo, otherwise downloaded now (scripts/fetch_models.py checks the file)
COPY backend/models backend/models
COPY scripts/fetch_models.py scripts/fetch_models.py
RUN python scripts/fetch_models.py

# the website from stage 1, where the server looks for it by default (next to backend/)
COPY --from=site /build/dist-server dist-server

# APP_ENV=production: cookies only over HTTPS (Render serves HTTPS) and no /v1/docs
# ANALYSIS_MODE=real: refuse to start when the hand model is missing, rather than quietly give sample readings
# STORAGE=memory: no Firebase here. Accounts last until the service restarts or sleeps.
ENV APP_ENV=production \
    ANALYSIS_MODE=real \
    STORAGE=memory

RUN useradd --create-home --uid 10001 app
USER app
WORKDIR /app/backend

# Render sets PORT (10000 unless changed). --proxy-headers: the real address and https come from Render's front door.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 5 --no-use-colors"]
