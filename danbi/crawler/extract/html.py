"""HTML → 마크다운."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment
from markdownify import markdownify


def clean_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def html_to_md(el) -> str:
    """본문 요소를 마크다운으로 변환.

    HWP에서 붙여 넣은 글은 HTML 주석 안에 거대한 data-hwpjson이 들어 있으므로 주석을 반드시 제거한다.
    """
    el = BeautifulSoup(str(el), "lxml")
    for c in el.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for t in el(["script", "style", "noscript", "link", "button", "form", "select", "input"]):
        t.decompose()
    md = markdownify(str(el), heading_style="ATX", strip=["img"])
    md = md.replace("\xa0", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()
