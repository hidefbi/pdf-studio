"""The page only shows "server stopped" after several heartbeats in a row fail."""
from __future__ import annotations

from playwright.sync_api import expect


def test_one_lost_heartbeat_is_not_enough(ui, server):
    page = ui.page
    page.route("**/api/heartbeat", lambda route: route.abort())
    page.wait_for_timeout(4000)  # about one beat missed
    assert not page.is_visible("#stopped")
    expect(page.locator("#stopped")).to_be_visible(timeout=15000)
    assert not ui.errors
