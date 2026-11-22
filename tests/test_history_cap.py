"""Undo copies are dropped from the oldest end once they add up to more than the size cap."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = """
import json, sys
from pathlib import Path
from app import main as m

doc_id = m._create_doc(Path(sys.argv[1]).read_bytes(), "cap.pdf")
for _ in range(8):
    m._mutate(doc_id, lambda doc: None)
path = m.DOCS_DIR / doc_id
meta = m._read_meta(path)
print(json.dumps({"steps": meta["history"] - meta["floor"], "bytes": m._history_bytes(path)}))
"""


def test_old_copies_are_dropped_past_the_cap(tmp_path: Path):
    pdf = tmp_path / "cap.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "size me", fontsize=12)
    doc.save(pdf)
    doc.close()
    size = pdf.stat().st_size
    cap = size * 3 + 10  # room for three copies, not eight

    env = dict(os.environ, PDF_STUDIO_DATA=str(tmp_path / "data"), PDF_STUDIO_NO_WATCHDOG="1",
               PDF_STUDIO_HISTORY_BYTES=str(cap))
    out = subprocess.run([sys.executable, "-c", SCRIPT, str(pdf)], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert 1 <= result["steps"] <= 3
    assert result["bytes"] <= cap
