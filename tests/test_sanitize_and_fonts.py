"""Scripts and launch actions are dropped on import, and font files get a structure check."""
from __future__ import annotations

import json
import struct
import urllib.error
import urllib.request
import uuid

import pymupdf

from support import call, fixture, upload


def make_active_pdf(folder):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "ACTIVE BODY TEXT")
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 200, 200, 220),
                      "uri": "https://example.com/"})
    note = page.add_text_annot((72, 300), "note")
    js = doc.get_new_xref()
    doc.update_object(js, "<< /S /JavaScript /JS (app.alert('hi')) >>")
    launch = doc.get_new_xref()
    doc.update_object(launch, "<< /S /Launch /F << /F (calc.exe) >> >>")
    names = doc.get_new_xref()
    doc.update_object(names, f"<< /JavaScript << /Names [(s) {js} 0 R] >> >>")
    cat = doc.pdf_catalog()
    doc.xref_set_key(cat, "OpenAction", f"{js} 0 R")
    doc.xref_set_key(cat, "AA", f"<< /WC {launch} 0 R >>")
    doc.xref_set_key(cat, "Names", f"{names} 0 R")
    doc.xref_set_key(note.xref, "A", f"{js} 0 R")
    doc.xref_set_key(note.xref, "AA", f"<< /E {launch} 0 R >>")
    path = folder / "active.pdf"
    doc.save(path)
    doc.close()
    return path


def object_texts(data: bytes | None = None, path=None):
    doc = pymupdf.open(stream=data, filetype="pdf") if data else pymupdf.open(path)
    texts = [doc.xref_object(x, compressed=False) for x in range(1, doc.xref_length())]
    doc.close()
    return texts


def test_scripts_and_launch_actions_are_removed(server, tmp_path):
    status, body = upload(server.base, make_active_pdf(tmp_path))
    assert status == 200, body
    texts = object_texts(path=server.data_dir / "docs" / body["id"] / "current.pdf")
    assert not any("/JavaScript" in t or "/Launch" in t for t in texts)
    assert any("/URI" in t for t in texts)


def test_export_has_no_scripts_either(server, tmp_path):
    status, body = upload(server.base, make_active_pdf(tmp_path))
    assert status == 200, body
    status, exported = call(server.base, "GET", f"/api/docs/{body['id']}/export/pdf")
    assert status == 200
    texts = object_texts(data=exported)
    assert not any("/JavaScript" in t or "/Launch" in t for t in texts)
    assert any("/URI" in t for t in texts)


def post_font(base, data):
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="x.ttf"\r\n'
        "Content-Type: font/ttf\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(base + "/api/fonts", data=body, method="POST",
                                 headers={"X-PDF-Studio": "1"})
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_font_with_bad_table_count_is_refused(server):
    data = b"\x00\x01\x00\x00" + struct.pack(">H", 60000) + b"\x00" * 100
    status, body = post_font(server.base, data)
    assert status == 400 and body["detail"] == "invalid font file"


def test_font_with_table_past_end_is_refused(server):
    entry = b"glyf" + b"\x00" * 4 + struct.pack(">II", 0xFFFFFF, 0xFFFFFF)
    data = b"\x00\x01\x00\x00" + struct.pack(">HHHH", 1, 0, 0, 0) + entry
    status, body = post_font(server.base, data)
    assert status == 400 and body["detail"] == "invalid font file"


def test_real_font_is_still_accepted(server):
    doc = pymupdf.open(str(fixture("embedded.pdf")))
    ttf = None
    for page in doc:
        for font in page.get_fonts(full=True):
            if font[1] == "ttf" and ttf is None:
                ttf = doc.extract_font(font[0])[3]
    doc.close()
    assert ttf
    status, body = post_font(server.base, ttf)
    assert status == 200, body
