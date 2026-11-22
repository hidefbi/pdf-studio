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
    picker = re.search(r'<select id="lang"[^>]*>(.*?)</select>', html, re.S).group(1)
    assert sorted(re.findall(r'value="([^"]+)"', picker)) == sorted(LANGS)


def test_every_server_message_has_a_translation():
    """The UI shows server messages in the chosen language, so each one needs an entry."""
    texts = set()
    for name in ("main.py", "linetext.py"):
        code = (ROOT / "app" / name).read_text(encoding="utf-8")
        texts.update(re.findall(r'HTTPException\(\d+, "([^"]+)"', code))
        texts.update(re.findall(r'ValueError\("([^"]+)"\)', code))
        texts.update(re.findall(r'_save_upload\([^\n]*"([^"]+)"\)', code))
        texts.update(re.findall(r'REFUSED = "([^"]+)"', code))
    texts.add("invalid request")
    texts.discard("ocr_not_installed")  # a code; the page shows its own message for it
    for lang in LANGS:
        table = json.loads((ROOT / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        missing = sorted(text for text in texts if text not in table)
        assert not missing, (lang, missing)
