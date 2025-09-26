import re

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None


def sanitize_for_publish(div_html: str) -> str:
    """
    편집용 div.folder → 배포용으로 정화
    - 제거: .folder-actions, .btn*, contenteditable/draggable, on*, data-*, style
    - 화이트리스트: 태그/속성 최소화
    """
    if BeautifulSoup is None:
        html = re.sub(
            r'<[^>]+class="[^"]*\bfolder-actions\b[^"]*"[^>]*>.*?</[^>]+>',
            "",
            div_html,
            flags=re.I | re.S,
        )
        html = re.sub(
            r'<[^>]+class="[^"]*\bbtn[^"]*"[^>]*>.*?</[^>]+>',
            "",
            html,
            flags=re.I | re.S,
        )
        html = re.sub(r'\scontenteditable="[^"]*"', "", html, flags=re.I)
        html = re.sub(r'\sdraggable="[^"]*"', "", html, flags=re.I)
        html = re.sub(r'\sdata-[\w-]+="[^"]*"', "", html, flags=re.I)
        html = re.sub(r'\son[a-zA-Z]+\s*=\s*"[^"]*"', "", html, flags=re.I)
        html = re.sub(r'\sstyle="[^"]*"', "", html, flags=re.I)
        return html

    soup = BeautifulSoup(div_html, "html.parser")

    for n in soup.select('.folder-actions, .btn, [class^="btn"]'):
        n.decompose()

    allowed_tags = {
        "div",
        "p",
        "img",
        "a",
        "ul",
        "ol",
        "li",
        "br",
        "h2",
        "h3",
        "h4",
        "span",
        "strong",
        "em",
    }
    allowed_attrs = {
        "img": {"src", "alt", "title", "width", "height"},
        "a": {"href", "title", "target", "rel"},
    }

    for tag in list(soup.find_all(True)):
        # 공통 속성 제거
        for attr in list(tag.attrs.keys()):
            low = attr.lower()
            if (
                low.startswith("on")
                or low.startswith("data-")
                or low in {"contenteditable", "draggable", "style"}
            ):
                tag.attrs.pop(attr, None)

        # 태그 화이트리스트
        if tag.name not in allowed_tags:
            tag.unwrap()
            continue

        # 허용 속성만 유지
        if tag.name in allowed_attrs:
            keep = allowed_attrs[tag.name]
            for a in list(tag.attrs.keys()):
                if a not in keep and a != "class":
                    tag.attrs.pop(a, None)

    return str(soup)
