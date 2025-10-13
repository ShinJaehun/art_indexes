from pathlib import Path
from typing import Optional

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

from thumbs import _safe_name as _thumb_safe_name


def _append_fs_thumb_if_missing(
    soup: "BeautifulSoup",
    tw,  # thumb-wrap 노드
    folder: str,
    resource_dir: Path,
) -> None:
    """
    파일시스템에 썸네일이 있으면 <img.thumb src="resource/<folder>/thumbs/<safe>.jpg">를
    thumb-wrap(tw)에 '존재하지 않는 경우에만' 추가한다.
    """
    if tw is None:
        return
    # 이미 썸네일이 있으면 무시
    if tw.find("img", class_="thumb"):
        return

    safe = _thumb_safe_name(folder)
    jpg = resource_dir / folder / "thumbs" / f"{safe}.jpg"
    if not jpg.exists():
        return

    img = soup.new_tag(
        "img",
        **{
            "class": "thumb",
            "src": f"resource/{folder}/thumbs/{safe}.jpg",
            "alt": "썸네일",
        },
    )
    tw.append(img)


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

    _append_fs_thumb_if_missing(soup, tw, folder, resource_dir)
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

        _append_fs_thumb_if_missing(soup, tw, folder, resource_dir)

    return str(soup)


def persist_thumbs_in_master(html: str, resource_dir: Path) -> str:
    """저장 직전 master_content.html에 썸네일을 영구 반영"""
    if BeautifulSoup is None:
        return html

    # NOTE: 일부 환경에서 'html.parser'가 더 보편적입니다.
    # 오탈자 방지를 위해 아래 라인을 사용하세요:
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

        # .inner에 있는 썸네일 후보를 head로 이동 (이미 tw에 썸네일이 없을 때만)
        if not tw.find("img", class_="thumb"):
            candidates = []
            for img in div.find_all("img"):
                if img is tw.find("img", class_="thumb"):
                    continue
                src = (img.get("src") or "").lower()
                cls = img.get("class") or []
                if (
                    ("thumbs/" in src)
                    or ("thumb" in cls)
                    or (img.get("alt", "") == "썸네일")
                ):
                    candidates.append(img)
            if candidates and not tw.find("img", class_="thumb"):
                # 첫 번째 후보만 이동
                tw.append(candidates[0])

        # 파일시스템 기준 보강 (여전히 없으면 FS에서 채움)
        _append_fs_thumb_if_missing(soup, tw, folder, resource_dir)

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
