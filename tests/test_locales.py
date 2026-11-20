"""The four languages must have the same keys, and the picker must list them."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("en", "zh-CN", "ja", "ko")


def test_every_language_has_the_same_keys():
    keys = {lang: set(json.loads((ROOT / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8")))
            for lang in LANGS}
    for lang in LANGS:
        assert keys[lang] == keys["en"], lang


def test_language_picker_lists_every_locale_file():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    picker = re.search(r'<select id="lang">(.*?)</select>', html, re.S).group(1)
    assert sorted(re.findall(r'value="([^"]+)"', picker)) == sorted(LANGS)
