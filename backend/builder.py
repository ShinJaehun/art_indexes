from pathlib import Path
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
from typing import Tuple
import os
import hashlib
import shutil
import uuid

try:
    from .constants import PUBLISH_CSS, CSS_PREFIX
except Exception:
    PUBLISH_CSS = "backend/ui/publish.css"
    CSS_PREFIX = "master"

try:
    # P3-1: 카드 ID 파일 헬퍼
    from .fsutil import read_card_id, write_card_id
except Exception:
    try:
        from fsutil import read_card_id, write_card_id
    except Exception:
        read_card_id = None
        write_card_id = None

TOOLBAR_HTML = """
<div class="card-actions">
  <button class="btn btnEditOne">편집 종료</button>
  <button class="btn btnSaveOne" disabled>저장</button>
  <button class="btn btnThumb">썸네일 갱신</button>
  <button class="btn btnAddNote">메모 추가</button>
</div>
""".strip()


def run_sync_all(resource_dir: Path, thumb_width: int = 640, *, scan_only: bool = False) -> int | Dict[str, Any]:
    """
    리소스 전체 썸네일 스캔/생성만 수행(HTML 생성 없음).
    SSOT 스캔 단일화 + 썸네일 리빌드 엔트리.
    - scan_only=True: 파일시스템(SSOT)을 스캔하여 표준 JSON을 반환 (읽기 전용).
    - scan_only=False(기본): 기존처럼 썸네일 스캔/생성만 수행하고 종료 코드(int) 반환.

    SSOT: HTML 생성은 MasterApi._push_master_to_resource()만 담당.
    """
    if scan_only:
        return scan_ssot(resource_dir)
    try:
        # 패키지 실행/스크립트 실행 모두 지원
        try:
            from .thumbs import scan_and_make_thumbs
        except Exception:
            from thumbs import scan_and_make_thumbs
        ok = scan_and_make_thumbs(resource_dir, refresh=True, width=thumb_width)
        return 0 if ok else 1
    except Exception as e:
        print(f"❌ internal thumbnail scan failed: {e}")
        return 1

# ---------- 카드 ID 보장 (P3-1) ----------
def ensure_card_ids(resource_dir: Path) -> dict[str, str]:
    """
    resource/ 하위 카드 폴더에 .suksukidx.id 를 보장하고,
    {folder_name: card_id} 매핑을 반환한다.

    - 숨김 폴더(. 시작)와 'thumbs' 폴더는 제외
    - 중복 ID가 발견되면 후순위 폴더에 새 UUID를 발급하여 충돌을 해소
    """
    if read_card_id is None or write_card_id is None:
        # 헬퍼를 사용할 수 없는 환경에서는 조용히 폴백(이행기 대비)
        # 호출 측에서 이 경우 ID 의존 로직을 건너뛸 수 있다.
        return {}

    folder_to_id: dict[str, str] = {}
    used_ids: dict[str, str] = {}

    try:
        entries = sorted(
            [p for p in resource_dir.iterdir() if p.is_dir() and not p.name.startswith(".")],
            key=lambda p: p.name,
        )
    except Exception as e:
        print(f"[id] WARN: failed to list resource dir for ids: {e}")
        return {}

    for d in entries:
        if d.name.lower() == "thumbs":
            continue
        
        dir_str = str(d)
        cid = read_card_id(dir_str)

        if not cid:
            cid = str(uuid.uuid4())
            try:
                write_card_id(dir_str, cid)
                print(f"[id] create {d.name} -> {cid}")
            except Exception as e:
                print(f"[id] WARN: failed to write id for {d.name}: {e}")
                continue
            
        # 중복 ID 해소: 이미 사용 중이면 새로 발급
        if cid in used_ids and used_ids[cid] != d.name:
            new_cid = str(uuid.uuid4())
            try:
                write_card_id(dir_str, new_cid)
                print(
                    f"[id] duplicate detected for {d.name} (old:{cid}); "
                    f"reassigned -> {new_cid}"
                )
                cid = new_cid
            except Exception as e:
                print(f"[id] WARN: failed to fix duplicate id for {d.name}: {e}")
                continue
            
        used_ids[cid] = d.name
        folder_to_id[d.name] = cid

    return folder_to_id

def _make_slug(name: str) -> str:
    """
    파일시스템 세이프 슬러그(최소 규칙):
    - 앞뒤 공백 제거
    - 경로 구분자 제거
    - 공백 → '_' 치환
    (한글/숫자/일부 기호는 그대로 둡니다)
    """
    name = name.strip().replace(os.sep, " ").replace("/", " ")
    while "  " in name:
        name = name.replace("  ", " ")
    return name.replace(" ", "_")


def _iter_thumb_files(thumb_dir: Path):
    if not thumb_dir.exists() or not thumb_dir.is_dir():
        return
    for p in thumb_dir.iterdir():
        if p.is_file() and not p.name.startswith("."):
            yield p


def _latest_mtime_of_tree(root: Path) -> float:
    latest = root.stat().st_mtime if root.exists() else 0.0
    try:
        for base, _, files in os.walk(root):
            for f in files:
                try:
                    t = (Path(base) / f).stat().st_mtime
                    if t > latest:
                        latest = t
                except Exception:
                    # 파일 접근 실패는 무시(스캔 전체 중단 방지)
                    pass
    except Exception:
        pass
    return latest


def scan_ssot(resource_dir: Path) -> Dict[str, Any]:
    """
    resource/ 폴더를 SSOT로 스캔하여 표준 JSON 구조를 반환.
    반환 예:
    {
      "folders": [
        {"slug": "...", "path": "resource/...", "title": "...",
         "thumb_exists": True, "mtime": 1729570000.0}
      ],
      "stats": {"count": 12, "thumbs": 11, "errors": 0}
    }
    """
    folders: List[Dict[str, Any]] = []
    errors = 0

    try:
        entries = sorted(
            [p for p in resource_dir.iterdir() if p.is_dir() and not p.name.startswith(".")],
            key=lambda p: p.name,
        )
    except Exception as e:
        print(f"❌ [SCAN] failed to list resource dir: {e}")
        return {"folders": [], "stats": {"count": 0, "thumbs": 0, "errors": 1}}

    thumb_count = 0
    for d in entries:
        try:
            title = d.name.replace("_", " ")
            slug = _make_slug(d.name)
            thumbs_dir = d / "thumbs"
            has_thumb = any(True for _ in _iter_thumb_files(thumbs_dir))
            if has_thumb:
                thumb_count += 1

            mtime = _latest_mtime_of_tree(d)
            rel_path = f"{resource_dir.name}/{d.name}" if d.parent == resource_dir else str(d)

            folders.append(
                {
                    "slug": slug,
                    "path": rel_path,
                    "title": title,
                    "thumb_exists": bool(has_thumb),
                    "mtime": float(mtime),
                }
            )
            print(f"[SCAN] {slug} ✓ (thumb:{'Y' if has_thumb else 'N'})")
        except Exception as e:
            errors += 1
            print(f"[SCAN] {d.name} ⚠️  {e}")

    return {
        "folders": folders,
        "stats": {"count": len(folders), "thumbs": thumb_count, "errors": errors},
    }


# ---------- CSS 해시 배포 ----------
def _read_publish_css(resource_dir: Path) -> Optional[bytes]:
    """backend/ui/publish.css 를 최우선으로 읽고, 없으면 None 반환"""
    base = resource_dir.parent  # 프로젝트 루트
    p = base / PUBLISH_CSS
    if p.exists():
        return p.read_bytes()
    return None


def _sha1_12(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:12]


def _write_if_changed(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            if target.read_bytes() == data:
                return
        except Exception:
            pass
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)

def _cleanup_old_css(dirpath: Path, keep_name: str) -> int:
    """dirpath 내 {CSS_PREFIX}.*.css 중 keep_name 이외 삭제"""
    removed = 0
    if not dirpath.exists():
        return removed
    for p in dirpath.glob(f"{CSS_PREFIX}.*.css"):
        if p.name != keep_name:
            try:
                p.unlink()
                removed += 1
            except Exception:
                pass
    return removed


def ensure_css_assets(resource_dir: Path) -> str:
    """
    publish.css 를 읽어 해시 파일로 배포하고, 사용해야 할 CSS 파일명을 반환.
    - 루트: resource/master.<HASH>.css
    - 각 폴더: resource/<folder>/master.<HASH>.css
    - publish.css 가 없으면 "master.css" 로 폴백(이전 방식 유지)
    """
    css = _read_publish_css(resource_dir)
    if css is None:
        # 안전 폴백: 기존 master.css 체계 유지
        print("[css] publish.css not found; fallback to master.css")
        return "master.css"

    h = _sha1_12(css)
    basename = f"{CSS_PREFIX}.{h}.css"

    # 루트 배포
    root_target = resource_dir / basename
    _write_if_changed(root_target, css)
    _cleanup_old_css(resource_dir, basename)

    # 각 폴더 배포
    for d in sorted(p for p in resource_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if d.name.lower() == "thumbs":
            continue
        target = d / basename
        _write_if_changed(target, css)
        _cleanup_old_css(d, basename)

    print(f"[css] deployed {basename} to root and folders")
    return basename
# ----------------------------------------

def _meta_from_dict(d: Dict[str, Any]) -> Tuple[Optional[bool], Optional[int]]:
    """folders 요소(dict)에서 (hidden, order) 안전 추출"""
    hidden = d.get("hidden", None)
    if isinstance(hidden, str):
        hidden = hidden.lower() == "true"
    elif hidden is not None:
        hidden = bool(hidden)

    order = d.get("order", None)
    try:
        order = int(order) if order is not None and str(order).strip() != "" else None
    except Exception:
        order = None

    return hidden, order

def _classes_for_meta(hidden: Optional[bool]) -> str:
    classes = []
    if hidden:
        classes.append("is-hidden")
    return (" " + " ".join(classes)) if classes else ""

def _card_block_html(
    title: str,
    inner_html: str,
    thumb_src: str | None = None,
    *,
    card_id: str | None = None,
    hidden: Optional[bool] = None,
    order: Optional[int] = None,
    include_toolbar: bool = False,
    editable: bool = False,
) -> str:
    meta_cls = _classes_for_meta(hidden)
    toolbar = TOOLBAR_HTML if include_toolbar else ""
    # 빈 thumb-wrap 제거: 썸네일 있을 때만 출력
    thumb_wrap = (
        f'<div class="thumb-wrap"><img class="thumb" src="{thumb_src}" alt="썸네일"/></div>'
        if thumb_src else ''
    )
    editable_attr = ' contenteditable="true"' if editable else ""
    editable_cls = " editable" if editable else ""
    data_id_attr = f' data-card-id="{card_id}"' if card_id else ""
    data_hidden = f' data-hidden="{str(bool(hidden)).lower()}"' if hidden is not None else ""
    data_order  = f' data-order="{order}"' if isinstance(order, int) else ""
    return f"""
<div class="card{meta_cls}" data-card="{title}"{data_id_attr}{data_hidden}{data_order}>
  <div class="card-head">
    <h2>{title}</h2>
    {toolbar}
    {thumb_wrap}
  </div>
  <div class="inner{editable_cls}"{editable_attr}>
    {inner_html}
  </div>
</div>
""".strip()


def render_master_index(folders: list[dict], *, css_basename: str = "master.css") -> str:
    """
    resource/master_index.html(캐시) 렌더
    - 툴바/편집 속성 없음(배포 캐시에는 편집 UI가 없어야 함)
    - CSS 링크는 css_basename 사용 (예: master.<HASH>.css)
    """
    # 정렬은 호출 측(MasterApi._push_master_to_resource)이 책임지고,
    # 여기서는 전달받은 순서를 그대로 사용한다(SSOT = master_content 순서).
    blocks: List[str] = []
    for f in folders:
        card_id = f.get("id") or f.get("card_id")
        hidden, order = _meta_from_dict(f)

        if hidden:
            continue
        
        blocks.append(
            _card_block_html(
                title=f.get("title", ""),
                inner_html=f.get("html", ""),
                thumb_src=f.get("thumb"),
                card_id=card_id,
                hidden=hidden,
                order=order,
                include_toolbar=False,
                editable=False,
             )
         )
    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>SukSuk Index — Master</title>
  <link rel="stylesheet" href="{css_basename}"/>
</head>
<body>
  {'\n'.join(blocks)}
</body>
</html>
""".strip()

    # 배포 캐시에는 툴바가 없어야 하므로 전부 제거
    return dedupe_toolbar(html, mode="child")


def render_child_index(
    title: str,
    html_body: str,
    thumb_src: str | None,
    *,
    css_basename: str = "master.css",
    card_id: str | None = None,
) -> str:
    # child는 메타 표시가 필수는 아니나, 디버깅 편의를 위해 최소한 data-card-id만 유지
    block = _card_block_html(
        title=title,
        inner_html=html_body,
        thumb_src=thumb_src,
        card_id=card_id,
        include_toolbar=False,
        editable=False,
    )

    back_link = (
        '<a class="back-to-master" href="../master_index.html">⬅ 전체 목록으로</a>'
    )

    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>
  <link rel="stylesheet" href="{css_basename if css_basename.startswith('http') or css_basename.startswith('/') else '../' + css_basename}"/>
</head>
<body>
  {block}
  {back_link}
</body>
</html>
""".strip()

    # 배포 캐시에는 툴바가 없어야 하므로 전부 제거
    return dedupe_toolbar(html, mode="child")


def dedupe_toolbar(html: str, *, mode: str = "master") -> str:
    """
    mode="master": 각 .card마다 .card-actions 1개만 유지
    mode="child" : .card-actions 전부 제거
    """
    soup = BeautifulSoup(html, "html.parser")
    folders = soup.select(".card")

    for folder in folders:
        actions = folder.select(".card-actions")
        if not actions:
            continue

        if mode == "child":
            for node in actions:
                node.decompose()
            continue

        keep = actions[0]
        for node in actions[1:]:
            node.decompose()

        head = folder.select_one(".card-head")
        if head and keep.parent != head:
            keep.extract()
            head.append(keep)

    return str(soup)
