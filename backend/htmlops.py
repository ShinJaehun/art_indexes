import re
from typing import List, Dict, Any, Optional
import os

try:
    from bs4 import BeautifulSoup, Comment
except Exception:
    BeautifulSoup = None
    Comment = None

try:
    from .constants import MASTER_INDEX
except Exception:
    MASTER_INDEX = "master_index.html"

_BODY_RE = re.compile(r"<body[^>]*>([\s\S]*?)</body>", re.I)

_SKIP_PREFIX = re.compile(
    r"^(https?://|www\.|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}|/|\.\./|#|resource/|mailto:|tel:|data:)",
    re.I,
)

__all__ = [
    "extract_folder_blocks",  # (호환 이름 유지)
    "map_blocks_by_slug",
]


def _make_slug(name: str) -> str:
    """
    파일시스템 세이프 슬러그(최소 규칙):
    - 앞뒤 공백 제거
    - 경로 구분자 제거('/', os.sep)
    - 연속 공백 압축 후 공백→'_' 치환
    """
    if name is None:
        name = ""
    name = str(name).strip().replace(os.sep, " ").replace("/", " ")
    while "  " in name:
        name = name.replace("  ", " ")
    return name.replace(" ", "_")


def _text(el) -> str:
    try:
        return el.get_text(strip=True)
    except Exception:
        return ""


def _inner_html(el) -> str:
    try:
        # BeautifulSoup: 태그 내부 HTML만 문자열로
        return "".join(str(c) for c in el.contents)
    except Exception:
        return ""


def extract_folder_blocks(html: str) -> List[Dict[str, Any]]:
    """
    (호환 함수명) 마스터/차일드 HTML에서 <div class="card"> 블록들을 표준 스키마로 파싱.
    반환 스키마:
      [{"slug","title","thumb","html","raw_html"}, ...]
    """
    if BeautifulSoup is None:
        raise RuntimeError(
            "BeautifulSoup(bs4)가 필요합니다. `pip install beautifulsoup4` 후 다시 시도하세요."
        )

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, Any]] = []

    for folder in soup.select("div.card"):
        # 1) 제목
        h2 = folder.select_one(".card-head h2") or folder.find("h2")
        title = _text(h2) if h2 else ""

        # 2) 썸네일
        thumb_img = folder.select_one(".card-head img.thumb") or folder.select_one(
            "img.thumb"
        )
        thumb: Optional[str] = (
            thumb_img.get("src") if thumb_img and thumb_img.has_attr("src") else None
        )

        # 3) 본문(inner)
        inner = folder.select_one(".inner")
        inner_html = _inner_html(inner) if inner else ""

        # 4) slug + raw
        slug = _make_slug(title if title else "card")
        raw_html = str(folder)

        out.append(
            {
                "slug": slug,
                "title": title,
                "thumb": thumb,
                "html": inner_html,
                "raw_html": raw_html,
            }
        )

    return out


def map_blocks_by_slug(blocks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    블록 리스트를 slug 기준 dict로 변환.
    slug 충돌 시 뒤 항목이 덮어쓰지 않도록 '-2','-3' 접미사로 디스앰빅 처리.
    """
    bucket: Dict[str, Dict[str, Any]] = {}
    counter: Dict[str, int] = {}

    for b in blocks:
        slug = b.get("slug") or "card"
        if slug in bucket:
            # disambiguate
            counter[slug] = counter.get(slug, 1) + 1
            new_slug = f"{slug}-{counter[slug]}"
            # 사본을 만들어 slug만 교체
            b = dict(b)
            b["slug"] = new_slug
            bucket[new_slug] = b
        else:
            counter[slug] = 1
            bucket[slug] = b

    return bucket


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
        if href in (f"../{MASTER_INDEX}", MASTER_INDEX):
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
                r"\1" + folder + r"/\2" + '"',
                div_html,
                flags=re.I,
            )
            # ★ 맨몸 A  : href="file.html" → href="<folder>/file.html"
            div_html = re.sub(
                r'(<a[^>]+href=")(?!https?://|/|\.\./|#|resource/|mailto:|tel:|data:)([^"]+)"',
                r"\1" + folder + r"/\2" + '"',
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
    <div class="card">에서 .inner의 '자식'만 HTML 그대로 반환
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
    folder = soup.find("div", class_="card") or soup
    inner = folder.find("div", class_="inner")
    if not inner:
        return ""
    # 주석 제거
    if Comment is not None:
        for c in list(inner.find_all(string=lambda x: isinstance(x, Comment))):
            c.extract()
    # ✅ 핵심: decode_contents()로 HTML 그대로 추출 (get_text() 금지)
    return inner.decode_contents().strip()
