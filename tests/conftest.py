"""Starts one PDF Studio server per test session, and a browser page per UI test."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Server:
    base: str
    data_dir: Path


@dataclass
class UI:
    page: object
    errors: list


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def server(tmp_path_factory) -> Server:
    port = _free_port()
    data_dir = tmp_path_factory.mktemp("data")
    log = open(data_dir / "server.log", "wb")
    env = dict(os.environ, PDF_STUDIO_DATA=str(data_dir), PDF_STUDIO_NO_WATCHDOG="1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=log, stderr=log,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(base + "/api/identity", timeout=1) as res:
                if b"pdf-studio" in res.read():
                    break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("server did not start; see " + str(data_dir / "server.log"))
    yield Server(base=base, data_dir=data_dir)
    proc.terminate()
    proc.wait(timeout=10)
    log.close()


def _browser_ui(server: Server, width: int, height: int):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=2)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append(msg.text) if "Content Security Policy" in msg.text else None)
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(server.base + "/")
        page.wait_for_selector("#empty:not([hidden])")
        yield UI(page=page, errors=errors)
        browser.close()


@pytest.fixture
def ui(server):
    yield from _browser_ui(server, 1200, 900)


@pytest.fixture
def ui_small(server):
    yield from _browser_ui(server, 1000, 760)


@pytest.fixture
def encrypted_pdf(tmp_path) -> Path:
    path = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    doc[0].insert_text((72, 100), "Secret body text", fontsize=14)
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    doc.close()
    return path


@pytest.fixture
def annotated_pdf(tmp_path) -> Path:
    path = tmp_path / "note.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    annot = page.add_text_annot((100, 100), "first note")
    annot.set_info(content="first note")
    annot.update()
    doc.save(path)
    doc.close()
    return path
