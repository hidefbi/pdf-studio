"""Browser tests for selection, group actions, alignment and the replace tool."""
from __future__ import annotations

from collections import OrderedDict

from support import call, fixture, open_file


def lines_of(base, doc):
    return call(base, "GET", f"/api/docs/{doc}/pages/0/lines")[1]["lines"]


def steps(page):
    return page.evaluate("() => window.pdfStudio.state.info.undo_steps")


def bold(name):
    return "bold" in (name or "").lower()


def italic(name):
    return "oblique" in (name or "").lower() or "italic" in (name or "").lower()


def test_selection_modes_and_group_actions(ui, server):
    page = ui.page
    doc = open_file(page, fixture("multi.pdf"))
    boxes = page.locator(".tl-box")
    bar = page.locator("#style-bar")
    lines = lines_of(server.base, doc)
    n = len(lines)
    assert n >= 12, f"{n} lines"

    boxes.nth(2).click()
    page.wait_for_timeout(400)
    assert page.locator(".tl-box.selected").count() == 1

    boxes.nth(5).click(modifiers=["Shift"])
    page.wait_for_timeout(400)
    assert page.locator(".tl-box.selected").count() == 4
    assert page.locator(".style-count").is_visible()

    boxes.nth(7).click(modifiers=["Control"])
    page.wait_for_timeout(300)
    assert page.locator(".tl-box.selected").count() == 5
    boxes.nth(5).click(modifiers=["Control"])
    page.wait_for_timeout(300)
    assert page.locator(".tl-box.selected").count() == 4

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.locator(".tl-box.selected").count() == 0 and not bar.is_visible()

    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("Control+a")
    page.wait_for_timeout(400)
    assert page.locator(".tl-box.selected").count() == n
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    layer = page.locator("#textlayer").bounding_box()
    scale = page.evaluate("() => window.pdfStudio.scaleFactor()")
    rows = [lines[i] for i in (1, 2, 3)]
    top = min(r["bbox"][1] for r in rows) / scale - 2
    bottom = max(r["bbox"][3] for r in rows) / scale + 2
    right = max(r["bbox"][2] for r in rows) / scale + 6
    page.mouse.move(layer["x"] + 3, layer["y"] + top)
    page.mouse.down()
    for k in range(1, 9):
        page.mouse.move(layer["x"] + right * k / 8, layer["y"] + bottom * k / 8)
    page.mouse.move(layer["x"] + right, layer["y"] + bottom)
    page.mouse.up()
    page.wait_for_timeout(400)
    assert page.locator(".tl-box.selected").count() == 3
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    blocks = OrderedDict()
    for i, line in enumerate(lines):
        blocks.setdefault(tuple(line["block"]), []).append(i)
    group = next((v for v in blocks.values() if len(v) >= 3 and v == list(range(v[0], v[0] + len(v)))), None)
    assert group is not None, "no paragraph with 3+ lines"
    boxes.nth(group[0]).click()
    page.wait_for_timeout(300)
    boxes.nth(group[-1]).click(modifiers=["Shift"])
    page.wait_for_timeout(400)
    page.locator("#style-bar [data-act='align-center']").click()
    page.wait_for_timeout(1200)
    group_texts = {lines[i]["text"] for i in group}
    centres = [(l["bbox"][0] + l["bbox"][2]) / 2 for l in lines_of(server.base, doc) if l["text"] in group_texts]
    assert max(centres) - min(centres) < 2.0
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    boxes.nth(1).click()
    page.wait_for_timeout(300)
    boxes.nth(3).click(modifiers=["Shift"])
    page.wait_for_timeout(400)
    selected = page.evaluate("() => window.pdfStudio.state.selected.items.map(i => i.text)")
    assert len(selected) == 3, selected
    s0 = steps(page)
    page.locator("#style-bar [data-act='bold']").click()
    page.wait_for_timeout(1200)
    by_text = {l["text"]: l for l in lines_of(server.base, doc)}
    assert all(bold(by_text[t]["base_font"]) for t in selected)
    assert steps(page) == s0 + 1
    s0 = steps(page)
    page.locator("#style-bar [data-act='italic']").click()
    page.wait_for_timeout(1200)
    by_text = {l["text"]: l for l in lines_of(server.base, doc)}
    assert all(bold(by_text[t]["base_font"]) and italic(by_text[t]["base_font"]) for t in selected)
    assert steps(page) == s0 + 1
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    lines = lines_of(server.base, doc)
    idx = [8, 9, 10]
    assert len({lines[i]["text"] for i in idx}) == 3
    orig = {lines[i]["text"]: lines[i]["bbox"] for i in idx}
    boxes.nth(idx[0]).click()
    page.wait_for_timeout(300)
    boxes.nth(idx[-1]).click(modifiers=["Shift"])
    page.wait_for_timeout(300)
    mid = boxes.nth(idx[1]).bounding_box()
    s0 = steps(page)
    page.mouse.move(mid["x"] + 30, mid["y"] + mid["height"] / 2)
    page.mouse.down()
    for k in range(1, 9):
        page.mouse.move(mid["x"] + 30 + 5 * k, mid["y"] + mid["height"] / 2 + 3 * k)
    page.mouse.up()
    page.wait_for_timeout(1300)
    new = {l["text"]: l["bbox"] for l in lines_of(server.base, doc) if l["text"] in orig}
    deltas = [(new[t][0] - orig[t][0], new[t][1] - orig[t][1]) for t in orig]
    assert len(deltas) == 3 and deltas[0][0] > 5
    assert all(abs(dx - deltas[0][0]) < 2 and abs(dy - deltas[0][1]) < 2 for dx, dy in deltas)
    assert steps(page) == s0 + 1
    page.locator("#undo").click()
    page.wait_for_timeout(1300)
    back = {l["text"]: l["bbox"] for l in lines_of(server.base, doc) if l["text"] in orig}
    assert all(abs(back[t][0] - orig[t][0]) < 1 and abs(back[t][1] - orig[t][1]) < 1 for t in orig)
    assert not ui.errors


def test_replace_tool_selects_with_modifiers_and_edits_on_plain_click(ui, server):
    page = ui.page
    open_file(page, fixture("multi.pdf"))
    boxes = page.locator(".tl-box")
    page.locator("[data-tool='replace']").first.click()
    page.wait_for_timeout(900)
    boxes.nth(1).click()
    page.wait_for_timeout(300)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    boxes.nth(3).click(modifiers=["Shift"])
    page.wait_for_timeout(400)
    assert page.locator(".tl-box.selected").count() == 3
    assert page.locator(".tl-edit").count() == 0
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    boxes.nth(2).click()
    page.wait_for_timeout(500)
    assert page.locator(".tl-edit").count() == 1
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert not ui.errors


def test_alignment_buttons_follow_the_selection(ui_small, server):
    ui = ui_small
    page = ui.page
    doc = open_file(page, fixture("align.pdf"))
    boxes = page.locator(".tl-box")

    def active():
        return page.evaluate("() => [...document.querySelectorAll('#style-bar [data-align]')]"
                             ".find(b => b.classList.contains('active'))?.dataset.align || null")

    targets = ("A", "Medium length line", "Longer line of text for the test", "Short")
    boxes.nth(0).click()
    page.wait_for_timeout(300)
    boxes.nth(3).click(modifiers=["Shift"])
    page.wait_for_timeout(400)
    assert page.locator(".tl-box.selected").count() == 4
    assert active() == "left"

    page.locator("#style-bar [data-act='align-right']").click()
    page.wait_for_timeout(1300)
    rights = [l["bbox"][2] for l in lines_of(server.base, doc) if l["text"] in targets]
    assert len(rights) == 4 and max(rights) - min(rights) < 1.5
    assert active() == "right"

    page.locator("#style-bar [data-act='align-center']").click()
    page.wait_for_timeout(1300)
    centres = [(l["bbox"][0] + l["bbox"][2]) / 2 for l in lines_of(server.base, doc) if l["text"] in targets]
    assert len(centres) == 4 and max(centres) - min(centres) < 1.5
    assert active() == "center"
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert not ui.errors


def test_single_line_alignment_is_disabled_and_selection_highlight_is_accurate(ui_small, server):
    ui = ui_small
    page = ui.page
    doc = open_file(page, fixture("multi.pdf"))
    boxes = page.locator(".tl-box")
    lines = lines_of(server.base, doc)
    rows = [i for i, line in enumerate(lines) if line["text"].startswith("Row item")]
    if len(rows) < 5:
        import pytest
        pytest.skip("multi.pdf has no five-row block")
    boxes.nth(rows[0]).scroll_into_view_if_needed()
    boxes.nth(rows[0]).click()
    page.wait_for_timeout(400)
    assert page.locator("#style-bar [data-align]").first.is_disabled()

    boxes.nth(rows[4]).scroll_into_view_if_needed()
    boxes.nth(rows[4]).click(modifiers=["Shift"])
    page.wait_for_timeout(400)
    assert not page.locator("#style-bar [data-align='right']").is_disabled()
    page.locator("#style-bar [data-act='align-right']").click()
    page.wait_for_timeout(1200)
    chosen = {lines[i]["text"] for i in rows[:5]}
    rights = [l["bbox"][2] for l in lines_of(server.base, doc) if l["text"] in chosen]
    assert len(rights) == 5 and max(rights) - min(rights) < 1.5
    shown = page.evaluate("() => [...document.querySelectorAll('#style-bar [data-align]')]"
                          ".find(b => b.classList.contains('active'))?.dataset.align || null")
    expected = page.evaluate("() => window.pdfStudio.selectionAlign(window.pdfStudio.state.selected.items)")
    assert shown == expected, (shown, expected)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert not ui.errors


def test_style_bar_size_steps_from_the_shown_size(ui, server):
    page = ui.page
    doc = open_file(page, fixture("multi.pdf"))
    bar = page.locator("#style-bar")
    page.locator(".tl-box").nth(2).click()
    page.locator(".tl-box").nth(4).click(modifiers=["Shift"])
    page.wait_for_timeout(400)
    shown = bar.locator(".style-size")
    base = int(shown.inner_text())
    bar.locator("[data-act='larger']").click()
    page.wait_for_timeout(800)
    assert int(shown.inner_text()) == base + 1
    assert page.locator("#size").input_value() == str(base + 1)
    sizes = {round(ln["size"]) for ln in lines_of(server.base, doc)[2:5]}
    assert sizes == {base + 1}, sizes
    bar.locator("[data-act='smaller']").click()
    page.wait_for_timeout(800)
    assert int(shown.inner_text()) == base
    assert not ui.errors


def test_selected_text_is_tinted_without_a_frame(ui, server):
    page = ui.page
    open_file(page, fixture("multi.pdf"))
    boxes = page.locator(".tl-box")
    boxes.nth(2).click()
    page.wait_for_timeout(300)
    boxes.nth(5).click(modifiers=["Shift"])
    page.wait_for_timeout(300)
    selected = page.locator(".tl-box.selected")
    assert selected.count() == 4
    for i in range(selected.count()):
        width, color = selected.nth(i).evaluate(
            "el => [getComputedStyle(el).borderTopWidth, getComputedStyle(el).backgroundColor]")
        assert width == "0px"
        assert color != "rgba(0, 0, 0, 0)"
    boxes.nth(0).hover()
    page.wait_for_timeout(200)
    hovered = boxes.nth(0).evaluate("el => getComputedStyle(el).borderTopWidth")
    assert hovered == "0px"
