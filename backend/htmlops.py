import re
from typing import Optional

try:
    from bs4 import BeautifulSoup, Comment
except Exception:
    BeautifulSoup = None
    Comment = None

ROOT_MASTER = "master_index.html"
_BODY_RE = re.compile(r"<body[^>]*>([\s\S]*?)</body>", re.I)
_SKIP_PREFIX = re.compile(
    r"^(https?://|www\.|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}|/|\.\./|#|resource/|mailto:|tel:|data:)",
    re.I,
)


def extract_body_inner(html_text: str) -> str:
    """
    전체 HTML에서 <body> 안의 'HTML 그대로'를 반환.
    BeautifulSoup이 있으면 decode_contents()를, 없으면 정규식 폴백을 사용.
    """
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_text or "", "html.parser")
        if soup.body:
            return soup.body.decode_contents().strip()
        return html_text or ""
    # 폴백(정규식)
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
    - True : resource/master_index.html 기준 ("<folder>/..."), + 모든 resource/ 접두어 제거
    - 교차 폴더 경로(resource/<다른폴더>/...)도 보정
    """
    if BeautifulSoup is None:
        # --- 정규식 폴백 ---
        # 자기 폴더 → 기존 처리는 유지
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
            # ★ 교차 폴더: resource/<ANY>/... → ../<ANY>/...
            div_html = re.sub(
                r'(<img[^>]+src=")resource/([^"/]+/)',
                r"\1../\2",
                div_html,
                flags=re.I,
            )
            div_html = re.sub(
                r'(<a[^>]+href=")resource/([^"/]+/)',
                r"\1../\2",
                div_html,
                flags=re.I,
            )
            return div_html
        else:
            # 마스터: 자기 폴더는 "<folder>/" 로, 나머지 모든 resource/ 접두어는 제거
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
            # ★ 교차 폴더: resource/<ANY>/... → <ANY>/...
            div_html = re.sub(
                r'(<img[^>]+src=")resource/',
                r"\1",
                div_html,
                flags=re.I,
            )
            div_html = re.sub(
                r'(<a[^>]+href=")resource/',
                r"\1",
                div_html,
                flags=re.I,
            )
            # ★ 맨몸 IMG: src="x.png"  → src="<folder>/x.png"
            div_html = re.sub(
                r'(<img[^>]+src=")(?!https?://|/|\.\./|#|resource/|mailto:|tel:|data:)([^"]+)"',
                r"\1" + folder + r"/\2\"",
                div_html,
                flags=re.I,
            )
            # ★ 맨몸 A  : href="file.html" → href="<folder>/file.html"
            div_html = re.sub(
                r'(<a[^>]+href=")(?!https?://|/|\.\./|#|resource/|mailto:|tel:|data:)([^"]+)"',
                r"\1" + folder + r"/\2\"",
                div_html,
                flags=re.I,
            )
            return div_html

    # --- BeautifulSoup 경로 ---
    soup = BeautifulSoup(div_html, "html.parser")
    prefix_self = f"resource/{folder}/"

    def _is_bare(p: str) -> bool:
        return p and not _SKIP_PREFIX.search(p)

    for tag in soup.find_all(["img", "a"]):
        if tag.name == "img" and tag.has_attr("src"):
            src = tag["src"]

            if src.startswith(prefix_self):
                rest = src[len(prefix_self) :]
                tag["src"] = f"{folder}/{rest}" if for_resource_master else rest

            elif src.startswith("resource/"):
                # 교차 폴더
                rest = src[len("resource/") :]
                tag["src"] = rest if for_resource_master else f"../{rest}"

            elif _is_bare(src):
                # ★ 맨몸 경로: master_index에선 <folder>/..., child에선 그대로
                if for_resource_master:
                    tag["src"] = f"{folder}/{src}"
                else:
                    tag["src"] = src  # child 그대로

        if tag.name == "a" and tag.has_attr("href"):
            href = tag["href"]

            if href == f"{prefix_self}index.html":
                tag["href"] = (
                    f"{folder}/index.html" if for_resource_master else "index.html"
                )

            elif href.startswith(prefix_self):
                rest = href[len(prefix_self) :]
                tag["href"] = f"{folder}/{rest}" if for_resource_master else rest

            elif href.startswith("resource/"):
                rest = href[len("resource/") :]
                tag["href"] = rest if for_resource_master else f"../{rest}"

            elif _is_bare(href):
                # ★ 맨몸 경로: index.html 같은 것들
                if for_resource_master:
                    tag["href"] = f"{folder}/{href}"
                else:
                    tag["href"] = href

    return str(soup)


def extract_inner_html_only(div_folder_html: str) -> str:
    """
    <div class="folder">에서 .inner의 '자식'만 HTML 그대로 반환
    (헤드/툴바/썸네일 배제, 엔티티 재이스케이프 금지)
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
    # 주석 제거
    if Comment is not None:
        for c in list(inner.find_all(string=lambda x: isinstance(x, Comment))):
            c.extract()
    # ✅ 핵심: decode_contents()로 HTML 그대로 추출 (get_text() 금지)
    return inner.decode_contents().strip()
