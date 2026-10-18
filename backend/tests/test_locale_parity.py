"""
Пять словарей интерфейса — один набор ключей и одни подстановки {…}.

Пропущенный ключ молча показывает английский текст посреди русского экрана;
потерянная подстановка выбрасывает из фразы число («лимит {max} корпусов»).
Сторож регрессии: на момент написания расхождений не было.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
LANGS = ["en", "ru", "de", "fr", "pl"]

_NODE = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ctx = { window: { LOCALES: {} } }; vm.createContext(ctx);
for (const l of JSON.parse(process.argv[2]))
  vm.runInContext(fs.readFileSync(path.join(process.argv[1], 'i18n', l + '.js'), 'utf8'), ctx);
console.log(JSON.stringify(ctx.window.LOCALES));
"""


@pytest.fixture(scope="module")
def locales():
    if shutil.which("node") is None:
        pytest.skip("нужен node")
    out = subprocess.run(["node", "-e", _NODE, str(STATIC), json.dumps(LANGS)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_same_keys_in_every_dictionary(locales):
    en = set(locales["en"])
    problems = [f"{lang}: нет {sorted(en - set(locales[lang]))}, лишние {sorted(set(locales[lang]) - en)}"
                for lang in LANGS[1:] if set(locales[lang]) != en]
    assert not problems, "\n".join(problems)


def test_same_placeholders_in_every_translation(locales):
    def placeholders(v):
        return sorted(set(re.findall(r"\{[a-z_0-9]+\}", v))) if isinstance(v, str) else []
    problems = [f"{key} [{lang}]: {placeholders(locales[lang].get(key))} ≠ en {placeholders(text)}"
                for key, text in locales["en"].items() for lang in LANGS[1:]
                if placeholders(text) != placeholders(locales[lang].get(key))]
    assert not problems, "\n".join(problems[:20])
