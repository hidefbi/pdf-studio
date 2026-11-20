"""Takes one line of text out of a page's content stream.

Only the glyphs of that line are removed. Nothing is painted over the
page, so text around the line stays as it was, even where the two overlap.
The page text is compared before and after, and if anything else changed
the edit is refused.

Anything this module does not understand raises ValueError with the
generic message below.
"""

from __future__ import annotations

import re

import fitz

REFUSED = "this text cannot be changed safely"
MATCH_TOL = 0.3  # points between a glyph origin and the text origin
CHECK_TOL = 0.05  # points allowed when the page text is compared again
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# Standard 14 fonts, by the names PyMuPDF uses for them.
BASE14 = {
    b"Helvetica": "helv", b"Helvetica-Bold": "hebo", b"Helvetica-Oblique": "heit",
    b"Helvetica-BoldOblique": "hebi", b"Times-Roman": "tiro", b"Times-Bold": "tibo",
    b"Times-Italic": "tiit", b"Times-BoldItalic": "tibi", b"Courier": "cour",
    b"Courier-Bold": "cobo", b"Courier-Oblique": "coit", b"Courier-BoldOblique": "cobi",
}
ESCAPES = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12,
           ord("("): 40, ord(")"): 41, ord("\\"): 92}
SPACE = frozenset(b" \t\r\n\f\x00")
DELIMS = frozenset(b"()<>[]{}/%")
NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
INLINE_ID = re.compile(rb"\sID(?=\s)")
INLINE_EI = re.compile(rb"\sEI(?=\s|$)")


def _refuse():
    raise ValueError(REFUSED)


class _Tok:
    __slots__ = ("kind", "value", "start", "end")

    def __init__(self, kind, value, start, end):
        self.kind = kind
        self.value = value
        self.start = start
        self.end = end


class _Ins:
    __slots__ = ("op", "operands", "start", "end")

    def __init__(self, op, operands, start, end):
        self.op = op
        self.operands = operands
        self.start = start
        self.end = end


# ---------- reading the syntax ----------

def _literal(data: bytes, i: int):
    """Reads a (...) string that starts at i. Returns the bytes and the index after it."""
    out = bytearray()
    depth = 0
    i += 1
    n = len(data)
    while i < n:
        c = data[i]
        if c == 0x5C:  # backslash
            i += 1
            if i >= n:
                break
            c = data[i]
            if c in ESCAPES:
                out.append(ESCAPES[c])
                i += 1
            elif 0x30 <= c <= 0x37:
                j, val = i, 0
                while j < n and j < i + 3 and 0x30 <= data[j] <= 0x37:
                    val = val * 8 + data[j] - 0x30
                    j += 1
                out.append(val & 0xFF)
                i = j
            elif c == 0x0D:
                i += 2 if data[i + 1:i + 2] == b"\n" else 1
            elif c == 0x0A:
                i += 1
            else:
                out.append(c)
                i += 1
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            if depth == 0:
                return bytes(out), i + 1
            depth -= 1
        out.append(c)
        i += 1
    _refuse()


def _inline_end(data: bytes, pos: int) -> int:
    """Skips an inline image (BI ... ID data EI). Returns the index after EI."""
    found = INLINE_ID.search(data, pos)
    if not found:
        _refuse()
    end = INLINE_EI.search(data, found.end())
    if not end:
        _refuse()
    return end.end()


def _lex(data: bytes):
    """Splits a content stream or an object into tokens, each with its byte span."""
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        if c in SPACE:
            i += 1
        elif c == 0x25:  # comment
            while i < n and data[i] not in b"\r\n":
                i += 1
        elif data[i:i + 2] == b"<<":
            yield _Tok("<<", None, i, i + 2)
            i += 2
        elif data[i:i + 2] == b">>":
            yield _Tok(">>", None, i, i + 2)
            i += 2
        elif c == 0x28:
            start = i
            value, i = _literal(data, i)
            yield _Tok("str", value, start, i)
        elif c == 0x3C:  # <hex>
            start = i
            end = data.find(b">", i)
            if end < 0:
                _refuse()
            digits = re.sub(rb"\s", b"", data[i + 1:end])
            if len(digits) % 2:
                digits += b"0"
            try:
                value = bytes.fromhex(digits.decode("ascii"))
            except ValueError:
                _refuse()
            i = end + 1
            yield _Tok("str", value, start, i)
        elif c in b"[]":
            yield _Tok(chr(c), None, i, i + 1)
            i += 1
        elif c == 0x2F:  # /name
            start = i
            j = i + 1
            while j < n and data[j] not in SPACE and data[j] not in DELIMS:
                j += 1
            yield _Tok("name", data[i + 1:j], start, j)
            i = j
        elif c in DELIMS:
            _refuse()
        else:
            start = i
            j = i
            while j < n and data[j] not in SPACE and data[j] not in DELIMS:
                j += 1
            word = data[i:j]
            i = j
            if NUMBER.fullmatch(word):
                yield _Tok("num", float(word), start, j)
            elif word == b"BI":
                i = _inline_end(data, j)
                yield _Tok("op", b"BI", start, i)
            else:
                yield _Tok("op", word, start, j)


def _read(toks, i):
    """Reads one value that starts at toks[i]. Returns the value and the next index."""
    tok = toks[i]
    if tok.kind in ("[", "<<"):
        close = "]" if tok.kind == "[" else ">>"
        items = []
        i += 1
        while toks[i].kind != close:
            value, i = _read(toks, i)
            items.append(value)
        node = _Tok("arr" if tok.kind == "[" else "dict", items, tok.start, toks[i].end)
        return node, i + 1
    if (tok.kind == "num" and toks[i + 1].kind == "num"
            and toks[i + 2].kind == "op" and toks[i + 2].value == b"R"):
        ref = _Tok("ref", (int(tok.value), int(toks[i + 1].value)), tok.start, toks[i + 2].end)
        return ref, i + 3
    return tok, i + 1


def _instructions(data: bytes):
    """Groups a content stream into operators with their operands."""
    toks = list(_lex(data))
    ins, operands = [], []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok.kind in ("[", "<<"):
            node, i = _read(toks, i)
            operands.append(node)
            continue
        if tok.kind == "op":
            start = operands[0].start if operands else tok.start
            ins.append(_Ins(tok.value, operands, start, tok.end))
            operands = []
        elif tok.kind in ("num", "name", "str"):
            operands.append(tok)
        else:
            _refuse()
        i += 1
    return ins


def _nums(items, count):
    """The last `count` operands, all of them numbers."""
    if len(items) < count:
        _refuse()
    picked = items[-count:]
    if any(t.kind != "num" for t in picked):
        _refuse()
    return [t.value for t in picked]


def _mul(a, b):
    """Row-vector product, the way PDF writes matrices: a first, then b."""
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


# ---------- objects in the file (fonts and their widths) ----------

def _object(doc: fitz.Document, xref: int):
    text = doc.xref_object(xref, compressed=False)
    node, _ = _read(list(_lex(text.encode("latin-1", "replace"))), 0)
    return node


def _deref(doc, node):
    if node is not None and node.kind == "ref":
        return _object(doc, node.value[0])
    return node


def _get(doc, dct, key):
    if dct is None or dct.kind != "dict":
        return None
    items = dct.value
    for k in range(0, len(items) - 1, 2):
        if items[k].kind == "name" and items[k].value == key:
            return _deref(doc, items[k + 1])
    return None


def _number_of(doc, dct, key, default):
    node = _get(doc, dct, key)
    if node is None:
        return default
    if node.kind != "num":
        _refuse()
    return node.value


def _numbers(node):
    if node is None or node.kind != "arr":
        _refuse()
    out = []
    for item in node.value:
        if item.kind != "num":
            _refuse()
        out.append(item.value)
    return out


def _singles(data: bytes):
    return [(i, i + 1, data[i:i + 1]) for i in range(len(data))]


class _Simple:
    """One byte per glyph. Widths come from /Widths, or from the built-in metrics."""

    def __init__(self, doc, font):
        enc = _get(doc, font, b"Encoding")
        self.win_ansi = enc is None or (enc.kind == "name" and enc.value in (b"WinAnsiEncoding", b"StandardEncoding"))
        widths = _get(doc, font, b"Widths")
        self.metrics = None
        self.widths = None
        if widths is not None:
            self.first = int(_number_of(doc, font, b"FirstChar", 0))
            self.widths = _numbers(widths)
        else:
            base = _get(doc, font, b"BaseFont")
            name = base.value.split(b"+", 1)[-1] if base is not None and base.kind == "name" else None
            if name not in BASE14 or not self.win_ansi:
                _refuse()
            self.metrics = fitz.Font(BASE14[name])

    def split(self, data: bytes):
        return _singles(data)

    def width(self, code: bytes) -> float:
        value = code[0]
        if self.widths is not None:
            idx = value - self.first
            return self.widths[idx] if 0 <= idx < len(self.widths) else None
        try:
            char = bytes([value]).decode("cp1252")
        except UnicodeDecodeError:
            return None
        return self.metrics.glyph_advance(ord(char)) * 1000.0

    def char(self, code: bytes):
        if not self.win_ansi:
            return None
        try:
            return code.decode("cp1252")
        except UnicodeDecodeError:
            return None


class _Composite:
    """Two bytes per glyph. Identity-H, or a UTF-16 CMap where the code is the character."""

    def __init__(self, doc, font):
        enc = _get(doc, font, b"Encoding")
        name = enc.value if enc is not None and enc.kind == "name" else None
        if name == b"Identity-H":
            self.unicode = False
        elif name is not None and (name.endswith(b"UTF16-H") or name.endswith(b"UCS2-H")):
            self.unicode = True
        else:
            _refuse()
        desc = _get(doc, font, b"DescendantFonts")
        if desc is None or desc.kind != "arr" or not desc.value:
            _refuse()
        cid = _deref(doc, desc.value[0])
        self.dw = _number_of(doc, cid, b"DW", 1000.0)
        self.cw = {}
        self.ranges = []
        w = _get(doc, cid, b"W")
        if w is not None:
            # Widths are keyed by CID. Only Identity-H maps a code straight to a CID.
            if self.unicode or w.kind != "arr":
                _refuse()
            items = w.value
            i = 0
            while i < len(items):
                if items[i].kind != "num" or i + 1 >= len(items):
                    _refuse()
                first = int(items[i].value)
                nxt = items[i + 1]
                if nxt.kind == "arr":
                    for k, v in enumerate(nxt.value):
                        if v.kind != "num":
                            _refuse()
                        self.cw[first + k] = v.value
                    i += 2
                else:
                    if i + 2 >= len(items) or nxt.kind != "num" or items[i + 2].kind != "num":
                        _refuse()
                    self.ranges.append((first, int(nxt.value), items[i + 2].value))
                    i += 3

    def split(self, data: bytes):
        if len(data) % 2:
            _refuse()
        return [(i, i + 2, data[i:i + 2]) for i in range(0, len(data), 2)]

    def width(self, code: bytes) -> float:
        cid = (code[0] << 8) | code[1]
        if cid in self.cw:
            return self.cw[cid]
        for first, last, value in self.ranges:
            if first <= cid <= last:
                return value
        return self.dw

    def char(self, code: bytes):
        if not self.unicode:
            return None
        value = (code[0] << 8) | code[1]
        if value < 0xD800 or 0xE000 <= value <= 0xFFFF:
            return chr(value)
        return None


def _font_model(doc, xref: int):
    font = _object(doc, xref)
    subtype = _get(doc, font, b"Subtype")
    if subtype is None or subtype.kind != "name":
        _refuse()
    if subtype.value in (b"Type1", b"MMType1", b"TrueType"):
        return _Simple(doc, font)
    if subtype.value == b"Type0":
        return _Composite(doc, font)
    _refuse()


# ---------- where each glyph is drawn ----------

class _Glyph:
    __slots__ = ("origin", "char", "adjust", "known", "tc", "tfs")

    def __init__(self, origin, char, adjust, known, tc=0.0, tfs=0.0):
        self.origin = origin
        self.char = char
        self.adjust = adjust
        self.known = known
        self.tc = tc
        self.tfs = tfs


def _walk(doc, ins_list, font_xrefs, page_matrix):
    """Works out where every glyph is drawn, in the same space as the page text.

    Returns the glyphs, and for each text operator its font model and glyph indexes.
    """
    glyphs = []
    per_ins = {}
    models = {}
    st = {"ctm": IDENTITY, "tc": 0.0, "tw": 0.0, "th": 1.0, "tl": 0.0, "trise": 0.0,
          "tfs": 0.0, "model": None}
    tm = tlm = IDENTITY
    saved = []

    def model_for(name):
        xref = font_xrefs.get(name)
        if xref is None:
            return None
        if xref not in models:
            try:
                models[xref] = _font_model(doc, xref)
            except ValueError:
                models[xref] = None
        return models[xref]

    def show(index, string):
        nonlocal tm
        model = st["model"]
        split = model.split if model is not None else _singles
        indexes = per_ins.setdefault(index, (model, []))[1]
        for start, end, code in split(string):
            space = end - start == 1 and code[0] == 32
            tfs, th = st["tfs"], st["th"]
            trm = _mul((tfs * th, 0, 0, tfs, 0, st["trise"]), tm)
            dev = _mul(_mul(trm, st["ctm"]), page_matrix)
            width = model.width(code) if model is not None else None
            char = model.char(code) if model is not None else None
            # An unknown width leaves this glyph and the ones after it unsure of their place.
            known = width is not None and bool(tfs)
            if width is None:
                width = 0.0
            adjust = None
            if tfs:
                adjust = -(width + (st["tc"] + (st["tw"] if space else 0.0)) * 1000.0 / tfs)
            indexes.append(len(glyphs))
            glyphs.append(_Glyph((dev[4], dev[5]), char, adjust, known, st["tc"], tfs))
            advance = (width / 1000.0 * tfs + st["tc"] + (st["tw"] if space else 0.0)) * th
            tm = _mul((1, 0, 0, 1, advance, 0), tm)

    for index, ins in enumerate(ins_list):
        op = ins.op
        args = ins.operands
        if op == b"q":
            saved.append(dict(st))
        elif op == b"Q":
            if saved:
                st = saved.pop()
        elif op == b"cm":
            st["ctm"] = _mul(tuple(_nums(args, 6)), st["ctm"])
        elif op == b"BT":
            tm = tlm = IDENTITY
        elif op == b"Tc":
            st["tc"] = _nums(args, 1)[0]
        elif op == b"Tw":
            st["tw"] = _nums(args, 1)[0]
        elif op == b"Tz":
            st["th"] = _nums(args, 1)[0] / 100.0
        elif op == b"TL":
            st["tl"] = _nums(args, 1)[0]
        elif op == b"Ts":
            st["trise"] = _nums(args, 1)[0]
        elif op == b"Tf":
            if len(args) < 2 or args[-2].kind != "name":
                _refuse()
            st["model"] = model_for(args[-2].value)
            st["tfs"] = _nums(args, 1)[0]
        elif op == b"Td":
            tx, ty = _nums(args, 2)
            tlm = _mul((1, 0, 0, 1, tx, ty), tlm)
            tm = tlm
        elif op == b"TD":
            tx, ty = _nums(args, 2)
            st["tl"] = -ty
            tlm = _mul((1, 0, 0, 1, tx, ty), tlm)
            tm = tlm
        elif op == b"Tm":
            tlm = tm = tuple(_nums(args, 6))
        elif op == b"T*":
            tlm = _mul((1, 0, 0, 1, 0, -st["tl"]), tlm)
            tm = tlm
        elif op in (b"Tj", b"TJ", b"'", b'"'):
            if op == b'"':
                if len(args) < 3:
                    _refuse()
                st["tw"], st["tc"] = _nums(args[:2], 2)
            if op in (b"'", b'"'):
                tlm = _mul((1, 0, 0, 1, 0, -st["tl"]), tlm)
                tm = tlm
            if op == b"TJ":
                if not args or args[-1].kind != "arr":
                    _refuse()
                for item in args[-1].value:
                    if item.kind == "str":
                        show(index, item.value)
                    elif item.kind == "num":
                        tm = _mul((1, 0, 0, 1, -item.value / 1000.0 * st["tfs"] * st["th"], 0), tm)
                    else:
                        _refuse()
            else:
                if not args or args[-1].kind != "str":
                    _refuse()
                show(index, args[-1].value)
    return glyphs, per_ins


def _walk_page(doc, page):
    """Parses one page: its content bytes, instructions, glyphs and per-operator index."""
    data = page.read_contents()
    ins_list = _instructions(data)
    fonts = {}
    for entry in page.get_fonts():
        name = entry[4].encode("latin-1", "replace") if isinstance(entry[4], str) else entry[4]
        fonts[name] = entry[0]
    glyphs, per_ins = _walk(doc, ins_list, fonts, tuple(page.transformation_matrix))
    return data, ins_list, glyphs, per_ins


def spacing_map(doc: fitz.Document, index: int) -> list:
    """Letter spacing of every glyph on a page, as (origin, 1/1000 em) pairs.

    A page that cannot be read gives an empty list, so lines just keep their defaults.
    """
    try:
        _, _, glyphs, _ = _walk_page(doc, doc[index])
    except Exception:
        return []
    return [(g.origin, round(g.tc / g.tfs * 1000.0)) for g in glyphs if g.tfs]


def _match(targets, glyphs):
    """Pairs each character of the line with the glyph drawn at the same place."""
    buckets = {}
    for gi, g in enumerate(glyphs):
        buckets.setdefault(round(g.origin[1]), []).append(gi)
    chosen = {}
    for char, origin, is_space in targets:
        best = None
        y = round(origin[1])
        for key in (y - 1, y, y + 1):
            for gi in buckets.get(key, ()):
                if gi in chosen:
                    continue
                g = glyphs[gi]
                dx = abs(g.origin[0] - origin[0])
                dy = abs(g.origin[1] - origin[1])
                if dx > MATCH_TOL or dy > MATCH_TOL:
                    continue
                score = dx + dy + (0.0 if g.char in (None, char) else 1.0)
                if best is None or score < best[0]:
                    best = (score, gi)
        if best is None:
            if is_space:
                continue
            _refuse()
        chosen[best[1]] = char
    return chosen


def _fmt(value: float) -> str:
    text = ("%.4f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _rebuild(ins, model, indexes, glyphs, removed):
    """Writes one text operator again as a TJ array.

    A removed glyph becomes a spacing number of the same width, so the glyphs
    after it stay where they were.
    """
    args = ins.operands
    items = args[-1].value if ins.op == b"TJ" else [args[-1]]
    split = model.split if model is not None else _singles
    pieces = []
    it = iter(indexes)
    for item in items:
        if item.kind == "str":
            for start, end, _ in split(item.value):
                gi = next(it)
                if gi in removed:
                    pieces.append(("n", glyphs[gi].adjust))
                else:
                    pieces.append(("b", item.value[start:end]))
        else:
            pieces.append(("n", item.value))
    parts = []
    if ins.op == b'"':
        parts.append("%s Tw %s Tc" % (_fmt(args[-3].value), _fmt(args[-2].value)))
    if ins.op in (b"'", b'"'):
        parts.append("T*")
    body = []
    total = 0.0
    for kind, value in pieces:
        if kind == "n":
            total += value
            continue
        if abs(total) > 1e-9:
            body.append(_fmt(total))
        total = 0.0
        body.append("<%s>" % value.hex())
    if abs(total) > 1e-9:
        body.append(_fmt(total))
    parts.append("[%s] TJ" % " ".join(body))
    return " ".join(parts).encode("latin-1")


# ---------- the page text, before and after ----------

def _find_line(raw, bbox, origin):
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            box = line["bbox"]
            if any(abs(box[k] - bbox[k]) > CHECK_TOL for k in range(4)):
                continue
            for span in line.get("spans", []):
                o = span["origin"]
                if abs(o[0] - origin[0]) <= CHECK_TOL and abs(o[1] - origin[1]) <= CHECK_TOL:
                    return [ch for sp in line["spans"] for ch in sp.get("chars", [])]
    return None


def _visible(raw):
    out = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    if ch["c"].strip():
                        out.append((ch["c"], tuple(ch["origin"])))
    return out


def _take(pool: dict, char: str, origin) -> bool:
    """Removes one character from the pool that sits at origin, within CHECK_TOL."""
    x, y = origin
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            bucket = pool.get((char, round(x) + dx, round(y) + dy), [])
            for k, (ax, ay) in enumerate(bucket):
                if abs(ax - x) <= CHECK_TOL and abs(ay - y) <= CHECK_TOL:
                    bucket.pop(k)
                    return True
    return False


def _same_chars(expected, actual) -> bool:
    if len(expected) != len(actual):
        return False
    pool = {}
    for char, (x, y) in actual:
        pool.setdefault((char, round(x), round(y)), []).append((x, y))
    return all(_take(pool, char, origin) for char, origin in expected)


def _remove_line(doc: fitz.Document, index: int, bbox, origin) -> None:
    page = doc[index]
    raw = page.get_text("rawdict")
    line = _find_line(raw, bbox, origin)
    if line is None:
        _refuse()
    targets = [(ch["c"], tuple(ch["origin"]), not ch["c"].strip()) for ch in line]
    before = _visible(raw)

    data, ins_list, glyphs, per_ins = _walk_page(doc, page)
    chosen = _match(targets, glyphs)
    removed = set(chosen)
    if not removed:
        return
    # MuPDF leaves out a glyph that overprints the one before it, so take
    # those too when they sit on the line's baseline inside its box.
    for model, indexes in per_ins.values():
        if not any(gi in removed for gi in indexes):
            continue
        for gi in indexes:
            g = glyphs[gi]
            if (abs(g.origin[1] - origin[1]) <= MATCH_TOL
                    and bbox[0] - MATCH_TOL <= g.origin[0] <= bbox[2] + MATCH_TOL):
                removed.add(gi)
    for gi in removed:
        if not glyphs[gi].known or glyphs[gi].adjust is None:
            _refuse()

    edits = []
    for ins_index, (model, indexes) in per_ins.items():
        if any(gi in removed for gi in indexes):
            ins = ins_list[ins_index]
            edits.append((ins.start, ins.end, _rebuild(ins, model, indexes, glyphs, removed)))
    edits.sort(key=lambda e: e[0])
    out = bytearray()
    last = 0
    for start, end, text in edits:
        out += data[last:start]
        out += text
        last = end
    out += data[last:]

    xrefs = page.get_contents()
    if not xrefs:
        _refuse()
    doc.update_stream(xrefs[0], bytes(out))
    for xref in xrefs[1:]:
        doc.update_stream(xref, b"")

    expected = list(before)
    for char, pos, is_space in targets:
        if is_space:
            continue
        hit = None
        for k, (c2, o2) in enumerate(expected):
            if c2 == char and abs(o2[0] - pos[0]) <= CHECK_TOL and abs(o2[1] - pos[1]) <= CHECK_TOL:
                hit = k
                break
        if hit is None:
            _refuse()
        expected.pop(hit)
    after = _visible(doc[index].get_text("rawdict"))
    if not _same_chars(expected, after):
        _refuse()


def remove_line(doc: fitz.Document, index: int, bbox, origin) -> None:
    """Takes the line at bbox and origin off page `index`.

    Raises ValueError when that cannot be done without touching other text.
    """
    if not origin or len(origin) != 2 or not bbox or len(bbox) != 4:
        _refuse()
    try:
        _remove_line(doc, index, bbox, origin)
    except ValueError:
        raise
    except Exception:
        _refuse()
