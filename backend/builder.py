from pathlib import Path
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
from typing import Tuple
import os
import hashlib
import shutil
import uuid
import logging

from backend.constants import PUBLISH_CSS, CSS_PREFIX
from backend.fsutil import read_card_id, write_card_id

log = logging.getLogger("suksukidx")

TOOLBAR_HTML = """
<div class="card-actions">
  <button class="btn btnEditOne">편집 종료</button>
  <button class="btn btnSaveOne" disabled>저장</button>
  <button class="btn btnThumb">썸네일 갱신</button>
  <button class="btn btnAddNote">메모 추가</button>
</div>
""".strip()


def run_sync_all(
    resource_dir: Path, thumb_width: int = 640, *, scan_only: bool = False
) -> int | Dict[str, Any]:
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
        from backend.thumbs import scan_and_make_thumbs
        # P5-썸네일: sync에서는 성능을 위해 기존 썸네일이 있으면 유지
        #  - 캡처 후보 X + 썸네일 O → 삭제
        #  - 캡처 후보 O + 썸네일 X → 1회 생성
        ok = scan_and_make_thumbs(resource_dir, refresh=False, width=thumb_width)
        return 0 if ok else 1
    except Exception as e:
        log.error("[scan] internal thumbnail scan failed: %s", str(e))
        return 1


# ---------- 카드 ID 보장 (P3-1) ----------
def ensure_card_ids(resource_dir: Path) -> dict[str, str]:
    """
    resource/ 하위 카드 폴더에 .suksukidx.id 를 보장하고,
    {folder_name: card_id} 매핑을 반환한다.

    - 숨김 폴더(. 시작)와 'thumbs' 폴더는 제외
    - 중복 ID가 발견되면 후순위 폴더에 새 UUID를 발급하여 충돌을 해소
    """
    # read_card_id / write_card_id 는 항상 존재해야 한다(패키지/패키징 일관성)

    folder_to_id: dict[str, str] = {}
    used_ids: dict[str, str] = {}

    try:
        entries = sorted(
            [
                p
                for p in resource_dir.iterdir()
                if p.is_dir() and not p.name.startswith(".")
            ],
            key=lambda p: p.name,
        )
    except Exception as e:
        log.warning("[id] failed to list resource dir for ids: %s", str(e))
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
                log.info("[id] create %s -> %s", d.name, cid)
            except Exception as e:
                log.warning("[id] failed to write id for %s: %s", d.name, str(e))
                continue

        # 중복 ID 해소: 이미 사용 중이면 새로 발급
        if cid in used_ids and used_ids[cid] != d.name:
            new_cid = str(uuid.uuid4())
            try:
                write_card_id(dir_str, new_cid)
                log.warning("[id] duplicate detected for %s (old:%s); reassigned -> %s", d.name, cid, new_cid)
                cid = new_cid
            except Exception as e:
                log.warning("[id] failed to fix duplicate id for %s: %s", d.name, str(e))
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
            [
                p
                for p in resource_dir.iterdir()
                if p.is_dir() and not p.name.startswith(".")
            ],
            key=lambda p: p.name,
        )
    except Exception as e:
        log.error("[SCAN] failed to list resource dir: %s", str(e))
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
            rel_path = (
                f"{resource_dir.name}/{d.name}" if d.parent == resource_dir else str(d)
            )

            folders.append(
                {
                    "slug": slug,
                    "path": rel_path,
                    "title": title,
                    "thumb_exists": bool(has_thumb),
                    "mtime": float(mtime),
                }
            )
            log.info("[SCAN] %s ✓ (thumb:%s)", slug, ("Y" if has_thumb else "N"))

        except Exception as e:
            errors += 1
            log.warning("[SCAN] %s ⚠ %s", d.name, str(e))

    return {
        "folders": folders,
        "stats": {"count": len(folders), "thumbs": thumb_count, "errors": errors},
    }


# ---------- CSS 해시 배포 ----------
def _read_publish_css(resource_dir: Path) -> Optional[bytes]:
    """
    publish.css 를 읽어 bytes로 반환.
    - PyInstaller(one-folder)에서는 backend 패키지가 dist/.../_internal/backend 아래에 위치하므로
      (즉, 이 파일(__file__) 기준으로 ui/ 폴더가 존재)
      `Path(__file__).parent / "ui" / "publish.css"` 를 최우선으로 본다.
    - 개발환경(소스 실행)에서는 기존처럼 PUBLISH_CSS(상대경로)도 fallback으로 본다.
    """
    # 1) 패키징/런타임 우선 경로: dist/.../_internal/backend/ui/publish.css
    ui_css = Path(__file__).resolve().parent / "ui" / "publish.css"
    if ui_css.exists():
        return ui_css.read_bytes()

    # 2) 기존 방식 fallback: (프로젝트 루트 기준) <base>/<PUBLISH_CSS>
    base = resource_dir.parent
    p = base / PUBLISH_CSS
    if p.exists():
        return p.read_bytes()
    return None


def _read_master_css(resource_dir: Path) -> Optional[bytes]:
    """
    master.css 를 읽어 bytes로 반환.
    publish.css 가 없는 환경(또는 디버그)에서 resource에 master.css를 '실제로' 배포하기 위해 필요.
    """
    # 1) 패키징/런타임 우선 경로: dist/.../_internal/backend/ui/master.css
    ui_css = Path(__file__).resolve().parent / "ui" / "master.css"
    if ui_css.exists():
        return ui_css.read_bytes()

    # 2) 개발환경 fallback: (프로젝트 루트 기준) resource_dir.parent/master.css
    base = resource_dir.parent
    p = base / "master.css"
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
    - publish.css 가 없으면 master.css를 resource 루트/각 폴더에 '실제로' 배포하고 "master.css" 반환
    """
    css = _read_publish_css(resource_dir)
    if css is None:
        # ✅ 안전 폴백: master.css를 실제로 배포해 링크가 깨지지 않게 한다
        master_css = _read_master_css(resource_dir)
        if master_css is None:
            # 여기까지 오면 진짜로 CSS 소스가 없는 상태
            log.error("[css] publish.css/master.css not found; fallback to master.css (missing)")
            return "master.css"

        basename = "master.css"

        # 루트 배포
        root_target = resource_dir / basename
        _write_if_changed(root_target, master_css)

        # 각 폴더 배포
        for d in sorted(
            p for p in resource_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
        ):
            if d.name.lower() == "thumbs":
                continue
            target = d / basename
            _write_if_changed(target, master_css)

        log.info("[css] deployed %s to root and folders (fallback)", basename)
        return basename

    h = _sha1_12(css)
    basename = f"{CSS_PREFIX}.{h}.css"

    # 루트 배포
    root_target = resource_dir / basename
    _write_if_changed(root_target, css)
    _cleanup_old_css(resource_dir, basename)

    # 각 폴더 배포
    for d in sorted(
        p for p in resource_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
    ):
        if d.name.lower() == "thumbs":
            continue
        target = d / basename
        _write_if_changed(target, css)
        _cleanup_old_css(d, basename)

    log.info("[css] deployed %s to root and folders", basename)
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
        if thumb_src
        else ""
    )
    editable_attr = ' contenteditable="true"' if editable else ""
    editable_cls = " editable" if editable else ""
    data_id_attr = f' data-card-id="{card_id}"' if card_id else ""
    data_hidden = (
        f' data-hidden="{str(bool(hidden)).lower()}"' if hidden is not None else ""
    )
    data_order = f' data-order="{order}"' if isinstance(order, int) else ""
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


def render_master_index(
    folders: list[dict], *, css_basename: str = "master.css"
) -> str:
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
    blocks_html = "\n".join(blocks)
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
  {blocks_html}
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
