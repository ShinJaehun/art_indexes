from pathlib import Path

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

from thumbs import _safe_name as _thumb_safe_name


def ensure_thumb_in_head(div_html: str, folder: str, resource_dir: Path) -> str:
    """head의 .thumb-wrap이 비어 있으면 파일시스템 썸네일을 채워 넣는다."""
    if BeautifulSoup is None:
        return div_html

    soup = BeautifulSoup(div_html, "html.parser")
    head = soup.select_one(".folder-head") or soup
    tw = head.select_one(".thumb-wrap")
    if not tw:
        tw = soup.new_tag("div", **{"class": "thumb-wrap"})
        head.append(tw)

    if not tw.find("img"):
        safe = _thumb_safe_name(folder)
        jpg = resource_dir / folder / "thumbs" / f"{safe}.jpg"
        if jpg.exists():
            img = soup.new_tag(
                "img",
                **{
                    "class": "thumb",
                    "src": f"resource/{folder}/thumbs/{safe}.jpg",
                    "alt": "썸네일",
                },
            )
            tw.append(img)
    return str(soup)


def inject_thumbs_for_preview(html: str, resource_dir: Path) -> str:
    """webview 편집 화면 미리보기용(파일 저장은 안 함)"""
    if BeautifulSoup is None:
        return html

    soup = BeautifulSoup(html or "", "html.parser")
    for div in soup.find_all("div", class_="folder"):
        h2 = div.find("h2")
        if not h2:
            continue
        folder = (h2.get_text() or "").strip()
        if not folder:
            continue

        head = div.find(class_="folder-head") or div
        tw = head.find(class_="thumb-wrap")
        if not tw:
            tw = soup.new_tag("div", **{"class": "thumb-wrap"})
            head.append(tw)

        if tw.find("img"):
            continue

        safe = _thumb_safe_name(folder)
        jpg = resource_dir / folder / "thumbs" / f"{safe}.jpg"
        if jpg.exists():
            img = soup.new_tag(
                "img",
                **{
                    "class": "thumb",
                    "src": f"resource/{folder}/thumbs/{safe}.jpg",
                    "alt": "썸네일",
                },
            )
            tw.append(img)

    return str(soup)


def persist_thumbs_in_master(html: str, resource_dir: Path) -> str:
    """저장 직전 master_content.html에 썸네일을 영구 반영"""
    if BeautifulSoup is None:
        return html

    soup = BeautifulSoup(html or "", "html.parser")

    for div in soup.find_all("div", class_="folder"):
        h2 = div.find("h2")
        if not h2:
            continue
        folder = (h2.get_text() or "").strip()
        if not folder:
            continue

        head = div.find(class_="folder-head")
        if not head:
            head = soup.new_tag("div", **{"class": "folder-head"})
            h2.replace_with(head)
            head.append(h2)

        tw = head.find(class_="thumb-wrap")
        if not tw:
            tw = soup.new_tag("div", **{"class": "thumb-wrap"})
            head.append(tw)

        # .inner에 있는 썸네일 후보를 head로 이동
        candidates = []
        for img in div.find_all("img"):
            src = img.get("src", "")
            if img is tw.find("img"):
                continue
            if (
                "thumbs/" in src
                or "thumb" in (img.get("class") or [])
                or img.get("alt", "") == "썸네일"
            ):
                candidates.append(img)
        if candidates and not tw.find("img"):
            tw.append(candidates[0])

        # 파일시스템 기준 보강
        if not tw.find("img"):
            safe = _thumb_safe_name(folder)
            jpg = resource_dir / folder / "thumbs" / f"{safe}.jpg"
            if jpg.exists():
                img = soup.new_tag(
                    "img",
                    **{
                        "class": "thumb",
                        "src": f"resource/{folder}/thumbs/{safe}.jpg",
                        "alt": "썸네일",
                    },
                )
                tw.append(img)

        # 편집용 속성 정리
        for el in [div, head, tw] + list(div.find_all(True)):
            if hasattr(el, "attrs"):
                el.attrs.pop("contenteditable", None)
                el.attrs.pop("draggable", None)
                cls = el.get("class")
                if cls:
                    el["class"] = [c for c in cls if c != "editable"]

    return str(soup)


def make_clean_block_html_for_master(folder: str, resource_dir: Path) -> str:
    """초기화/신규 폴더용 '깨끗한 기본 카드' HTML 문자열 생성(툴바 없음)"""
    safe = _thumb_safe_name(folder)
    thumb_path = resource_dir / folder / "thumbs" / f"{safe}.jpg"
    if thumb_path.exists():
        thumb_html = f"""
      <div class="thumb-wrap">
        <img class="thumb" src="resource/{folder}/thumbs/{safe}.jpg" alt="썸네일" />
      </div>"""
    else:
        thumb_html = """<div class="thumb-wrap"></div>"""

    return f"""
<div class="folder" data-folder="{folder}">
  <div class="folder-head">
    <h2>{folder}</h2>
    {thumb_html}
  </div>
  <div class="inner">
    <!-- 새 폴더 기본 본문 -->
  </div>
</div>""".strip()
