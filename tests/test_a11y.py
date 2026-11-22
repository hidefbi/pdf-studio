"""Keyboard use of the dialogs and the file buttons."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import expect

LOCALES = Path(__file__).resolve().parent.parent / "static" / "locales"


def test_escape_closes_dialog_and_returns_focus(ui, server):
    page = ui.page
    page.click("#about-open")
    expect(page.locator("#about-dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#about-dialog")).to_be_hidden()
    assert page.evaluate("() => document.activeElement.id") == "about-open"


def test_tab_stays_inside_open_dialog(ui, server):
    page = ui.page
    page.click("#about-open")
    expect(page.locator("#about-dialog")).to_be_visible()
    for _ in range(25):
        page.keyboard.press("Tab")
        inside = page.evaluate("() => !!document.activeElement.closest('#about-dialog')")
        assert inside, "focus left the dialog"
    page.keyboard.press("Escape")
    expect(page.locator("#about-dialog")).to_be_hidden()


def test_open_and_merge_are_real_buttons(ui, server):
    page = ui.page
    for sel in ("#open-pick", "#merge-pick"):
        assert page.evaluate(f"() => document.querySelector('{sel}').tagName") == "BUTTON"
    with page.expect_file_chooser():
        page.click("#open-pick")


def test_icon_labels_follow_language(ui, server):
    page = ui.page
    page.select_option("#lang", "ja")
    ja = json.loads((LOCALES / "ja.json").read_text(encoding="utf-8"))
    expect(page.locator("#lang")).to_have_attribute("aria-label", ja["language"])
    expect(page.locator("#font")).to_have_attribute("aria-label", ja["font_family"])
    page.select_option("#lang", "en")
    expect(page.locator("#font")).to_have_attribute("aria-label", "Font")
