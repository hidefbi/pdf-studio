"""Writes need the app header and a local Origin. Reads stay open."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from support import call, doc_id_of, fixture


def status_of(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status
    except urllib.error.HTTPError as err:
        return err.code


def multipart_status(base, path, headers=None):
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="x.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + fixture("align.pdf").read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(base + path, data=body, method="POST", headers=headers or {})
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status
    except urllib.error.HTTPError as err:
        return err.code


def test_upload_without_header_is_refused(server):
    assert multipart_status(server.base, "/api/docs") == 403


def test_font_upload_without_header_is_refused(server):
    assert multipart_status(server.base, "/api/fonts") == 403


def test_undo_without_header_is_refused(server):
    doc = doc_id_of(server.base, fixture("align.pdf"))
    assert status_of(server.base, "POST", f"/api/docs/{doc}/undo") == 403


def test_delete_without_header_is_refused(server):
    doc = doc_id_of(server.base, fixture("align.pdf"))
    assert status_of(server.base, "DELETE", f"/api/docs/{doc}") == 403
    assert status_of(server.base, "GET", f"/api/docs/{doc}") == 200


def test_heartbeat_without_header_is_refused(server):
    assert status_of(server.base, "POST", "/api/heartbeat", {"id": "x"}) == 403


def test_other_origin_is_refused_even_with_header(server):
    doc = doc_id_of(server.base, fixture("align.pdf"))
    headers = {"X-PDF-Studio": "1", "Origin": "https://evil.example"}
    assert status_of(server.base, "POST", f"/api/docs/{doc}/undo", headers=headers) == 403


def test_lookalike_origin_is_refused(server):
    headers = {"X-PDF-Studio": "1", "Origin": "http://127.0.0.1.evil.example"}
    assert status_of(server.base, "POST", "/api/heartbeat", {"id": "x"}, headers=headers) == 403


def test_local_origin_with_header_is_allowed(server):
    for origin in ("http://127.0.0.1:8000", "http://localhost", "http://localhost:5173"):
        headers = {"X-PDF-Studio": "1", "Origin": origin}
        assert status_of(server.base, "POST", "/api/heartbeat", {"id": "x"}, headers=headers) == 200


def test_app_calls_with_header_work(server):
    status, body = call(server.base, "POST", "/api/heartbeat", {"id": "x"})
    assert status == 200 and body == {"ok": True}
