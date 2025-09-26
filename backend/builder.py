import sys
import subprocess
from bs4 import BeautifulSoup
from pathlib import Path
from html import escape
from thumbs import _safe_name  # ← 추가

# ANNO: 이 모듈의 역할
# - run_sync_all: 리소스 디렉토리(cwd)를 바꿔 'build_art_indexes.py'를 직접 실행한다.
#   * 외부 프로세스 호출(서브프로세스)이므로 실패/반환코드로만 성공여부를 판단한다.
# - rebuild_master_from_sources: resource/<폴더> 구조만을 읽어 순수 HTML 블록을 구성한다.
#   * 현재 구현은 .folder-actions(버튼)까지 포함해 "관리 UI를 가진 카드"를 생성한다.
#
# HAZARD(yesterday): rebuild_master_from_sources가 생성하는 블록은 버튼/편집 UI까지 포함한다.
# - 이 결과를 api.rebuild_master()가 master_content.html로 재주입하면, 저장물에 버튼이 남아 이후 중복 삽입/경계 붕괴를 유발한다.
# - 리팩토링 시 이 함수는 "콘텐츠만"(예: .inner) 또는 화이트리스트된 태그만 생성하도록 조정 필요. (지금은 주석만)

TOOLBAR_HTML = """
<div class="folder-actions">
  <button class="btn btnEditOne">편집 종료</button>
  <button class="btn btnSaveOne" disabled>저장</button>
  <button class="btn btnThumb">썸네일 갱신</button>
  <button class="btn btnAddNote">메모 추가</button>
</div>
""".strip()


def run_sync_all(resource_dir: Path, thumb_width: int = 640) -> int:
    """
    리소스 전체 썸네일 스캔/생성만 수행(HTML 생성 없음).
    SSOT: HTML 생성은 MasterApi._push_master_to_resource()만 담당.
    """
    try:
        from thumbs import scan_and_make_thumbs

        ok = scan_and_make_thumbs(resource_dir, refresh=True, width=thumb_width)
        return 0 if ok else 1
    except Exception as e:
        print(f"❌ internal thumbnail scan failed: {e}", file=sys.stderr)
        return 1


def _folder_block_html(
    title: str,
    inner_html: str,
    thumb_src: str | None = None,
    *,
    include_toolbar: bool = False,  # 캐시 출력물: False
    editable: bool = False,  # 캐시 출력물: False
) -> str:
    """
    폴더 하나를 렌더하는 공통 블록.
    - include_toolbar: webview 편집 화면에서만 True (파일 출력물은 False)
    - editable: webview 편집 화면에서만 True (파일 출력물은 False)
    """
    toolbar = TOOLBAR_HTML if include_toolbar else ""
    thumb_wrap = (
        f'<div class="thumb-wrap"><img class="thumb" src="{thumb_src}" alt="썸네일"/></div>'
        if thumb_src
        else '<div class="thumb-wrap"></div>'
    )
    editable_attr = ' contenteditable="true"' if editable else ""
    editable_cls = " editable" if editable else ""
    return f"""
<div class="folder">
  <div class="folder-head">
    <h2>{title}</h2>
    {toolbar}
    {thumb_wrap}
  </div>
  <div class="inner{editable_cls}"{editable_attr}>
    {inner_html}
  </div>
</div>
""".strip()


def render_master_index(folders: list[dict]) -> str:
    """
    folders: [{ 'title': str, 'html': str, 'thumb': str|None }, ...]
    resource/master_index.html(캐시)을 렌더.
    - 툴바 없음
    - contenteditable 없음
    """
    blocks = []
    for f in folders:
        block = _folder_block_html(
            title=f.get("title", ""),
            inner_html=f.get("html", ""),
            thumb_src=f.get("thumb"),
            include_toolbar=False,  # 캐시에는 툴바 없음
            editable=False,
        )
        blocks.append(block)

    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Art Index — Master</title>
  <link rel="stylesheet" href="master.css"/>
  <!-- 필요 CSS/JS 링크 -->
</head>
<body>
  {'\n'.join(blocks)}
</body>
</html>
""".strip()

    # 안전망: 혹시라도 중첩 삽입되었으면 제거
    return dedupe_toolbar(html, mode="child")  # 마스터 캐시도 툴바 없어야 함


def render_child_index(title: str, html_body: str, thumb_src: str | None) -> str:
    """
    단일 폴더의 하위 index.html 렌더(툴바 없음).
    """
    block = _folder_block_html(
        title=title,
        inner_html=html_body,
        thumb_src=thumb_src,
        include_toolbar=False,
        editable=False,  # 캐시 출력물엔 편집 속성 없음
    )

    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>
  <!-- 필요 CSS/JS 링크(출력용) -->
</head>
<body>
  {block}
</body>
</html>
""".strip()

    # 안전망: 혹시라도 남아있으면 전부 제거
    return dedupe_toolbar(html, mode="child")


def dedupe_toolbar(html: str, *, mode: str = "master") -> str:
    """
    mode="master": 각 .folder마다 .folder-actions를 1개만 남기고 제거
    mode="child" : 모든 .folder-actions 전부 제거
    """
    soup = BeautifulSoup(html, "html.parser")
    folders = soup.select(".folder")

    for folder in folders:
        actions = folder.select(".folder-actions")
        if not actions:
            continue

        if mode == "child":
            # 하위 인덱스: 절대 없어야 함 → 전부 삭제
            for node in actions:
                node.decompose()
            continue

        # master 모드: 1개만 유지하고 나머지는 제거
        keep = actions[0]
        for node in actions[1:]:
            node.decompose()

        # 혹시 .folder-actions가 .folder-head 바깥/안쪽 이상한 위치면 교정
        head = folder.select_one(".folder-head")
        if head and keep.parent != head:
            keep.extract()
            head.append(keep)

    return str(soup)
