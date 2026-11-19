"""Browser tests for inline editing: font choice, click-away save, clipboard."""
from __future__ import annotations

from support import click_line, fixture, fonts_with, open_file, saved_pdf, saved_text


def count_text(base, doc, token):
    return saved_text(base, doc).count(token)


def test_click_away_saves_open_edit_with_chosen_font(ui, server):
    doc = open_file(ui.page, fixture("embedded.pdf"))
    click_line(ui.page, "Embedded line one")
    ui.page.select_option("#font", "tiro")
    ui.page.wait_for_timeout(1000)
    box = ui.page.locator(".tl-box[title*='Second embedded']").bounding_box()
    ui.page.mouse.dblclick(box["x"] + 20, box["y"] + box["height"] / 2)
    ui.page.wait_for_timeout(400)
    ui.page.keyboard.press("End")
    ui.page.keyboard.type(" Z")
    ui.page.wait_for_timeout(100)
    other = ui.page.locator(".tl-box[title*='Helvetica plain']").bounding_box()
    ui.page.mouse.click(other["x"] + 20, other["y"] + other["height"] / 2)
    ui.page.wait_for_timeout(1000)
    pdf = saved_pdf(server.base, doc)
    assert " ".join(w[4] for w in pdf[0].get_text("words")).count("Second embedded line Z") == 1
    assert any("Times" in f for f in fonts_with(pdf, "Second embedded line Z"))
    assert ui.page.locator(".tl-edit").count() == 0
    assert not ui.errors


def test_enter_without_text_change_still_applies_font(ui, server):
    doc = open_file(ui.page, fixture("embedded.pdf"))
    ui.page.select_option("#font", "cour")
    ui.page.wait_for_timeout(900)
    box = ui.page.locator(".tl-box[title*='Embedded line one']").bounding_box()
    ui.page.mouse.dblclick(box["x"] + 20, box["y"] + box["height"] / 2)
    ui.page.wait_for_timeout(400)
    ui.page.keyboard.press("Enter")
    ui.page.wait_for_timeout(1000)
    assert any("Cour" in f for f in fonts_with(saved_pdf(server.base, doc), "Embedded line one here"))


def test_copy_paste_at_pointer_undo_and_cut(ui, server):
    doc = open_file(ui.page, fixture("embedded.pdf"))
    ui.page.select_option("#font", "auto")
    ui.page.wait_for_timeout(500)
    click_line(ui.page, "Helvetica plain")
    ui.page.keyboard.press("Control+c")
    ui.page.wait_for_timeout(200)
    img = ui.page.locator("#page-img").bounding_box()
    tx, ty = img["x"] + img["width"] * 0.6, img["y"] + img["height"] * 0.85
    ui.page.mouse.move(tx, ty)
    ui.page.wait_for_timeout(150)
    ui.page.keyboard.press("Control+v")
    ui.page.wait_for_timeout(1200)
    assert count_text(server.base, doc, "Helvetica plain line") == 2

    pdf = saved_pdf(server.base, doc)
    ys = sorted(w[1] for w in pdf[0].get_text("words") if w[4] == "plain")
    want = (ty - img["y"]) / img["height"] * pdf[0].rect.height
    assert len(ys) == 2 and abs(ys[1] - want) < 40, (want, ys)
    assert ui.page.locator(".tl-box.selected").count() >= 1

    ui.page.keyboard.press("Escape")
    ui.page.keyboard.press("Control+z")
    ui.page.wait_for_timeout(1000)
    assert count_text(server.base, doc, "Helvetica plain line") == 1

    click_line(ui.page, "Embedded line one here")
    ui.page.keyboard.press("Control+x")
    ui.page.wait_for_timeout(1000)
    assert count_text(server.base, doc, "Embedded line one here") == 0
    assert ui.page.locator(".tl-box.selected").count() == 0
    ui.page.mouse.move(tx, ty)
    ui.page.wait_for_timeout(150)
    ui.page.keyboard.press("Control+v")
    ui.page.wait_for_timeout(1000)
    assert count_text(server.base, doc, "Embedded line one here") == 1

    before = count_text(server.base, doc, "Helvetica plain line")
    ui.page.click("#search-input")
    ui.page.keyboard.press("Control+v")
    ui.page.wait_for_timeout(800)
    assert count_text(server.base, doc, "Helvetica plain line") == before
    assert not ui.errors


def test_font_choice_sticks_and_applies_to_edits_moves_and_undo(ui, server):
    doc = open_file(ui.page, fixture("embedded.pdf"))
    click_line(ui.page, "Embedded line one")
    ui.page.select_option("#font", "tiro")
    ui.page.wait_for_timeout(1200)
    assert any("Times" in f for f in fonts_with(saved_pdf(server.base, doc), "Embedded line one"))

    click_line(ui.page, "Second embedded")
    assert ui.page.evaluate("() => document.querySelector('#font').value") == "tiro"

    box = ui.page.locator(".tl-box[title*='Second embedded']").bounding_box()
    ui.page.mouse.dblclick(box["x"] + 20, box["y"] + box["height"] / 2)
    ui.page.wait_for_timeout(500)
    ui.page.keyboard.press("End")
    ui.page.keyboard.type(" X")
    ui.page.keyboard.press("Enter")
    ui.page.wait_for_timeout(1200)
    assert any("Times" in f for f in fonts_with(saved_pdf(server.base, doc), "Second embedded line X"))

    click_line(ui.page, "Second embedded line X")
    ui.page.locator("#style-bar [data-act='larger']").click()
    ui.page.wait_for_timeout(1200)
    assert any("Times" in f for f in fonts_with(saved_pdf(server.base, doc), "Second embedded line X"))

    click_line(ui.page, "Embedded line one")
    ui.page.locator("#style-bar [data-act='bold']").click()
    ui.page.wait_for_timeout(1200)
    assert any("Times" in f and "Bold" in f for f in fonts_with(saved_pdf(server.base, doc), "Embedded line one"))

    before = fonts_with(saved_pdf(server.base, doc), "Helvetica plain")
    box = click_line(ui.page, "Helvetica plain")
    ui.page.mouse.move(box["x"] + 30, box["y"] + box["height"] / 2)
    ui.page.mouse.down()
    ui.page.mouse.move(box["x"] + 90, box["y"] + box["height"] / 2, steps=6)
    ui.page.mouse.up()
    ui.page.wait_for_timeout(1200)
    after = fonts_with(saved_pdf(server.base, doc), "Helvetica plain")
    assert before == after and after and all("Helv" in f or "Arial" in f for f in after), after

    ui.page.select_option("#font", "auto")
    ui.page.wait_for_timeout(300)
    click_line(ui.page, "Second embedded line X")
    assert ui.page.evaluate("() => document.querySelector('#font').value") == "auto"

    click_line(ui.page, "Helvetica plain")
    ui.page.select_option("#font", "cour")
    ui.page.wait_for_timeout(1200)
    assert any("Cour" in f for f in fonts_with(saved_pdf(server.base, doc), "Helvetica plain"))
    ui.page.locator("#undo").click()
    ui.page.wait_for_timeout(1200)
    assert any("Helv" in f for f in fonts_with(saved_pdf(server.base, doc), "Helvetica plain"))
    assert not ui.errors


def test_spacing_steppers_set_kerning_and_leading_in_browser(ui, server):
    doc = open_file(ui.page, fixture("multi.pdf"))
    ui.page.click("[data-tool='text']")
    ui.page.wait_for_timeout(200)
    img = ui.page.locator("#page-img").bounding_box()
    pw = ui.page.evaluate("() => window.pdfStudio.state.info.pages[0].width")
    ph = ui.page.evaluate("() => window.pdfStudio.state.info.pages[0].height")

    def at(x, y):
        return img["x"] + x / pw * img["width"], img["y"] + y / ph * img["height"]

    def draw(y0, y1):
        x0, y0s = at(60, y0)
        x1, y1s = at(260, y1)
        ui.page.mouse.move(x0, y0s)
        ui.page.mouse.down()
        ui.page.mouse.move(x1, y1s, steps=5)
        ui.page.mouse.up()
        ui.page.wait_for_timeout(300)

    draw(80, 110)
    ui.page.keyboard.type("Plain")
    ui.page.keyboard.press("Enter")
    ui.page.wait_for_timeout(900)

    draw(160, 190)
    ui.page.keyboard.type("Line1")
    ui.page.keyboard.press("Shift+Enter")
    ui.page.keyboard.type("Line2")
    assert ui.page.locator(".tl-step").count() == 2
    leading_input = ui.page.locator("[data-field='leading'] input")
    assert leading_input.input_value() == ""  # automatic at first
    ui.page.locator("[data-field='kerning'] button[data-step='1']").click()
    ui.page.locator("[data-field='kerning'] button[data-step='1']").click()
    assert ui.page.locator("[data-field='kerning'] input").input_value() == "20"  # two steps of 10
    spacing = ui.page.locator(".tl-edit").evaluate("el => parseFloat(getComputedStyle(el).letterSpacing)")
    assert spacing > 0
    leading_input.fill("30")
    ui.page.wait_for_timeout(200)
    line_height = ui.page.locator(".tl-edit").evaluate("el => parseFloat(getComputedStyle(el).lineHeight)")
    assert line_height > 0
    ui.page.keyboard.press("Enter")
    ui.page.wait_for_timeout(1000)

    pdf = saved_pdf(server.base, doc)
    words = pdf[0].get_text("words")
    assert "Plain" in [w[4] for w in words]
    tops = {w[4]: w[1] for w in words}
    assert abs((tops["Line2"] - tops["Line1"]) - 30) < 0.5, (tops["Line1"], tops["Line2"])
    assert ui.page.locator(".tl-edit").count() == 0
    assert not ui.errors


def test_spacing_row_follows_the_editor_bottom(ui, server):
    page = ui.page
    open_file(page, fixture("multi.pdf"))
    page.locator(".tl-box[title*='Billing']").first.dblclick()
    page.wait_for_timeout(300)
    for _ in range(3):
        page.keyboard.press("Shift+Enter")
    page.keyboard.type("more text")
    page.wait_for_timeout(200)
    ed = page.locator(".tl-edit").bounding_box()
    tools = page.locator(".tl-tools").bounding_box()
    assert abs(tools["y"] - (ed["y"] + ed["height"] + 4)) < 3
    cancel_bg = page.locator(".tl-tools .cancel").evaluate("el => getComputedStyle(el).backgroundColor")
    assert cancel_bg == "rgb(198, 40, 40)"
    step_bg = page.locator(".tl-step-btn").first.evaluate("el => getComputedStyle(el).backgroundColor")
    assert step_bg != "rgba(0, 0, 0, 0)"
