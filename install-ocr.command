#!/bin/bash
# Optional: adds text recognition (OCR) for scanned pages.
cd "$(dirname "$0")" || exit 1

fail() {
  echo ""
  echo "$1"
  read -r -p "Press Return to close this window." _
  exit 1
}

[ -x .venv/bin/python ] || fail "Run start.command first. It sets up the packages OCR needs."
if ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info < (3, 13) else 1)'; then
  fail "OCR does not work with Python 3.13 or newer yet. Install Python 3.12, delete the .venv folder, and start again."
fi

OCR_HASH=$(shasum -a 256 requirements-ocr.txt | cut -d' ' -f1)
if [ "$(cat .venv/.ocr-hash 2>/dev/null)" = "$OCR_HASH" ]; then
  echo "OCR is already installed."
  read -r -p "Press Return to close this window." _
  exit 0
fi

echo "Installing OCR. This is a large download and needs an internet connection."
.venv/bin/python -m pip install -q --require-hashes -r requirements-ocr.txt \
  || fail "Installing OCR failed. Check your internet connection and run this file again."
echo "$OCR_HASH" > .venv/.ocr-hash

echo ""
echo "OCR is installed. Quit PDF Studio with stop.command, then start it again."
read -r -p "Press Return to close this window." _
