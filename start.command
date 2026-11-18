#!/bin/bash
# No log and no output on purpose: the server exits when the last page closes.
cd "$(dirname "$0")" || exit 1

is_ours() {
  curl -s -m 2 "http://127.0.0.1:$1/api/identity" 2>/dev/null | grep -q '"pdf-studio"'
}

# Stop our own old build on a port. Other programs are never touched.
stop_ours() {
  curl -s -m 2 -o /dev/null -X POST -H "X-PDF-Studio: 1" "http://127.0.0.1:$1/api/shutdown"
  sleep 1
  if nc -z 127.0.0.1 "$1" 2>/dev/null; then
    PIDS=$(lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null)
    [ -n "$PIDS" ] && kill $PIDS 2>/dev/null
    sleep 1
  fi
}

# Reuse our own port (replacing an old build), or take the first free one.
PORT=""
for p in $(seq 8000 8009); do
  if nc -z 127.0.0.1 "$p" 2>/dev/null; then
    if is_ours "$p"; then
      stop_ours "$p"
      PORT=$p
      break
    fi
  else
    PORT=$p
    break
  fi
done
[ -n "$PORT" ] || exit 1
URL="http://127.0.0.1:$PORT"

# Install required packages only when requirements.txt changes.
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv >/dev/null 2>&1 || exit 1
fi
REQ_HASH=$(shasum -a 256 requirements.txt | cut -d' ' -f1)
if [ "$(cat .venv/.req-hash 2>/dev/null)" != "$REQ_HASH" ]; then
  .venv/bin/python -m pip install -q -r requirements.txt >/dev/null 2>&1 || exit 1
  echo "$REQ_HASH" > .venv/.req-hash
fi
# OCR installs in the background, so the app opens without waiting.
OCR_HASH=$(shasum -a 256 requirements-ocr.txt | cut -d' ' -f1)
if [ "$(cat .venv/.ocr-hash 2>/dev/null)" != "$OCR_HASH" ]; then
  ( .venv/bin/python -m pip install -q -r requirements-ocr.txt >/dev/null 2>&1 \
      && echo "$OCR_HASH" > .venv/.ocr-hash ) >/dev/null 2>&1 &
  disown
fi

nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
  --log-level critical --no-access-log >/dev/null 2>&1 &
disown

for _ in $(seq 1 50); do
  if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
    open "$URL"
    exit 0
  fi
  sleep 0.2
done
exit 1
