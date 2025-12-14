from pathlib import Path
from typing import Optional

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

from backend.thumbs import _safe_name as _thumb_safe_name

def _fs_thumb_path(resource_dir: Path, card_name: str) -> Path:
    safe = _thumb_safe_name(card_name)
    return resource_dir / card_name / "thumbs" / f"{safe}.jpg"

def _fs_thumb_path_any(resource_dir: Path, card_name: str) -> Optional[Path]:
    """
    thumbs 폴더에 실제로 존재하는 jpg를 우선 사용.
    - 1순위: safe_name.jpg
    - 2순위: thumbs 안의 첫 번째 *.jpg
    """
    thumbs_dir = resource_dir / card_name / "thumbs"
    if not thumbs_dir.exists() or not thumbs_dir.is_dir():
        return None

    # 1) safe_name 우선
    preferred = _fs_thumb_path(resource_dir, card_name)
    if preferred.exists():
        return preferred

    # 2) 아무 jpg 하나라도 있으면 사용
    try:
        for p in thumbs_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".jpg":
                return p
    except Exception:
        return None

    return None

def _fs_thumb_exists(resource_dir: Path, card_name: str) -> bool:
    return _fs_thumb_path_any(resource_dir, card_name) is not None


def _is_within(ancestor, node) -> bool:
    """bs4용 조상 포함 여부(head.contains 대체)."""
    try:
        return any(p is ancestor for p in getattr(node, "parents", []))
    except Exception:
        return False


def _append_fs_thumb_if_missing(
    soup: "BeautifulSoup",
    tw,  # thumb-wrap 노드
    card_name: str,
    resource_dir: Path,
) -> None:
    """
    파일시스템에 썸네일이 있으면
    <img.thumb src="resource/<card_name>/thumbs/<safe>.jpg">를
    thumb-wrap(tw)에 '존재하지 않는 경우에만' 추가한다.
    """
    if tw is None:
        return
    # 이미 썸네일이 있으면 무시
    if tw.find("img", class_="thumb"):
        return

    jpg = _fs_thumb_path_any(resource_dir, card_name)
    if not jpg:
        return

    # 실제 파일명을 그대로 사용 (safe_name 불일치/정규화 차이 대비)
    jpg_name = jpg.name
    img = soup.new_tag(
        "img",
        **{
            "class": "thumb",
            "src": f"resource/{card_name}/thumbs/{jpg_name}",
            "alt": "썸네일",
        },
    )
    tw.append(img)


def _dedupe_and_confine_thumb_wrap(soup: "BeautifulSoup", card_div) -> None:
    """
    - .card 내부의 .thumb-wrap을 .card-head 안으로만 제한
    - 헤더 밖 thumb-wrap 전부 제거
    - 헤더 안 thumb-wrap 여러 개면 1개만 남김
    """
    if card_div is None:
        return
    head = card_div.find(class_="card-head") or card_div

    # 헤더 밖의 .thumb-wrap 제거
    for tw in card_div.find_all("div", class_="thumb-wrap"):
        if not _is_within(head, tw):
            tw.decompose()

    # 헤더 안 thumb-wrap dedupe
    wraps_in_head = head.find_all("div", class_="thumb-wrap")
    if len(wraps_in_head) > 1:
        keep = wraps_in_head[0]
        for extra in wraps_in_head[1:]:
            extra.decompose()


def ensure_thumb_in_head(div_html: str, card_name: str, resource_dir: Path) -> str:
    """
    - 헤더 밖 thumb-wrap 제거
    - FS 썸네일이 있거나 기존 이미지가 있을 때만 thumb-wrap 유지/생성
    - 최종적으로 비어 있으면 제거
    """
    if BeautifulSoup is None:
        return div_html

    soup = BeautifulSoup(div_html, "html.parser")
    card_div = soup.find("div", class_="card") or soup
    head = card_div.find(class_="card-head") or card_div

    # 1) 영역 정리
    _dedupe_and_confine_thumb_wrap(soup, card_div)

    # 2) 상태 파악
    fs_exists = _fs_thumb_exists(resource_dir, card_name)
    tw = head.find("div", class_="thumb-wrap")

    # 3) 필요할 때만 생성
    if not tw and fs_exists:
        tw = soup.new_tag("div", **{"class": "thumb-wrap"})
        head.append(tw)

    # 4) FS 보강
    if tw:
        _append_fs_thumb_if_missing(soup, tw, card_name, resource_dir)
        # 비어 있으면 제거
        if not tw.find("img", class_="thumb"):
            tw.decompose()

    return str(soup)


def inject_thumbs_for_preview(html: str, resource_dir: Path) -> str:
    """webview 편집 화면 미리보기용(파일 저장은 안 함)"""
    if BeautifulSoup is None:
        return html

    soup = BeautifulSoup(html or "", "html.parser")
    for div in soup.find_all("div", class_="card"):
        h2 = div.find("h2")
        card_name = (h2.get_text() or "").strip() if h2 else ""
        if not card_name:
            continue

        head = div.find(class_="card-head") or div

        # 영역 정리: thumb-wrap 위치/중복 정돈
        _dedupe_and_confine_thumb_wrap(soup, div)

        fs_exists = _fs_thumb_exists(resource_dir, card_name)
        tw = head.find("div", class_="thumb-wrap")

        # 🔹 썸네일 파일이 더 이상 없으면, 기존 thumb-wrap 자체를 제거한다.
        #    (예전 썸네일 <img>가 남아 있어도 강제로 정리해서 캐시 이미지가 계속 보이지 않도록)
        if not fs_exists:
            if tw:
                tw.decompose()
            continue

        # 🔹 여기부터는 "FS에 썸네일이 실제로 존재"하는 경우만 처리

        # tw가 없고 FS가 있을 때만 새로 만든다
        if not tw:
            tw = soup.new_tag("div", **{"class": "thumb-wrap"})
            head.append(tw)

        if tw:
            _append_fs_thumb_if_missing(soup, tw, card_name, resource_dir)
            # 여전히 비어 있으면 제거 (방어 코드)
            if not tw.find("img", class_="thumb"):
                tw.decompose()

    return str(soup)


def persist_thumbs_in_master(html: str, resource_dir: Path) -> str:
    """저장 직전 master_content.html에 썸네일을 영구 반영"""
    if BeautifulSoup is None:
        return html

    soup = BeautifulSoup(html or "", "html.parser")

    for div in soup.find_all("div", class_="card"):
        h2 = div.find("h2")
        card_name = (h2.get_text() or "").strip() if h2 else ""
        if not card_name:
            continue

        head = div.find(class_="card-head")
        if not head:
            head = soup.new_tag("div", **{"class": "card-head"})
            if h2:
                h2.replace_with(head)
                head.append(h2)
            else:
                div.insert(0, head)

        # 1) 영역 정리
        _dedupe_and_confine_thumb_wrap(soup, div)

        tw = head.find("div", class_="thumb-wrap")
        if not tw and _fs_thumb_exists(resource_dir, card_name):
            # tw가 없으면 우선 FS 여부 확인
            tw = soup.new_tag("div", **{"class": "thumb-wrap"})
            head.append(tw)

        # 2) 후보 이미지(head 외부에 있던 thumb성 이미지 → tw로 이동)
        if tw and not tw.find("img", class_="thumb"):
            for img in div.find_all("img"):
                if _is_within(head, img):
                    continue
                src = (img.get("src") or "").lower()
                cls = img.get("class") or []
                if (
                    ("thumbs/" in src)
                    or ("thumb" in cls)
                    or (img.get("alt", "") == "썸네일")
                ):
                    img.extract()
                    tw.append(img)
                    break

        # 3) FS 보강
        if tw:
            _append_fs_thumb_if_missing(soup, tw, card_name, resource_dir)
            # dedupe: tw 내부 이미지 1장만 유지 (FS 경로 우선)
            imgs = tw.find_all("img")
            if imgs:
                # FS에 실제 존재하는 jpg 기준으로 fs_src 구성
                jpg = _fs_thumb_path_any(resource_dir, card_name)
                fs_src = (
                    f"resource/{card_name}/thumbs/{jpg.name}"
                    if jpg is not None
                    else f"resource/{card_name}/thumbs/{_thumb_safe_name(card_name)}.jpg"
                )

                # 우선순위 1: class에 'thumb' 있고 src가 FS 경로인 것
                keep = next(
                    (
                        im
                        for im in imgs
                        if "thumb" in (im.get("class") or [])
                        and (im.get("src") or "") == fs_src
                    ),
                    None,
                )
                # 우선순위 2: class에 'thumb' 있는 것
                if not keep:
                    keep = next(
                        (im for im in imgs if "thumb" in (im.get("class") or [])), None
                    )
                # 우선순위 3: 첫 번째 이미지
                if not keep:
                    keep = imgs[0]

                # 나머지 제거 + keep에 'thumb' 클래스 보장
                for im in imgs:
                    if im is not keep:
                        im.decompose()
                cls = set(keep.get("class") or [])
                if "thumb" not in cls:
                    cls.add("thumb")
                    keep["class"] = list(cls)

            # 비어 있으면 제거
            if not tw.find("img", class_="thumb"):
                tw.decompose()

        # 4) 편집용 속성 정리
        for el in [div, head] + ([tw] if tw is not None else []) + list(div.find_all(True)):
            if hasattr(el, "attrs"):
                el.attrs.pop("contenteditable", None)
                el.attrs.pop("draggable", None)
                cls = el.get("class")
                if cls:
                    el["class"] = [c for c in cls if c != "editable"]

    return str(soup)


def make_clean_block_html_for_master(card_name: str, resource_dir: Path) -> str:
    """초기화/신규 카드용 '깨끗한 기본 카드' HTML 문자열 생성(툴바 없음)"""
    jpg = _fs_thumb_path_any(resource_dir, card_name)
    if jpg is not None:
        jpg_name = jpg.name
        thumb_html = f"""
      <div class="thumb-wrap">
        <img class="thumb" src="resource/{card_name}/thumbs/{jpg_name}" alt="썸네일" />
      </div>"""
    else:
        thumb_html = ""  # ← 빈 래퍼 생성 금지

    return f"""
<div class="card" data-card="{card_name}">
  <div class="card-head">
    <h2>{card_name}</h2>
    {thumb_html}
  </div>
  <div class="inner">
    <!-- 새 카드 기본 본문 -->
  </div>
</div>""".strip()
