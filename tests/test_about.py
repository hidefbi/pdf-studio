"""The About dialog: version, the two links, and the donation cards."""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import expect

from support import call

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.version import VERSION  # noqa: E402


def test_version_endpoint(server):
    status, body = call(server.base, "GET", "/api/version")
    assert status == 200 and body == {"version": VERSION}


def test_about_dialog_shows_version_links_and_copy_cards(ui, server):
    page = ui.page
    page.click("#about-open")
    expect(page.locator("#about-dialog")).to_be_visible()
    expect(page.locator("#about-version")).to_contain_text(VERSION)

    assert page.get_attribute("#about-dialog a[href$='/releases']", "href") == \
        "https://github.com/hidefbi/pdf-studio/releases"
    assert page.get_attribute("#about-dialog a[href$='/issues']", "href") == \
        "https://github.com/hidefbi/pdf-studio/issues"

    card = page.locator(".donate-card[data-copy^='bc1']")
    before = card.locator(".copy-state").inner_text()
    card.click()
    # Headless Chromium may refuse the clipboard, so either outcome is fine: the text changes.
    expect(card.locator(".copy-state")).not_to_have_text(before)

    page.click("#about-close")
    expect(page.locator("#about-dialog")).to_be_hidden()
    assert not ui.errors
