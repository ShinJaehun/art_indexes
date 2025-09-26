import re
from typing import Optional

try:
    from bs4 import BeautifulSoup, Comment
except Exception:
    BeautifulSoup = None
    Comment = None

ROOT_MASTER = "master_index.html"
_BODY_RE = re.compile(r"<body[^>]*>([\s\S]*?)</body>", re.I)
_SKIP_PREFIX = re.compile(r"^(https?://|/|\.\./|#|resource/|mailto:|tel:|data:)", re.I)


def extract_body_inner(html_text: str) -> str:
    m = _BODY_RE.search(html_text or "")
    return m.group(1).strip() if m else (html_text or "")


def prefix_resource_paths_for_root(html: str) -> str:
    """root(index.html)에서 사용할 내용에 대해 src/href 앞에 resource/ 접두어를 붙임"""

    def fix_src(m: "re.Match[str]"):
        val = m.group(2)
        return (
            f'{m.group(1)}resource/{val}"'
            if not _SKIP_PREFIX.search(val)
            else m.group(0)
        )

    html = re.sub(r'(<img[^>]+src=")([^"]+)"', fix_src, html, flags=re.I)
    html = re.sub(r'(<a[^>]+href=")([^"]+)"', fix_src, html, flags=re.I)
    return html


def strip_back_to_master(div_html: str) -> str:
    """child index의 '⬅ 전체 목록으로' 링크 제거(마스터에서는 불필요)"""
    if BeautifulSoup is None:
        return re.sub(
            r'<a[^>]+href="\.\./master_index\.html"[^>]*>.*?</a>',
            "",
            div_html,
            flags=re.I | re.S,
        )
    soup = BeautifulSoup(div_html, "html.parser")
    for a in list(soup.find_all("a", href=True)):
        href = a["href"]
        if href in (f"../{ROOT_MASTER}", ROOT_MASTER):
            if a.find("img"):
                a.unwrap()
            else:
                a.decompose()
    return str(soup)


def adjust_paths_for_folder(
    div_html: str, folder: str, *, for_resource_master: bool = False
) -> str:
    """
    master_content 기준 경로 치환
    - False: 해당 폴더 index.html 기준
    - True : resource/master_index.html 기준 ("<folder>/...")
    """
    if BeautifulSoup is None:
        if not for_resource_master:
            div_html = re.sub(
                rf'(<img[^>]+src=")resource/{re.escape(folder)}/',
                r"\1",
                div_html,
                flags=re.I,
            )
            div_html = re.sub(
                rf'(<a[^>]+href=")resource/{re.escape(folder)}/index\.html"',
                r'\1index.html"',
                div_html,
                flags=re.I,
            )
            div_html = re.sub(
                rf'(<a[^>]+href=")resource/{re.escape(folder)}/',
                r"\1",
                div_html,
                flags=re.I,
            )
            return div_html
        else:
            div_html = re.sub(
                rf'(<img[^>]+src=")resource/{re.escape(folder)}/',
                r"\1" + folder + "/",
                div_html,
                flags=re.I,
            )
            div_html = re.sub(
                rf'(<a[^>]+href=")resource/{re.escape(folder)}/index\.html"',
                r"\1" + folder + '/index.html"',
                div_html,
                flags=re.I,
            )
            div_html = re.sub(
                rf'(<a[^>]+href=")resource/{re.escape(folder)}/',
                r"\1" + folder + "/",
                div_html,
                flags=re.I,
            )
            return div_html

    soup = BeautifulSoup(div_html, "html.parser")
    prefix = f"resource/{folder}/"

    for tag in soup.find_all(["img", "a"]):
        if tag.name == "img" and tag.has_attr("src"):
            src = tag["src"]
            if src.startswith(prefix):
                rest = src[len(prefix) :]
                tag["src"] = f"{folder}/{rest}" if for_resource_master else rest

        if tag.name == "a" and tag.has_attr("href"):
            href = tag["href"]
            if href == f"{prefix}index.html":
                tag["href"] = (
                    f"{folder}/index.html" if for_resource_master else "index.html"
                )
            elif href.startswith(prefix):
                rest = href[len(prefix) :]
                tag["href"] = f"{folder}/{rest}" if for_resource_master else rest

    return str(soup)


def extract_inner_html_only(div_folder_html: str) -> str:
    """
    <div class="folder">에서 .inner의 '자식'만 문자열로 반환(헤드/툴바/썸네일 배제)
    """
    if BeautifulSoup is None:
        m = re.search(
            r'<div\s+class="inner"[^>]*>([\s\S]*?)</div>', div_folder_html, re.I
        )
        inner = m.group(1) if m else ""
        inner = re.sub(r"<!--[\s\S]*?-->", "", inner)  # 주석 제거
        return inner.strip()

    soup = BeautifulSoup(div_folder_html, "html.parser")
    folder = soup.find("div", class_="folder") or soup
    inner = folder.find("div", class_="inner")
    if not inner:
        return ""
    for node in list(inner.contents):
        if Comment is not None and isinstance(node, Comment):
            node.extract()
    return "".join(str(x) for x in inner.contents).strip()
