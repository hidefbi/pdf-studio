"""Kerning (letter gap) and line spacing (leading), through the API."""
from __future__ import annotations

import pymupdf

from support import call, doc_id_of, fixture, saved_pdf

FREE_RECT = [400, 600, 560, 640]  # free area of multi.pdf, away from its text
CHINESE = "".join(chr(c) for c in (0x4E2D, 0x6587, 0x5B57, 0x7B26))  # four Chinese characters


def ops(base, doc, body):
    return call(base, "POST", f"/api/docs/{doc}/ops", {"ops": [body]})


def word_rect(base, doc, token):
    pdf = saved_pdf(base, doc)
    try:
        for w in pdf[0].get_text("words"):
            if w[4] == token:
                return pymupdf.Rect(w[:4])
    finally:
        pdf.close()
    raise AssertionError(f"word not found: {token}")


def char_origins(base, doc, rect):
    pdf = saved_pdf(base, doc)
    try:
        out = []
        for b in pdf[0].get_text("rawdict")["blocks"]:
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        x0, y0, x1, y1 = ch["bbox"]
                        if rect.contains(pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)):
                            out.append((ch["c"], ch["origin"][0]))
        return out
    finally:
        pdf.close()


def gaps(chars):
    xs = [x for _, x in chars]
    return [b - a for a, b in zip(xs, xs[1:])]


def test_kerning_adds_gap_after_each_character_and_stops_there(server):
    plain = doc_id_of(server.base, fixture("multi.pdf"))
    spaced = doc_id_of(server.base, fixture("multi.pdf"))
    body = {"type": "text", "page": 0, "rect": FREE_RECT, "text": "12345678", "size": 12, "color": [0, 0, 0]}
    after = {"type": "text", "page": 0, "rect": [400, 660, 560, 680], "text": "after", "size": 12, "color": [0, 0, 0]}
    assert ops(server.base, plain, dict(body, tracking=0))[0] == 200
    assert ops(server.base, plain, after)[0] == 200
    assert ops(server.base, spaced, dict(body, tracking=250))[0] == 200  # 250/1000 em = 3 pt at 12 pt
    assert ops(server.base, spaced, after)[0] == 200

    rect = pymupdf.Rect(*FREE_RECT)
    # Readers may add synthetic space characters at wide gaps, so compare the glyphs only.
    a = [(c, x) for c, x in char_origins(server.base, plain, rect) if c != " "]
    b = [(c, x) for c, x in char_origins(server.base, spaced, rect) if c != " "]
    assert [c for c, _ in a] == list("12345678") == [c for c, _ in b]
    step = 250 / 1000 * 12
    for k, ((_, pa), (_, pb)) in enumerate(zip(a, b)):
        assert abs((pb - pa) - step * k) < 0.1, (k, pa, pb)
    # The operator belongs to its own run, so text written afterwards is unchanged.
    after_rect = pymupdf.Rect(400, 660, 560, 680)
    assert char_origins(server.base, plain, after_rect) == char_origins(server.base, spaced, after_rect)


def test_kerning_works_for_chinese_text(server):
    plain = doc_id_of(server.base, fixture("multi.pdf"))
    spaced = doc_id_of(server.base, fixture("multi.pdf"))
    body = {"type": "text", "page": 0, "rect": FREE_RECT, "text": CHINESE, "size": 12, "color": [0, 0, 0]}
    assert ops(server.base, plain, dict(body, tracking=0))[0] == 200
    assert ops(server.base, spaced, dict(body, tracking=150))[0] == 200  # 1.8 pt at 12 pt
    rect = pymupdf.Rect(*FREE_RECT)
    a, b = char_origins(server.base, plain, rect), char_origins(server.base, spaced, rect)
    assert len(a) == len(CHINESE) == len(b)
    for pa, pb in zip(gaps(a), gaps(b)):
        assert abs((pb - pa) - 1.8) < 0.1, (pa, pb)


def test_kerning_applies_to_an_edited_line(server):
    plain = doc_id_of(server.base, fixture("multi.pdf"))
    spaced = doc_id_of(server.base, fixture("multi.pdf"))
    line = next(ln for ln in call(server.base, "GET", f"/api/docs/{plain}/pages/0/lines")[1]["lines"]
                if ln["text"].startswith("Row item 3 "))
    body = {
        "type": "replace_span", "page": 0, "rect": line["bbox"], "origin": line["origin"],
        "text": line["text"], "font": "auto", "font_xref": line["font_xref"],
        "base_font": line["base_font"], "size": line["size"], "color": [0, 0, 0],
        "align": "left", "block": line["block"],
    }
    tracking = 500  # half an em
    assert ops(server.base, plain, dict(body, tracking=0))[0] == 200
    assert ops(server.base, spaced, dict(body, tracking=tracking))[0] == 200
    # The spaced line runs longer, so look wider. Spaces are skipped: PDF readers add
    # synthetic space characters where the gaps are large, which is not a glyph shift.
    x0, y0, _, y1 = line["bbox"]
    rect = pymupdf.Rect(x0 - 2, y0 - 2, x0 + 400, y1 + 2)
    a = [(c, x) for c, x in char_origins(server.base, plain, rect) if c != " "]
    b = [(c, x) for c, x in char_origins(server.base, spaced, rect) if c != " "]
    chars = [ch for ch in line["text"] if ch != " "]
    # Character k in the line moves by one gap per earlier character.
    index = [k for k, ch in enumerate(line["text"]) if ch != " "]
    step = tracking / 1000 * line["size"]
    assert [c for c, _ in a] == chars == [c for c, _ in b] and len(chars) > 10
    for (_, pa), (_, pb), k in zip(a, b, index):
        assert abs((pb - pa) - step * k) < 0.5, (k, pa, pb)


def test_kerning_outside_the_allowed_range_is_rejected(server):
    doc = doc_id_of(server.base, fixture("multi.pdf"))
    body = {"type": "text", "page": 0, "rect": FREE_RECT, "text": "Tight", "size": 12, "color": [0, 0, 0]}
    assert ops(server.base, doc, dict(body, tracking=1500))[0] == 400
    assert ops(server.base, doc, dict(body, tracking=-300))[0] == 400
    assert "Tight" not in " ".join(w[4] for w in saved_pdf(server.base, doc)[0].get_text("words"))


def line_tops(base, doc, tokens):
    pdf = saved_pdf(base, doc)
    try:
        words = pdf[0].get_text("words")
    finally:
        pdf.close()
    return [next(w[1] for w in words if w[4] == token) for token in tokens]


def test_leading_sets_the_distance_between_lines(server):
    doc = doc_id_of(server.base, fixture("multi.pdf"))
    body = {"type": "text", "page": 0, "rect": FREE_RECT, "text": "Alpha\nBeta\nGamma", "size": 12,
            "color": [0, 0, 0], "leading": 30}
    assert ops(server.base, doc, body)[0] == 200
    tops = line_tops(server.base, doc, ["Alpha", "Beta", "Gamma"])
    assert abs((tops[1] - tops[0]) - 30) < 0.5
    assert abs((tops[2] - tops[1]) - 30) < 0.5


def test_automatic_leading_is_the_size_times_1_2(server):
    doc = doc_id_of(server.base, fixture("multi.pdf"))
    body = {"type": "text", "page": 0, "rect": FREE_RECT, "text": "Alpha\nBeta", "size": 12, "color": [0, 0, 0]}
    assert ops(server.base, doc, body)[0] == 200
    tops = line_tops(server.base, doc, ["Alpha", "Beta"])
    assert abs((tops[1] - tops[0]) - 12 * 1.2) < 0.5


def test_leading_outside_the_allowed_range_is_rejected(server):
    doc = doc_id_of(server.base, fixture("multi.pdf"))
    body = {"type": "text", "page": 0, "rect": FREE_RECT, "text": "Narrow", "size": 12, "color": [0, 0, 0]}
    assert ops(server.base, doc, dict(body, leading=0.5))[0] == 400
    assert ops(server.base, doc, dict(body, leading=300))[0] == 400
    assert "Narrow" not in " ".join(w[4] for w in saved_pdf(server.base, doc)[0].get_text("words"))
