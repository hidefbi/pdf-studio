"""Browser tests for document-level controls: undo/redo, delete, leaving, and the tool dialogs."""
from __future__ import annotations

from support import call, fixture, open_file


def page_state(page):
    return page.evaluate("() => ({ undo: window.pdfStudio.state.info.undo_steps, redo: window.pdfStudio.state.info.redo_steps })")


def test_undo_redo_buttons_and_shortcuts(ui, server):
    page = ui.page
    open_file(page, fixture("embedded.pdf"))
    assert page.is_disabled("#redo")
    assert page.is_enabled("#delete-doc")

    page.click("#rotate")
    page.wait_for_timeout(600)
    page.click("#undo")
    page.wait_for_timeout(600)
    assert page.is_enabled("#redo")
    page.click("#redo")
    page.wait_for_timeout(600)
    assert page.is_disabled("#redo")

    page.click("#undo")
    page.wait_for_timeout(600)
    page.keyboard.press("Control+Shift+Z")
    page.wait_for_timeout(600)
    assert page.is_disabled("#redo")
    page.keyboard.press("Control+Z")
    page.wait_for_timeout(600)
    assert page.is_enabled("#redo")
    page.keyboard.press("Control+Y")
    page.wait_for_timeout(600)
    assert page.is_disabled("#redo")
    assert not ui.errors


def test_unconfirmed_edit_asks_before_leaving(ui, server):
    page = ui.page
    open_file(page, fixture("embedded.pdf"))
    box = page.locator(".tl-box[title*='Embedded line one']").bounding_box()
    page.mouse.dblclick(box["x"] + 20, box["y"] + box["height"] / 2)
    page.wait_for_timeout(500)
    page.keyboard.type(" extra")
    page.wait_for_timeout(200)
    check = "() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented; }"
    assert page.evaluate(check) is True
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    assert page.evaluate(check) is False


def test_reload_restores_and_delete_clears(ui, server):
    page = ui.page
    doc = open_file(page, fixture("embedded.pdf"))
    page.reload()
    page.wait_for_selector("#stage:not([hidden])")
    page.wait_for_timeout(900)
    assert page.evaluate("() => localStorage.getItem('pdfstudio.doc')") == doc

    page.click("#delete-doc")
    page.wait_for_timeout(800)
    assert page.is_visible("#empty") and not page.is_visible("#stage")
    assert page.evaluate("localStorage.getItem('pdfstudio.doc')") is None
    assert page.is_disabled("#delete-doc")
    assert call(server.base, "GET", f"/api/docs/{doc}")[0] == 404


def test_header_footer_dialog_applies_to_pages(ui, server):
    page = ui.page
    doc = open_file(page, fixture("embedded.pdf"))
    page.click("#insert-blank")
    page.wait_for_timeout(900)
    page.click("#stamp-open")
    page.wait_for_timeout(300)
    assert page.is_visible("#stamp-dialog")
    assert page.input_value("#st-text") == "{page} / {total}"
    page.select_option("#st-where", "top-right")
    page.fill("#st-text", "Report {name}")
    page.click("#stamp-form button[type=submit]")
    page.wait_for_timeout(900)
    assert not page.is_visible("#stamp-dialog")
    assert "Added to pages" in page.inner_text("#toast")
    info = call(server.base, "GET", f"/api/docs/{doc}")[1]
    assert len(info["pages"]) == 2


def test_bookmark_dialog_saves_to_server(ui, server):
    page = ui.page
    doc = open_file(page, fixture("embedded.pdf"))
    page.click("#toc-open")
    page.wait_for_timeout(500)
    assert page.is_visible("#toc-dialog")
    assert "No bookmarks" in page.inner_text("#toc-rows")
    page.click("#toc-add")
    page.wait_for_timeout(200)
    page.fill("#toc-rows .row input.grow", "Chapter one")
    page.click("#toc-save")
    page.wait_for_timeout(700)
    assert not page.is_visible("#toc-dialog")
    titles = [item["title"] for item in call(server.base, "GET", f"/api/docs/{doc}/toc")[1]["items"]]
    assert "Chapter one" in titles


def test_comment_dialog_edits_and_deletes(ui, server, annotated_pdf):
    page = ui.page
    doc = open_file(page, annotated_pdf)
    page.click("#annots-open")
    page.wait_for_timeout(600)
    assert page.locator("#annots-rows .row").count() == 1
    page.fill("#annots-rows .row input.grow", "changed in ui")
    page.locator("#annots-rows .row button", has_text="Save").click()
    page.wait_for_timeout(900)
    items = call(server.base, "GET", f"/api/docs/{doc}/annotations")[1]["items"]
    assert items[0]["content"] == "changed in ui"
    page.locator("#annots-rows .row button", has_text="Delete").click()
    page.wait_for_timeout(900)
    assert call(server.base, "GET", f"/api/docs/{doc}/annotations")[1]["items"] == []
    assert "no comments" in page.inner_text("#annots-rows").lower()
    page.click("#annots-close")


def test_locked_pdf_asks_for_password(ui, server, encrypted_pdf):
    page = ui.page
    page.set_input_files("#file-input", encrypted_pdf)
    page.wait_for_timeout(700)
    assert page.is_visible("#password-dialog")
    page.fill("#pw-input", "nope")
    page.press("#pw-input", "Enter")
    page.wait_for_timeout(700)
    assert page.is_visible("#password-dialog")
    assert "Wrong password" in page.inner_text("#pw-hint")
    page.fill("#pw-input", "secret")
    page.press("#pw-input", "Enter")
    page.wait_for_timeout(1000)
    assert page.is_visible("#stage") and not page.is_visible("#password-dialog")
    assert "/ 2" in page.inner_text("#page-label")

    page.set_input_files("#file-input", encrypted_pdf)
    page.wait_for_timeout(700)
    page.click("#pw-cancel")
    page.wait_for_timeout(500)
    assert "Opening cancelled" in page.inner_text("#toast")
    assert not page.is_visible("#password-dialog")
    assert not ui.errors
