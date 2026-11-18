"""Security headers, no browser cache for page images, and short error texts."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from support import doc_id_of, fixture, upload


def get_headers(base, path):
    with urllib.request.urlopen(base + path) as res:
        return res.headers


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


def test_pages_get_security_headers(server):
    for path in ("/", "/api/identity"):
        headers = get_headers(server.base, path)
        csp = headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "camera=()" in headers["Permissions-Policy"]


def test_page_images_are_not_cached(server):
    doc = doc_id_of(server.base, fixture("align.pdf"))
    assert get_headers(server.base, f"/api/docs/{doc}/pages/0.png").get("Cache-Control") == "no-store"


def test_unreadable_pdf_error_is_short(server, tmp_path):
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"this is not a pdf")
    status, body = upload(server.base, junk)
    assert status == 400
    assert body["detail"] == "not a readable PDF"


def test_invalid_font_error_is_short(server):
    status, body = post_font(server.base, b"not a font at all")
    assert status == 400
    assert body["detail"] == "invalid font file"
