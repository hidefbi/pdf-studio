"""PDF Studio: a local, Acrobat-style PDF editor built on FastAPI and PyMuPDF."""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

import fitz  # PyMuPDF
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PDF_STUDIO_DATA") or BASE_DIR / "data")
DOCS_DIR = DATA_DIR / "docs"
FONTS_DIR = DATA_DIR / "fonts"
STATIC_DIR = BASE_DIR / "static"
FONT_INDEX = FONTS_DIR / "index.json"
MAX_FONT_BYTES = 30 * 1024 * 1024
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
HISTORY_LIMIT = 30
UPLOAD_CHUNK = 1024 * 1024
MAX_RENDER_SCALE = 4.0
RENDER_CACHE_BYTES = 256 * 1024 * 1024
LINES_CACHE_ITEMS = 64

BUILTIN_FONTS = {
    "helv": "Helvetica",
    "tiro": "Times Roman",
    "cour": "Courier",
    "china-s": "Simplified Chinese (built-in CJK)",
}
STANDARD_FONTS = {"helv", "hebo", "heit", "hebi", "tiro", "tibo", "tiit", "tibi", "cour", "cobo", "coit", "cobi"}
MARKUP_TYPES = {"highlight", "underline", "strikeout", "squiggly"}
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

DOCS_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)
_lock = threading.RLock()
_cache_lock = threading.Lock()
_render_cache: OrderedDict = OrderedDict()
_render_bytes = 0
_lines_cache: OrderedDict = OrderedDict()

app = FastAPI(title="PDF Studio")
# Blocks DNS rebinding: a page on another domain cannot reach the server through the browser.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


# ---------- storage helpers ----------

def _doc_dir(doc_id: str) -> Path:
    try:
        uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(404, "document not found")
    path = DOCS_DIR / doc_id
    if not (path / "current.pdf").exists():
        raise HTTPException(404, "document not found")
    return path


def _read_meta(path: Path) -> dict:
    return json.loads((path / "meta.json").read_text(encoding="utf-8"))


def _write_meta(path: Path, meta: dict) -> None:
    (path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _safe_name(name: str) -> str:
    name = Path(name).name.strip() or "document.pdf"
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def _new_meta(name: str) -> dict:
    return {"name": _safe_name(name), "history": 0, "floor": 0, "redo": 0, "version": 0}


def _create_doc(pdf_bytes: bytes, name: str) -> str:
    doc_id = uuid.uuid4().hex
    path = DOCS_DIR / doc_id
    (path / "history").mkdir(parents=True)
    (path / "redo").mkdir()
    (path / "current.pdf").write_bytes(pdf_bytes)
    _write_meta(path, _new_meta(name))
    return doc_id


def _create_doc_from_file(src: Path, name: str) -> str:
    doc_id = uuid.uuid4().hex
    path = DOCS_DIR / doc_id
    (path / "history").mkdir(parents=True)
    (path / "redo").mkdir()
    shutil.move(str(src), path / "current.pdf")
    _write_meta(path, _new_meta(name))
    return doc_id


async def _save_upload(file: UploadFile, limit: int, too_large: str) -> Path:
    """Stream an upload to a temp file, so memory use stays flat whatever the size."""
    fd, name = tempfile.mkstemp(dir=DATA_DIR, suffix=".upload")
    tmp = Path(name)
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(UPLOAD_CHUNK):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, too_large)
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _open_pdf_file(path: Path, password: str = "") -> tuple[fitz.Document, bool]:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise HTTPException(400, f"not a readable PDF: {exc}")
    locked = bool(doc.needs_pass)
    if locked:
        if not password:
            doc.close()
            raise HTTPException(401, "password required")
        if not doc.authenticate(password):
            doc.close()
            raise HTTPException(401, "wrong password")
    if doc.page_count == 0:
        doc.close()
        raise HTTPException(400, "PDF has no pages")
    return doc, locked


def _check_index(doc: fitz.Document, index: int) -> None:
    if not 0 <= index < doc.page_count:
        raise HTTPException(404, "page not found")


def _mutate(doc_id: str, action: Callable[[fitz.Document], Any]) -> Any:
    """Snapshot first, so the edit can be undone."""
    path = _doc_dir(doc_id)
    with _lock:
        meta = _read_meta(path)
        snap = path / "history" / f"{meta['history'] + 1:06d}.pdf"
        shutil.copyfile(path / "current.pdf", snap)
        tmp = path / "current.tmp"
        doc = fitz.open(path / "current.pdf")
        try:
            result = action(doc)
            doc.save(tmp, garbage=3, deflate=True)
        except HTTPException:
            snap.unlink(missing_ok=True)
            raise
        except Exception as exc:
            snap.unlink(missing_ok=True)
            raise HTTPException(400, str(exc))
        finally:
            doc.close()
        os.replace(tmp, path / "current.pdf")
        _clear_redo(path)
        meta["history"] += 1
        meta["redo"] = 0
        floor = meta.get("floor", 0)
        while meta["history"] - floor > HISTORY_LIMIT:
            floor += 1
            (path / "history" / f"{floor:06d}.pdf").unlink(missing_ok=True)
        meta["floor"] = floor
        meta["version"] = meta.get("version", 0) + 1
        _write_meta(path, meta)
        return result


def _clear_redo(path: Path) -> None:
    redo = path / "redo"
    redo.mkdir(exist_ok=True)
    for item in redo.glob("*.pdf"):
        item.unlink(missing_ok=True)


# ---------- picture placement in the page content ----------
# Only the picture's own draw command is touched, so nearby text stays exact.

_TOKEN = re.compile(rb"\((?:\\.|[^\\()])*\)|<[^<>]*>|/[^\s/\[\]()<>{}%]*|[-+]?(?:\d+\.?\d*|\.\d+)|[A-Za-z'\"*]+|[\[\]{}]|%[^\r\n]*")
_NUMBER = re.compile(rb"[-+]?(?:\d|\.\d)")
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mat_mul(m, n):
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _mat_inv(m):
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-9:
        raise ValueError("picture transform cannot be inverted")
    return (d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det)


def _ctm_before(data: bytes, stop: int):
    ctm, stack, nums = _IDENTITY, [], []
    for m in _TOKEN.finditer(data, 0, stop):
        tok = m.group(0)
        if tok in (b"[", b"]", b"{", b"}") or tok[:1] == b"%":
            continue
        if _NUMBER.match(tok):
            nums.append(float(tok))
        elif tok[:1] in (b"/", b"(", b"<"):
            nums.append(None)
        else:
            if tok == b"cm" and len(nums) >= 6 and None not in nums[-6:]:
                ctm = _mat_mul(tuple(nums[-6:]), ctm)
            elif tok == b"q":
                stack.append(ctm)
            elif tok == b"Q" and stack:
                ctm = stack.pop()
            nums = []
    return ctm


def _first_text_pos(data: bytes) -> int:
    for m in _TOKEN.finditer(data):
        if m.group(0) == b"BT":
            return m.start()
    return len(data)


def _page_image_name(page: fitz.Page, xref: int) -> str:
    for entry in page.get_images(full=True):
        if entry[0] == xref:
            return entry[7]
    raise ValueError("this picture cannot be moved")


def _draw_spot(data: bytes, name: str):
    spots = list(re.finditer(rb"/" + re.escape(name.encode()) + rb"\s+Do\b", data))
    if len(spots) != 1:
        raise ValueError("this picture cannot be moved")
    return spots[0]


def _draw_snippet(name: str, total, ctm_at) -> bytes:
    m = _mat_mul(total, _mat_inv(ctm_at))
    return ("q %.6f %.6f %.6f %.6f %.6f %.6f cm /%s Do Q" % (*m, name)).encode()


def _write_page_content(doc: fitz.Document, page: fitz.Page, data: bytes) -> None:
    xrefs = page.get_contents()
    doc.update_stream(xrefs[0], data)
    for xref in xrefs[1:]:
        doc.update_stream(xref, b"")


def _move_picture(doc: fitz.Document, page: fitz.Page, op: "Op") -> None:
    if not op.xref or not op.rect or not op.dest or len(op.dest) != 2:
        raise ValueError("move_image needs a picture and a destination")
    name = _page_image_name(page, op.xref)
    data = page.read_contents()
    spot = _draw_spot(data, name)
    total = _ctm_before(data, spot.start())
    rect = fitz.Rect(op.rect)
    # Page space is y-up, client coordinates are y-down.
    dx = op.dest[0] - rect.x0
    dy = -(op.dest[1] - rect.y0)
    new_total = _mat_mul(total, (1.0, 0.0, 0.0, 1.0, dx, dy))
    snippet = _draw_snippet(name, new_total, total)
    data = data[:spot.start()] + snippet + data[spot.end():]
    _write_page_content(doc, page, data)


def _set_picture_layer(doc: fitz.Document, page: fitz.Page, op: "Op") -> None:
    if not op.xref or not op.rect or op.z not in ("top", "under", "bottom"):
        raise ValueError("layer needs a picture and one of top, under, bottom")
    name = _page_image_name(page, op.xref)
    data = page.read_contents()
    spot = _draw_spot(data, name)
    total = _ctm_before(data, spot.start())
    data = data[:spot.start()] + data[spot.end():]
    if op.z == "top":
        pos = len(data)
    elif op.z == "bottom":
        pos = 0
    else:
        pos = _first_text_pos(data)
    snippet = _draw_snippet(name, total, _ctm_before(data, pos))
    data = data[:pos] + b"\n" + snippet + b"\n" + data[pos:]
    _write_page_content(doc, page, data)


def _resize_picture(doc: fitz.Document, page: fitz.Page, op: "Op") -> None:
    if not op.xref or not op.rect or not op.dest or len(op.dest) != 4:
        raise ValueError("resize_image needs a picture and a new rectangle")
    ox0, oy0, ox1, oy1 = op.rect
    nx0, ny0, nx1, ny1 = op.dest
    ow, oh, nw, nh = ox1 - ox0, oy1 - oy0, nx1 - nx0, ny1 - ny0
    if ow <= 0 or oh <= 0 or nw < 1 or nh < 1:
        raise ValueError("picture size is too small")
    name = _page_image_name(page, op.xref)
    data = page.read_contents()
    spot = _draw_spot(data, name)
    total = _ctm_before(data, spot.start())
    mb = page.mediabox
    sx, sy = nw / ow, nh / oh
    xo, yo = ox0 + mb.x0, mb.y1 - oy1
    xn, yn = nx0 + mb.x0, mb.y1 - ny1
    scale = (sx, 0.0, 0.0, sy, xn - xo * sx, yn - yo * sy)
    snippet = _draw_snippet(name, _mat_mul(total, scale), total)
    data = data[:spot.start()] + snippet + data[spot.end():]
    _write_page_content(doc, page, data)


def _delete_picture(doc: fitz.Document, page: fitz.Page, op: "Op") -> None:
    if not op.xref:
        raise ValueError("delete_image needs a picture")
    name = _page_image_name(page, op.xref)
    data = page.read_contents()
    spot = _draw_spot(data, name)
    _write_page_content(doc, page, data[:spot.start()] + data[spot.end():])


# ---------- edit operations ----------

class Op(BaseModel):
    type: str
    page: int = 0
    rect: Optional[list[float]] = None
    text: Optional[str] = None
    font: str = "auto"
    size: float = 12
    origin: Optional[list[float]] = None
    font_xref: int = 0
    base_font: Optional[str] = None
    color: list[float] = [0, 0, 0]
    fill: Optional[list[float]] = None
    width: float = 1.0
    opacity: float = 1.0
    points: Optional[list[list[list[float]]]] = None
    angle: Optional[int] = None
    to: Optional[int] = None
    dest: Optional[list[float]] = None
    bold: Optional[bool] = None
    enabled: Optional[bool] = None
    image: Optional[str] = None
    align: Optional[str] = None
    xref: int = 0
    z: Optional[str] = None
    block: Optional[list[float]] = None
    italic: Optional[bool] = None
    # Letter spacing in thousandths of an em, added after every character.
    tracking: Optional[float] = None
    # Line spacing in points between baselines of lines in this text; None means automatic.
    leading: Optional[float] = None


class OpsRequest(BaseModel):
    ops: list[Op] = Field(min_length=1, max_length=500)


def _load_fonts() -> list[dict]:
    if FONT_INDEX.exists():
        return json.loads(FONT_INDEX.read_text(encoding="utf-8"))
    return []


def _save_fonts(items: list[dict]) -> None:
    FONT_INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


CJK = r"⺀-鿿가-힯　-〿＀-￯"
TOKEN_RE = re.compile(rf"[{CJK}]|[^\s{CJK}]+\s*|\s+")
LINE_HEIGHT = 1.2


def _resolve_font(page: fitz.Page, key: str):
    if key in BUILTIN_FONTS or key in STANDARD_FONTS:
        return key, fitz.Font(fontname=key)
    entry = next((f for f in _load_fonts() if f["id"] == key), None)
    if entry is None:
        raise ValueError(f"unknown font: {key}")
    alias = f"U{key}"
    path = str(FONTS_DIR / entry["file"])
    page.insert_font(fontname=alias, fontfile=path)
    return alias, fitz.Font(fontfile=path)


def _base_key(base: Optional[str], force_bold: Optional[bool] = None,
              force_italic: Optional[bool] = None) -> str:
    name = (base or "").lower()
    bold = any(w in name for w in ("bold", "black", "heavy", "semibold", "demi"))
    if force_bold is not None:
        bold = force_bold
    italic = any(w in name for w in ("italic", "oblique"))
    if force_italic is not None:
        italic = force_italic
    if "courier" in name or "mono" in name:
        family = ("cour", "cobo", "coit", "cobi")
    elif "times" in name or ("serif" in name and "sans" not in name):
        family = ("tiro", "tibo", "tiit", "tibi")
    else:
        family = ("helv", "hebo", "heit", "hebi")
    regular, bold_name, italic_name, both = family
    if bold and italic:
        return both
    if bold:
        return bold_name
    if italic:
        return italic_name
    return regular


def _covers(font: fitz.Font, text: str) -> bool:
    return all(ch.isspace() or font.has_glyph(ord(ch)) for ch in text)


def _embedded(page: fitz.Page, doc: fitz.Document, xref: int, text: str):
    if not xref:
        return None
    try:
        _, ext, _, buf = doc.extract_font(xref)
        if not buf or ext in ("", "n/a"):
            return None
        font = fitz.Font(fontbuffer=buf)
        if not _covers(font, re.sub(rf"[{CJK}]", "", text)):
            return None
        alias = f"E{xref}"
        page.insert_font(fontname=alias, fontbuffer=buf)
        return alias, font
    except Exception:
        return None


STANDARD_FAMILIES = (("helv", "hebo", "heit", "hebi"), ("tiro", "tibo", "tiit", "tibi"), ("cour", "cobo", "coit", "cobi"))


def _style_variant(key: str, bold: Optional[bool], italic: Optional[bool]) -> str:
    """Uploaded fonts have no bold or italic variant, so they pass through."""
    for family in STANDARD_FAMILIES:
        if key in family:
            current = family.index(key)
            is_bold = bool(current & 1) if bold is None else bold
            is_italic = bool(current & 2) if italic is None else italic
            return family[(2 if is_italic else 0) + (1 if is_bold else 0)]
    return key


def _choose_font(page: fitz.Page, doc: fitz.Document, text: str,
                 xref: int, key: Optional[str], base: Optional[str]):
    # A chosen font is always used; only "auto" may keep the embedded one.
    explicit = bool(key) and key != "auto"
    primary = None if explicit else _embedded(page, doc, xref, text)
    if primary is None:
        if not explicit:
            key = _base_key(base)
        primary = _resolve_font(page, key)
    fallback = _resolve_font(page, "china-s")
    return primary, fallback


def _pick(fonts, segment: str):
    primary, fallback = fonts
    return primary if _covers(primary[1], segment) else fallback


def _segments(text: str) -> list[str]:
    return [s for s in re.findall(rf"[{CJK}]+|[^{CJK}]+", text) if s]


def _measure(fonts, text: str, size: float, tracking: float = 0.0) -> float:
    # Tracking adds one gap after every character, the same as the PDF Tc operator.
    return sum(_pick(fonts, seg)[1].text_length(seg, fontsize=size) for seg in _segments(text)) + tracking * len(text)


def _split_long(fonts, token: str, size: float, width: float, tracking: float = 0.0) -> list[str]:
    if len(token.rstrip()) <= 1 or _measure(fonts, token.rstrip(), size, tracking) <= width:
        return [token]
    pieces, cur = [], ""
    for ch in token:
        if cur and _measure(fonts, cur + ch, size, tracking) > width:
            pieces.append(cur)
            cur = ch
        else:
            cur += ch
    pieces.append(cur)
    return pieces


def _wrap(fonts, para: str, size: float, width: float, tracking: float = 0.0) -> list[str]:
    if not para.strip():
        return [""]
    lines, cur = [], ""
    for token in TOKEN_RE.findall(para):
        for piece in _split_long(fonts, token, size, width, tracking):
            candidate = cur + piece
            if cur.strip() and _measure(fonts, candidate.rstrip(), size, tracking) > width:
                lines.append(cur.rstrip())
                cur = piece.lstrip()
            else:
                cur = candidate
    if cur.strip() or not lines:
        lines.append(cur.rstrip())
    return lines


def _bg_color(page: fitz.Page, rect: fitz.Rect):
    """Sample the ring, not the box corners, so glyph pixels do not skew the color."""
    try:
        margin = 4.0
        clip = fitz.Rect(rect.x0 - margin, rect.y0 - margin, rect.x1 + margin, rect.y1 + margin) & page.rect
        pix = page.get_pixmap(clip=clip, colorspace=fitz.csRGB, alpha=False)
        w, h, n = pix.width, pix.height, pix.n
        data = pix.samples
        edge = []
        for x in range(w):
            for y in (0, h - 1):
                i = (y * w + x) * n
                edge.append(data[i:i + 3])
        for y in range(h):
            for x in (0, w - 1):
                i = (y * w + x) * n
                edge.append(data[i:i + 3])
        # Most common color, not a per-channel median, which can invent a tone no pixel has.
        counts: dict = {}
        for px in edge:
            key = (px[0], px[1], px[2])
            counts[key] = counts.get(key, 0) + 1
        best = max(counts.items(), key=lambda kv: kv[1])[0]
        return tuple(v / 255 for v in best)
    except Exception:
        return (1, 1, 1)


def _overlap_area(a: fitz.Rect, b: fitz.Rect) -> float:
    """Plain math, since some PyMuPDF versions lack Rect.get_area()."""
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    if w <= 0 or h <= 0:
        return 0.0
    return w * h


TC_BT_RE = re.compile(rb"(?<=\s)BT(?=\s)")
# Letter spacing uses Adobe's unit: thousandths of an em.
TRACKING_MIN = -200.0
TRACKING_MAX = 1000.0


def _tracking_value(value: Optional[float], size: float) -> float:
    """Returns the gap in points, which is what the PDF Tc operator takes."""
    if value is None:
        return 0.0
    if not TRACKING_MIN <= value <= TRACKING_MAX:
        raise ValueError(f"letter spacing must be from {TRACKING_MIN:g} to {TRACKING_MAX:g} (1/1000 em)")
    return float(value) / 1000.0 * size


def _insert_run(page: fitz.Page, point: fitz.Point, seg: str, alias: str,
                size: float, color, tracking: float) -> None:
    """One run per insert. Tracking becomes a Tc operator inside that run's own content stream.

    PyMuPDF wraps each run in q/Q, so the operator does not leak into later text.
    """
    if not tracking:
        page.insert_text(point, seg, fontname=alias, fontsize=size, color=tuple(color))
        return
    doc = page.parent
    before = page.get_contents()
    page.insert_text(point, seg, fontname=alias, fontsize=size, color=tuple(color))
    new = [x for x in page.get_contents() if x not in before]
    if len(new) != 1:
        raise RuntimeError("letter spacing: could not find the new text run")
    data, n = TC_BT_RE.subn(b"BT\n%.4f Tc" % tracking, doc.xref_stream(new[0]), count=1)
    if n != 1:
        raise RuntimeError("letter spacing: text operator not found")
    doc.update_stream(new[0], data)


def _place_text(page: fitz.Page, doc: fitz.Document, rect: fitz.Rect, text: str,
                key: Optional[str], size: float, color, xref: int = 0,
                origin=None, base: Optional[str] = None, tracking: float = 0.0,
                leading: Optional[float] = None) -> str:
    """Lines wrap at the page margin, never at the box, so the size stays the same."""
    fonts = _choose_font(page, doc, text, xref, key, base)
    x0 = origin[0] if origin else rect.x0
    baseline = origin[1] if origin else rect.y0 + size * 0.92
    avail = max(rect.width, page.rect.x1 - 18 - x0)
    lines = [ln for para in text.split("\n") for ln in _wrap(fonts, para, size, avail, tracking)]
    words = [fitz.Rect(w[:4]) for w in page.get_text("words")]
    collide = False
    for i, line in enumerate(lines):
        y = baseline + i * (leading if leading else size * LINE_HEIGHT)
        box = fitz.Rect(x0, y - size * 0.85, x0 + _measure(fonts, line, size, tracking), y + size * 0.25)
        if any(_overlap_area(w, box) > 2 for w in words):
            collide = True
        cx = x0
        for seg in _segments(line):
            alias, font = _pick(fonts, seg)
            _insert_run(page, fitz.Point(cx, y), seg, alias, size, color, tracking)
            cx += font.text_length(seg, fontsize=size) + tracking * len(seg)
    return "collide" if collide else "ok"


def _char_boxes(page: fitz.Page, rect: fitz.Rect) -> list:
    """Only glyphs centered in rect count; neighbors touching its edge stay put."""
    boxes = []
    data = page.get_text("rawdict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    b = fitz.Rect(ch["bbox"])
                    if b.is_empty:
                        continue
                    center = fitz.Point((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
                    if rect.contains(center):
                        boxes.append(b)
    return boxes


def _paint_pieces(shapes: list, box: fitz.Rect, fallback) -> list:
    """Split fills keep a shading edge intact; one color would leave a wrong patch."""
    # Stacked pieces would show faint seams at anti-aliased edges, so one shape wins here.
    top = None  # the topmost shape that overlaps the glyph box
    for shape_rect, fill in shapes:
        if _overlap_area(shape_rect, box) > 0:
            top = (shape_rect, fill)
    if top is not None and top[0].contains(box):
        return [(box, top[1])]
    # Pixels are read only when no shape lies under the glyph; rendering per glyph is slow.
    under = next(((r, f) for r, f in shapes if _overlap_area(r, box) > 0), None)
    base = under[1] if under is not None else fallback
    pieces = [(box, base)]
    for shape_rect, fill in shapes:
        common = fitz.Rect(shape_rect) & box
        if common.is_empty or common.width < 0.1 or common.height < 0.1:
            continue
        pieces.append((common, fill))
    return pieces


MIN_BACKDROP_SIDE_PT = 16  # glyph-sized patches left by earlier erasing are narrower or smaller than this
MIN_BACKDROP_AREA_PT = 2000


def _filled_shapes(page: fitz.Page) -> list:
    """Glyph-sized patches from earlier erases are skipped, or each edit would grow the work."""
    shapes = []
    for dr in page.get_drawings():
        fill = dr.get("fill")
        if fill is None or len(fill) != 3:
            continue
        r = fitz.Rect(dr["rect"])
        if r.is_empty or min(r.width, r.height) < MIN_BACKDROP_SIDE_PT or r.width * r.height < MIN_BACKDROP_AREA_PT:
            continue
        shapes.append((r, tuple(fill)))
    return shapes


def _erase(page: fitz.Page, rect: fitz.Rect) -> None:
    """Each glyph gets its own fill, so tinted backgrounds do not show a wrong patch."""
    boxes = _char_boxes(page, rect)
    if not boxes:
        return
    shapes = _filled_shapes(page)
    fallback = _bg_color(page, rect)  # for glyphs with no drawn shape under them, one sample per edit
    for b in boxes:
        for piece, color in _paint_pieces(shapes, b, fallback):
            page.add_redact_annot(piece, fill=color)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
    )


def _page_at(doc: fitz.Document, index: int) -> fitz.Page:
    if not 0 <= index < doc.page_count:
        raise ValueError(f"page {index + 1} does not exist")
    return doc[index]


LEADING_MIN = 1.0
LEADING_MAX = 200.0


def _leading_value(value: Optional[float]) -> Optional[float]:
    """Line spacing in points, or None for the automatic size times LINE_HEIGHT."""
    if value is None:
        return None
    if not LEADING_MIN <= value <= LEADING_MAX:
        raise ValueError(f"line spacing must be from {LEADING_MIN:g} to {LEADING_MAX:g} pt")
    return float(value)


def _apply_op(doc: fitz.Document, op: Op) -> Optional[str]:
    if op.type == "delete_page":
        _page_at(doc, op.page)
        if doc.page_count == 1:
            raise ValueError("cannot delete the only page")
        doc.delete_page(op.page)
        return None
    if op.type == "move_page":
        _page_at(doc, op.page)
        if op.to is None or not 0 <= op.to < doc.page_count:
            raise ValueError("invalid target page")
        doc.move_page(op.page, op.to)
        return None

    page = _page_at(doc, op.page)
    if op.type == "rotate_page":
        page.set_rotation((page.rotation + (op.angle or 90)) % 360)
        return None

    if op.rect is None and op.type != "ink":
        raise ValueError(f"{op.type} needs a rect")

    if op.type == "ocr_text":
        # Invisible text layer, so the scan looks unchanged.
        if not op.origin or not op.text:
            return None
        has_cjk = bool(re.search(rf"[{CJK}]", op.text))
        if has_cjk:
            fontname = "china-s"
        else:
            fontname = "hebo" if op.bold else "helv"
        page.insert_text(fitz.Point(op.origin[0], op.origin[1]), op.text,
                         fontname=fontname,
                         fontsize=op.size, render_mode=3)
        return None

    if op.type == "erase_text":
        _erase(page, fitz.Rect(op.rect))
        return None

    if op.type in ("move_text", "write_text"):
        # write_text never erases, so a group move can clear all lines first.
        if not op.dest or len(op.dest) != 2:
            raise ValueError("move needs a destination")
        rect = fitz.Rect(op.rect)
        if op.type == "move_text":
            _erase(page, rect)
        x, y = op.dest
        target = fitz.Rect(x, y - op.size, x + max(rect.width, 1), y + op.size * 0.3)
        status = _place_text(page, doc, target, op.text, op.font, op.size, op.color,
                             xref=op.font_xref, origin=(x, y), base=op.base_font)
        return None if status == "ok" else f"page {op.page + 1}: moved text overlaps nearby content"

    if op.type in ("text", "replace_text", "replace_span"):
        tracking = _tracking_value(op.tracking, op.size)  # validate before anything is erased
        leading = _leading_value(op.leading)
        rect = fitz.Rect(op.rect)
        if op.type != "text":
            _erase(page, rect)
        if not op.text:
            return None
        origin = op.origin if op.type == "replace_span" else None
        font, xref = op.font, op.font_xref
        if op.type == "replace_span" and font and font != "auto":
            # A chosen font stays; bold and italic only switch its variant.
            font, xref = _style_variant(font, op.bold, op.italic), 0
        elif op.type == "replace_span" and (op.bold is not None or op.italic is not None):
            font, xref = _base_key(op.base_font, force_bold=op.bold, force_italic=op.italic), 0
        if origin and op.align in ("left", "center", "right") and op.block and len(op.block) == 4:
            fonts = _choose_font(page, doc, op.text, xref, font, op.base_font)
            width = max(_measure(fonts, part, op.size) for part in op.text.split("\n"))
            bx0, bx1 = op.block[0], op.block[2]
            x = {"left": bx0, "center": (bx0 + bx1 - width) / 2}.get(op.align, bx1 - width)
            origin = [x, origin[1]]
        status = _place_text(page, doc, rect, op.text, font, op.size, op.color,
                             xref=xref, origin=origin, base=op.base_font, tracking=tracking,
                             leading=leading)
        if status == "ok":
            return None
        return f"page {op.page + 1}: text overlaps nearby content"

    if op.type == "set_underline":
        target = fitz.Rect(op.rect)
        area = max(1.0, target.width * target.height)
        found = None
        for annot in list(page.annots() or []):
            if annot.type[0] != fitz.PDF_ANNOT_UNDERLINE:
                continue
            if _overlap_area(annot.rect, target) > 0.5 * area:
                found = annot
                break
        if op.enabled and found is None:
            annot = page.add_underline_annot(target)
            annot.set_colors(stroke=(0, 0, 0))
            annot.update(opacity=1)
        elif not op.enabled and found is not None:
            page.delete_annot(found)
        return None

    if op.type in MARKUP_TYPES:
        maker = {
            "highlight": page.add_highlight_annot,
            "underline": page.add_underline_annot,
            "strikeout": page.add_strikeout_annot,
            "squiggly": page.add_squiggly_annot,
        }[op.type]
        annot = maker(fitz.Rect(op.rect))
        annot.set_colors(stroke=tuple(op.color))
        annot.update(opacity=op.opacity)
        return None

    if op.type == "rect":
        page.draw_rect(
            fitz.Rect(op.rect),
            color=tuple(op.color),
            fill=tuple(op.fill) if op.fill else None,
            width=op.width,
        )
        return None

    if op.type == "ink":
        strokes = [
            [(x, y) for x, y in stroke]
            for stroke in (op.points or []) if len(stroke) > 1
        ]
        if not strokes:
            raise ValueError("ink needs at least two points")
        annot = page.add_ink_annot(strokes)
        annot.set_colors(stroke=tuple(op.color))
        annot.set_border(width=op.width)
        annot.update(opacity=op.opacity)
        return None

    if op.type == "note":
        page.add_text_annot(fitz.Point(op.rect[0], op.rect[1]), op.text or "", icon="Note")
        return None

    if op.type == "move_image":
        _move_picture(doc, page, op)
        return None

    if op.type == "set_image_layer":
        _set_picture_layer(doc, page, op)
        return None

    if op.type == "delete_image":
        _delete_picture(doc, page, op)
        return None

    if op.type == "resize_image":
        _resize_picture(doc, page, op)
        return None

    if op.type == "image":
        if not op.image:
            raise ValueError("image data is required")
        data = base64.b64decode(op.image.split(",", 1)[-1])
        page.insert_image(fitz.Rect(op.rect), stream=data, keep_proportion=True, overlay=True)
        return None

    raise ValueError(f"unknown operation: {op.type}")


# ---------- documents ----------

@app.post("/api/docs")
async def upload_doc(file: UploadFile = File(...), password: str = Form("")):
    tmp = await _save_upload(file, MAX_UPLOAD_BYTES, "PDF is larger than 500 MB")
    plain = None
    try:
        doc, locked = _open_pdf_file(tmp, password)
        source = tmp
        try:
            if locked:
                # Store an unlocked copy, so later edits and undo work without the password.
                plain = tmp.with_name(tmp.name + ".plain")
                doc.save(plain, encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
                source = plain
        finally:
            doc.close()
        return {"id": _create_doc_from_file(source, file.filename or "document.pdf")}
    finally:
        tmp.unlink(missing_ok=True)
        if plain is not None:
            plain.unlink(missing_ok=True)


@app.get("/api/docs/{doc_id}")
def doc_info(doc_id: str):
    path = _doc_dir(doc_id)
    meta = _read_meta(path)
    doc = fitz.open(path / "current.pdf")
    try:
        pages = [
            {"width": p.rect.width, "height": p.rect.height, "rotation": p.rotation}
            for p in doc
        ]
    finally:
        doc.close()
    return {"id": doc_id, "name": meta["name"], "pages": pages, **_history_state(meta)}


# Caches are keyed by document version, so an edit, undo or redo never serves stale pages.
def _doc_version(doc_id: str) -> int:
    return _read_meta(_doc_dir(doc_id)).get("version", 0)


def _render_get(key: tuple) -> Optional[bytes]:
    with _cache_lock:
        data = _render_cache.get(key)
        if data is not None:
            _render_cache.move_to_end(key)
        return data


def _render_put(key: tuple, data: bytes) -> None:
    global _render_bytes
    with _cache_lock:
        if key in _render_cache:
            return
        _render_cache[key] = data
        _render_bytes += len(data)
        while _render_bytes > RENDER_CACHE_BYTES and _render_cache:
            _, old = _render_cache.popitem(last=False)
            _render_bytes -= len(old)


def _lines_get(key: tuple) -> Optional[dict]:
    with _cache_lock:
        value = _lines_cache.get(key)
        if value is not None:
            _lines_cache.move_to_end(key)
        return value


def _lines_put(key: tuple, value: dict) -> None:
    with _cache_lock:
        _lines_cache[key] = value
        while len(_lines_cache) > LINES_CACHE_ITEMS:
            _lines_cache.popitem(last=False)


def _forget_doc(doc_id: str) -> None:
    global _render_bytes
    with _cache_lock:
        for key in [k for k in _render_cache if k[0] == doc_id]:
            _render_bytes -= len(_render_cache.pop(key))
        for key in [k for k in _lines_cache if k[0] == doc_id]:
            _lines_cache.pop(key)


@app.get("/api/docs/{doc_id}/pages/{index}.png")
def render_page(doc_id: str, index: int, zoom: float = Query(2.0, ge=0.2, le=MAX_RENDER_SCALE)):
    key = (doc_id, _doc_version(doc_id), index, round(zoom, 2))
    data = _render_get(key)
    if data is None:
        path = _doc_dir(doc_id)
        doc = fitz.open(path / "current.pdf")
        try:
            _check_index(doc, index)
            data = doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")
        finally:
            doc.close()
        _render_put(key, data)
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/docs/{doc_id}/pages/{index}/text")
def text_in_rect(doc_id: str, index: int,
                 x0: float, y0: float, x1: float, y1: float):
    path = _doc_dir(doc_id)
    doc = fitz.open(path / "current.pdf")
    try:
        _check_index(doc, index)
        clip = fitz.Rect(x0, y0, x1, y1)
        words = doc[index].get_text("words", clip=clip)
    finally:
        doc.close()
    if not words:
        return {"text": "", "rect": None}
    text = " ".join(w[4] for w in words)
    rect = [min(w[0] for w in words), min(w[1] for w in words),
            max(w[2] for w in words), max(w[3] for w in words)]
    return {"text": text, "rect": rect}


@app.get("/api/docs/{doc_id}/pages/{index}/images")
def page_images(doc_id: str, index: int):
    """Page-size scans are skipped, so a scan is never dragged by accident."""
    path = _doc_dir(doc_id)
    doc = fitz.open(path / "current.pdf")
    try:
        _check_index(doc, index)
        page = doc[index]
        page_area = page.rect.width * page.rect.height
        images, seen = [], set()
        names = {entry[0]: entry[7] for entry in page.get_images(full=True)}
        content = page.read_contents()
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            bbox = fitz.Rect(info["bbox"])
            if xref <= 0 or bbox.is_empty or bbox.width * bbox.height > 0.9 * page_area:
                continue
            name = names.get(xref)
            if not name or len(list(re.finditer(rb"/" + re.escape(name.encode()) + rb"\s+Do\b", content))) != 1:
                continue
            key = (xref, tuple(round(v, 1) for v in bbox))
            if key in seen:
                continue
            seen.add(key)
            images.append({"xref": xref, "bbox": [round(v, 2) for v in bbox]})
    finally:
        doc.close()
    return {"images": images}


def _font_key(name: str) -> str:
    base = (name or "").split("+", 1)[-1]
    return re.sub(r"[^a-z0-9]", "", base.lower())


def _match_font_xref(span_font: str, names: list) -> int:
    """Span and font names differ ("DejaVuSans" vs "DejaVu Sans Book"), so compare normalized."""
    key = _font_key(span_font)
    if len(key) < 4:
        return 0
    for xref, name in names:
        if name and (key == name or key in name or name in key):
            return xref
    return 0


@app.get("/api/docs/{doc_id}/pages/{index}/lines")
def text_lines(doc_id: str, index: int):
    key = (doc_id, _doc_version(doc_id), index)
    value = _lines_get(key)
    if value is None:
        value = _text_lines_uncached(doc_id, index)
        _lines_put(key, value)
    return value


def _text_lines_uncached(doc_id: str, index: int) -> dict:
    path = _doc_dir(doc_id)
    doc = fitz.open(path / "current.pdf")
    try:
        _check_index(doc, index)
        page = doc[index]
        xrefs = {f[3]: f[0] for f in page.get_fonts()}
        names = [(f[0], _font_key(f[3])) for f in page.get_fonts()]
        underlines = [a.rect for a in (page.annots() or []) if a.type[0] == fitz.PDF_ANNOT_UNDERLINE]
        lines = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                main = max(spans, key=lambda s: len(s["text"]))
                box = fitz.Rect(line["bbox"])
                underlined = any(_overlap_area(r, box) > 0.5 * max(1.0, box.width * box.height) for r in underlines)
                lines.append({
                    "underlined": underlined,
                    "block": [round(v, 2) for v in block["bbox"]],
                    "text": "".join(s["text"] for s in line["spans"]).strip(),
                    "bbox": [round(v, 2) for v in line["bbox"]],
                    "origin": [round(v, 2) for v in spans[0]["origin"]],
                    "size": round(main["size"], 2),
                    "color": "#%06x" % main["color"],
                    "font_xref": xrefs.get(main["font"]) or _match_font_xref(main["font"], names),
                    "base_font": main["font"],
                })
    finally:
        doc.close()
    # Read in display order, not file order.
    lines.sort(key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
    return {"lines": lines}


OCR_SCALE = 3.0
# Stroke over size tells bold from regular; a rough heuristic.
OCR_BOLD_RATIO = 0.125


def _gray_from_pixmap(pix):
    import numpy as np
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return arr[:, :, :3].mean(axis=2)


def _ocr_is_bold(gray, x0, y0, x1, y1, size):
    import numpy as np
    crop = gray[int(y0 * OCR_SCALE):int(y1 * OCR_SCALE), int(x0 * OCR_SCALE):int(x1 * OCR_SCALE)]
    if crop.size == 0:
        return False
    ink = crop < (np.median(crop) - 70)
    runs = []
    for row in ink:
        count = 0
        for value in row:
            if value:
                count += 1
            elif count:
                runs.append(count)
                count = 0
        if count:
            runs.append(count)
    if not runs:
        return False
    ratio = float(np.median(runs)) / (size * OCR_SCALE)
    return ratio > OCR_BOLD_RATIO
OCR_MIN_SCORE = 0.5
_ocr_engine = None


def _get_ocr_engine():
    """Loaded on first use, since RapidOCR is optional."""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            raise HTTPException(501, "ocr_not_installed")
        _ocr_engine = RapidOCR()
    return _ocr_engine


@app.post("/api/docs/{doc_id}/pages/{index}/ocr")
def ocr_page(doc_id: str, index: int):
    path = _doc_dir(doc_id)
    doc = fitz.open(path / "current.pdf")
    try:
        _check_index(doc, index)
        page = doc[index]
        pix = page.get_pixmap(matrix=fitz.Matrix(OCR_SCALE, OCR_SCALE), alpha=False)
        png = pix.tobytes("png")
        gray = _gray_from_pixmap(pix)
    finally:
        doc.close()
    engine = _get_ocr_engine()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        tmp.write(png)
        tmp.close()
        result, _ = engine(tmp.name)
    except Exception as exc:
        raise HTTPException(500, f"OCR failed: {exc}")
    finally:
        os.unlink(tmp.name)
    lines = []
    for box, text, score in result or []:
        text = str(text).strip()
        # Low confidence is usually noise from icons or texture.
        if not text or float(score) < OCR_MIN_SCORE:
            continue
        xs = [pt[0] / OCR_SCALE for pt in box]
        ys = [pt[1] / OCR_SCALE for pt in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        height_size = (y1 - y0) / 0.93
        if re.search(rf"[{CJK}]", text):
            size = height_size
        else:
            unit = fitz.Font(fontname="helv").text_length(text, fontsize=1)
            width_size = (x1 - x0) / unit if unit > 0 else height_size
            size = width_size if abs(width_size - height_size) <= 0.3 * height_size else height_size
        size = max(4.0, min(144.0, round(size, 1)))
        bold = False if re.search(rf"[{CJK}]", text) else _ocr_is_bold(gray, x0, y0, x1, y1, size)
        lines.append({
            "bold": bold,
            "text": text,
            "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
            "origin": [round(x0, 2), round(y1 - size * 0.22, 2)],
            "size": size,
        })
    return {"lines": lines}


@app.get("/api/docs/{doc_id}/search")
def search(doc_id: str, q: str = Query(..., min_length=1, max_length=200)):
    path = _doc_dir(doc_id)
    doc = fitz.open(path / "current.pdf")
    results = []
    try:
        for index, page in enumerate(doc):
            for r in page.search_for(q):
                results.append({"page": index, "rect": [r.x0, r.y0, r.x1, r.y1]})
                if len(results) >= 500:
                    return {"results": results}
    finally:
        doc.close()
    return {"results": results}


@app.post("/api/docs/{doc_id}/ops")
def apply_ops(doc_id: str, body: OpsRequest):
    def action(doc: fitz.Document):
        warnings = [w for w in (_apply_op(doc, op) for op in body.ops) if w]
        return {"ok": True, "warnings": warnings, "pages": doc.page_count}
    return _mutate(doc_id, action)


def _history_state(meta: dict) -> dict:
    return {
        "undo_steps": meta["history"] - meta.get("floor", 0),
        "redo_steps": meta.get("redo", 0),
        "version": meta.get("version", 0),
    }


@app.post("/api/docs/{doc_id}/undo")
def undo(doc_id: str):
    path = _doc_dir(doc_id)
    with _lock:
        meta = _read_meta(path)
        if meta["history"] <= meta.get("floor", 0):
            raise HTTPException(409, "nothing to undo")
        (path / "redo").mkdir(exist_ok=True)
        redo_n = meta.get("redo", 0) + 1
        shutil.copyfile(path / "current.pdf", path / "redo" / f"{redo_n:06d}.pdf")
        snap = path / "history" / f"{meta['history']:06d}.pdf"
        os.replace(snap, path / "current.pdf")
        meta["history"] -= 1
        meta["redo"] = redo_n
        meta["version"] = meta.get("version", 0) + 1
        _write_meta(path, meta)
    return _history_state(meta)


@app.post("/api/docs/{doc_id}/redo")
def redo(doc_id: str):
    path = _doc_dir(doc_id)
    with _lock:
        meta = _read_meta(path)
        (path / "redo").mkdir(exist_ok=True)
        redo_n = meta.get("redo", 0)
        if redo_n == 0:
            raise HTTPException(409, "nothing to redo")
        shutil.copyfile(path / "current.pdf", path / "history" / f"{meta['history'] + 1:06d}.pdf")
        os.replace(path / "redo" / f"{redo_n:06d}.pdf", path / "current.pdf")
        meta["history"] += 1
        meta["redo"] = redo_n - 1
        meta["version"] = meta.get("version", 0) + 1
        _write_meta(path, meta)
    return _history_state(meta)


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str):
    path = _doc_dir(doc_id)
    with _lock:
        shutil.rmtree(path)
    _forget_doc(doc_id)
    return {"ok": True}


def _parse_pages(spec: str, count: int) -> list[int]:
    result: list[int] = []
    try:
        for part in spec.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                start, end = part.split("-", 1)
                result.extend(range(int(start), int(end) + 1))
            else:
                result.append(int(part))
    except ValueError:
        raise HTTPException(400, "invalid page range")
    pages = [p - 1 for p in result]
    if not pages or any(not 0 <= p < count for p in pages):
        raise HTTPException(400, "invalid page range")
    return pages


class ExtractRequest(BaseModel):
    pages: str
    name: Optional[str] = None


@app.post("/api/docs/{doc_id}/extract")
def extract(doc_id: str, body: ExtractRequest):
    path = _doc_dir(doc_id)
    doc = fitz.open(path / "current.pdf")
    try:
        doc.select(_parse_pages(body.pages, doc.page_count))
        data = doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
    stem = Path(_read_meta(path)["name"]).stem
    return {"id": _create_doc(data, body.name or f"{stem}-extract.pdf")}


class MergeRequest(BaseModel):
    ids: list[str] = Field(min_length=2, max_length=50)
    name: str = "merged.pdf"


@app.post("/api/merge")
def merge(body: MergeRequest):
    out = fitz.open()
    try:
        for doc_id in body.ids:
            src = fitz.open(_doc_dir(doc_id) / "current.pdf")
            try:
                out.insert_pdf(src)
            finally:
                src.close()
        data = out.tobytes(garbage=3, deflate=True)
    finally:
        out.close()
    return {"id": _create_doc(data, body.name)}


# ---------- export ----------

def _to_docx(pdf_path: Path, stem: str) -> tuple[bytes, str]:
    try:
        from pdf2docx import Converter
    except ImportError:
        raise HTTPException(501, "Word export needs the pdf2docx package")
    out = DATA_DIR / f"{uuid.uuid4().hex}.docx"
    cv = Converter(str(pdf_path))
    try:
        cv.convert(str(out))
    finally:
        cv.close()
    data = out.read_bytes()
    out.unlink(missing_ok=True)
    return data, f"{stem}.docx"


@app.get("/api/docs/{doc_id}/export/{fmt}")
def export(doc_id: str, fmt: str,
           page: int = Query(0, ge=0), zoom: float = Query(2.0, ge=0.5, le=4)):
    path = _doc_dir(doc_id)
    stem = Path(_read_meta(path)["name"]).stem or "document"
    pdf_path = path / "current.pdf"

    if fmt == "pdf":
        return _download(pdf_path.read_bytes(), "application/pdf", f"{stem}.pdf")
    if fmt == "docx":
        data, name = _to_docx(pdf_path, stem)
        return _download(data, DOCX_MEDIA, name)

    doc = fitz.open(pdf_path)
    try:
        if fmt == "txt":
            text = "\n\f".join(p.get_text() for p in doc)
            return _download(text.encode("utf-8"), "text/plain; charset=utf-8", f"{stem}.txt")
        if fmt == "png":
            _check_index(doc, page)
            data = doc[page].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")
            return _download(data, "image/png", f"{stem}-p{page + 1}.png")
        if fmt == "images":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, p in enumerate(doc):
                    png = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")
                    zf.writestr(f"{stem}-{i + 1:03d}.png", png)
            return _download(buf.getvalue(), "application/zip", f"{stem}-images.zip")
    finally:
        doc.close()
    raise HTTPException(400, "unknown export format")


def _download(data: bytes, media: str, filename: str) -> Response:
    return Response(
        data,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ---------- read-only export (Adobe-style "Restrict Editing and Printing") ----------

class ReadonlyRequest(BaseModel):
    owner_password: str = Field(min_length=6, max_length=128)
    open_password: Optional[str] = Field(default=None, max_length=128)
    printing: str = Field(default="high", pattern="^(none|low|high)$")
    changes: str = Field(default="none", pattern="^(none|forms|all)$")
    allow_copy: bool = True


@app.post("/api/docs/{doc_id}/export/readonly")
def export_readonly(doc_id: str, body: ReadonlyRequest):
    path = _doc_dir(doc_id)
    stem = Path(_read_meta(path)["name"]).stem or "document"
    perm = int(fitz.PDF_PERM_ACCESSIBILITY)  # screen readers are always allowed
    if body.printing in ("low", "high"):
        perm |= fitz.PDF_PERM_PRINT
    if body.printing == "high":
        perm |= fitz.PDF_PERM_PRINT_HQ
    if body.changes == "forms":
        perm |= fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM
    if body.changes == "all":
        perm |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM | fitz.PDF_PERM_ASSEMBLE
    if body.allow_copy:
        perm |= fitz.PDF_PERM_COPY
    doc = fitz.open(path / "current.pdf")
    try:
        data = doc.tobytes(
            garbage=3,
            deflate=True,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw=body.owner_password,
            user_pw=body.open_password or "",
            permissions=perm,
        )
    finally:
        doc.close()
    return _download(data, "application/pdf", f"{stem}-readonly.pdf")


# ---------- page, bookmark and annotation tools ----------

STAMP_POSITIONS = {"top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right", "center"}
STAMP_MARGIN = 36.0
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


class BlankPageRequest(BaseModel):
    after: int = Field(ge=-1)


class StampRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    where: str = "bottom-center"
    size: float = Field(10, ge=4, le=200)
    color: str = "#666666"
    opacity: float = Field(1.0, ge=0.05, le=1)
    angle: float = Field(0, ge=-90, le=90)
    pages: str = "all"
    page: int = Field(0, ge=0)
    behind: bool = False


class TocItem(BaseModel):
    level: int = Field(ge=1, le=10)
    title: str = Field(min_length=1, max_length=300)
    page: int = Field(ge=1)


class TocRequest(BaseModel):
    items: list[TocItem] = Field(default_factory=list, max_length=2000)


class AnnotPatch(BaseModel):
    content: str = Field(default="", max_length=5000)


def _insert_blank(doc: fitz.Document, after: int) -> int:
    ref_index = max(after, 0)
    _check_index(doc, ref_index)
    ref = doc[ref_index]
    doc.new_page(pno=after + 1, width=ref.rect.width, height=ref.rect.height)
    return doc.page_count


def _stamp_pages(doc: fitz.Document, body: StampRequest, name: str) -> int:
    if body.where not in STAMP_POSITIONS:
        raise HTTPException(400, "unknown position")
    if not HEX_COLOR.fullmatch(body.color):
        raise HTTPException(400, "color must look like #rrggbb")
    if body.pages not in ("all", "current"):
        raise HTTPException(400, "pages must be all or current")
    targets = list(range(doc.page_count)) if body.pages == "all" else [body.page]
    rgb = tuple(int(body.color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    for index in targets:
        _check_index(doc, index)
        page = doc[index]
        text = (body.text.replace("{page}", str(index + 1))
                .replace("{total}", str(doc.page_count))
                .replace("{name}", name))
        fontname = "china-s" if any(ord(ch) > 127 for ch in text) else "helv"
        width = fitz.get_text_length(text, fontname=fontname, fontsize=body.size)
        rect = page.rect
        shape = page.new_shape()
        if body.where == "center":
            cx, cy = rect.width / 2, rect.height / 2
            shape.insert_text(
                fitz.Point(cx - width / 2, cy + body.size / 3), text,
                fontsize=body.size, fontname=fontname, color=rgb, fill_opacity=body.opacity,
                morph=(fitz.Point(cx, cy), fitz.Matrix(body.angle)),
            )
        else:
            vertical, horizontal = body.where.split("-")
            x = {"left": STAMP_MARGIN, "center": (rect.width - width) / 2,
                 "right": rect.width - STAMP_MARGIN - width}[horizontal]
            y = STAMP_MARGIN + body.size if vertical == "top" else rect.height - STAMP_MARGIN
            shape.insert_text(fitz.Point(x, y), text, fontsize=body.size, fontname=fontname,
                              color=rgb, fill_opacity=body.opacity)
        shape.commit(overlay=not body.behind)
    return len(targets)


@app.post("/api/docs/{doc_id}/pages/blank")
def page_blank(doc_id: str, body: BlankPageRequest):
    return {"pages": _mutate(doc_id, lambda doc: _insert_blank(doc, body.after))}


@app.post("/api/docs/{doc_id}/stamp")
def page_stamp(doc_id: str, body: StampRequest):
    name = Path(_read_meta(_doc_dir(doc_id))["name"]).stem or "document"
    return {"stamped": _mutate(doc_id, lambda doc: _stamp_pages(doc, body, name))}


@app.get("/api/docs/{doc_id}/toc")
def toc_read(doc_id: str):
    path = _doc_dir(doc_id)
    doc = fitz.open(path / "current.pdf")
    try:
        rows = doc.get_toc(simple=True)
    finally:
        doc.close()
    return {"items": [{"level": lvl, "title": title, "page": page}
                      for lvl, title, page in rows if page > 0]}


@app.put("/api/docs/{doc_id}/toc")
def toc_write(doc_id: str, body: TocRequest):
    rows: list = []
    previous = 0
    for item in body.items:
        if item.level > previous + 1:
            raise HTTPException(400, "a bookmark cannot skip a level")
        previous = item.level
        rows.append([item.level, item.title, item.page])

    def action(doc: fitz.Document) -> int:
        if any(page > doc.page_count for _, _, page in rows):
            raise HTTPException(400, "bookmark page is out of range")
        doc.set_toc(rows)
        return len(rows)

    return {"count": _mutate(doc_id, action)}


def _find_annot(doc: fitz.Document, xref: int):
    for page in doc:
        for annot in page.annots() or []:
            if annot.xref == xref:
                return page, annot
    raise HTTPException(404, "annotation not found")


@app.get("/api/docs/{doc_id}/annotations")
def annots_list(doc_id: str):
    path = _doc_dir(doc_id)
    doc = fitz.open(path / "current.pdf")
    items = []
    try:
        for page in doc:
            for annot in page.annots() or []:
                items.append({
                    "xref": annot.xref,
                    "page": page.number,
                    "type": annot.type[1],
                    "content": annot.info.get("content", "") or "",
                    "rect": [round(v, 2) for v in annot.rect],
                })
    finally:
        doc.close()
    return {"items": items}


@app.patch("/api/docs/{doc_id}/annotations/{xref}")
def annot_edit(doc_id: str, xref: int, body: AnnotPatch):
    def action(doc: fitz.Document) -> None:
        _, annot = _find_annot(doc, xref)
        annot.set_info(content=body.content)
        annot.update()

    _mutate(doc_id, action)
    return {"ok": True}


@app.delete("/api/docs/{doc_id}/annotations/{xref}")
def annot_remove(doc_id: str, xref: int):
    def action(doc: fitz.Document) -> None:
        page, annot = _find_annot(doc, xref)
        page.delete_annot(annot)

    _mutate(doc_id, action)
    return {"ok": True}


# ---------- fonts ----------

def _font_details(entry: dict) -> dict:
    path = FONTS_DIR / entry["file"]
    try:
        cjk = fitz.Font(fontfile=str(path)).has_glyph(0x4E2D) > 0  # 0x4E2D is a CJK ideograph
    except Exception:
        cjk = False
    return {
        "id": entry["id"],
        "name": entry["name"],
        "size": path.stat().st_size if path.exists() else 0,
        "cjk": cjk,
    }


@app.get("/api/fonts")
def list_fonts():
    return {
        "builtin": [{"id": k, "name": v} for k, v in BUILTIN_FONTS.items()],
        "custom": [_font_details(f) for f in _load_fonts()],
    }


@app.get("/api/fonts/{font_id}/file")
def font_file(font_id: str):
    entry = next((f for f in _load_fonts() if f["id"] == font_id), None)
    if entry is None:
        raise HTTPException(404, "font not found")
    data = (FONTS_DIR / entry["file"]).read_bytes()
    return Response(data, media_type="font/ttf", headers={"Cache-Control": "no-store"})


@app.post("/api/fonts")
async def upload_font(file: UploadFile = File(...)):
    filename = file.filename or "font.ttf"
    ext = Path(filename).suffix.lower()
    if ext != ".ttf":
        raise HTTPException(400, "only standard .ttf fonts are supported")
    tmp = await _save_upload(file, MAX_FONT_BYTES, "font file is larger than 30 MB")
    try:
        data = tmp.read_bytes()
        try:
            font = fitz.Font(fontbuffer=data)
        except Exception as exc:
            raise HTTPException(400, f"invalid font file: {exc}")

        font_id = uuid.uuid4().hex[:12]
        display = font.name or Path(filename).stem
        with _lock:
            (FONTS_DIR / f"{font_id}{ext}").write_bytes(data)
            items = _load_fonts()
            items.append({"id": font_id, "name": display, "file": f"{font_id}{ext}"})
            _save_fonts(items)
        return {"id": font_id, "name": display}
    finally:
        tmp.unlink(missing_ok=True)


@app.delete("/api/fonts/{font_id}")
def delete_font(font_id: str):
    with _lock:
        items = _load_fonts()
        entry = next((f for f in items if f["id"] == font_id), None)
        if entry is None:
            raise HTTPException(404, "font not found")
        (FONTS_DIR / entry["file"]).unlink(missing_ok=True)
        _save_fonts([f for f in items if f["id"] != font_id])
    return {"ok": True}


# ---------- session lifecycle ----------

HEARTBEAT_TIMEOUT = 120.0  # fallback when a tab vanishes without a leave signal (background tabs are throttled)
LEAVE_GRACE = 3.0          # time allowed for a page reload to register again
STARTUP_GRACE = 30.0       # time to wait for the first browser tab

_clients: dict[str, float] = {}  # client id -> expiry time (monotonic clock)
_clients_lock = threading.Lock()
_started_at = time.monotonic()
_ever_connected = False


@app.get("/api/identity")
def identity():
    return {"app": "pdf-studio"}


class ClientMessage(BaseModel):
    id: str = Field(min_length=1, max_length=64)


def _require_marker(request: Request) -> None:
    # Only this app's pages send the header, so other sites cannot call these routes.
    if request.headers.get("x-pdf-studio") != "1":
        raise HTTPException(403, "forbidden")


def _exit_soon() -> None:
    threading.Timer(0.3, lambda: os._exit(0)).start()


def _watchdog() -> None:
    while True:
        time.sleep(2)
        now = time.monotonic()
        with _clients_lock:
            for cid in [c for c, expiry in _clients.items() if expiry < now]:
                del _clients[cid]
            if _clients:
                continue
            if _ever_connected or now - _started_at > STARTUP_GRACE:
                os._exit(0)


@app.post("/api/heartbeat", dependencies=[Depends(_require_marker)])
def heartbeat(body: ClientMessage):
    global _ever_connected
    with _clients_lock:
        _clients[body.id] = time.monotonic() + HEARTBEAT_TIMEOUT
        _ever_connected = True
    return {"ok": True}


@app.post("/api/leave", dependencies=[Depends(_require_marker)])
def leave(body: ClientMessage):
    with _clients_lock:
        if body.id in _clients:
            _clients[body.id] = min(_clients[body.id], time.monotonic() + LEAVE_GRACE)
    return {"ok": True}


@app.post("/api/shutdown", dependencies=[Depends(_require_marker)])
def shutdown():
    _exit_soon()
    return {"ok": True}


if not os.environ.get("PDF_STUDIO_NO_WATCHDOG"):
    threading.Thread(target=_watchdog, daemon=True).start()

class NoCacheStatic(StaticFiles):
    """No caching, so an update is never hidden by an old script."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount("/", NoCacheStatic(directory=STATIC_DIR, html=True), name="static")
