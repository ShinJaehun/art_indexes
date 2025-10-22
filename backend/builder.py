from pathlib import Path
from bs4 import BeautifulSoup

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
        print(f"❌ internal thumbnail scan failed: {e}")
        return 1


def _folder_block_html(
    title: str,
    inner_html: str,
    thumb_src: str | None = None,
    *,
    include_toolbar: bool = False,
    editable: bool = False,
) -> str:
    toolbar = TOOLBAR_HTML if include_toolbar else ""
    # 빈 thumb-wrap 제거: 썸네일 있을 때만 출력
    thumb_wrap = (
        f'<div class="thumb-wrap"><img class="thumb" src="{thumb_src}" alt="썸네일"/></div>'
        if thumb_src else ''
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
    resource/master_index.html(캐시) 렌더
    - 툴바/편집 속성 없음
    - master.css 링크 포함
    """
    blocks = []
    for f in folders:
        blocks.append(
            _folder_block_html(
                title=f.get("title", ""),
                inner_html=f.get("html", ""),
                thumb_src=f.get("thumb"),
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
  <title>Art Index — Master</title>
  <link rel="stylesheet" href="master.css"/>
</head>
<body>
  {'\n'.join(blocks)}
</body>
</html>
""".strip()

    # 마스터 캐시에도 툴바는 없어야 함
    return dedupe_toolbar(html, mode="child")


def render_child_index(title: str, html_body: str, thumb_src: str | None) -> str:
    block = _folder_block_html(
        title=title,
        inner_html=html_body,
        thumb_src=thumb_src,
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
  <link rel="stylesheet" href="../master.css"/>
</head>
<body>
  {block}
  {back_link}
</body>
</html>
""".strip()

    return dedupe_toolbar(html, mode="child")


def dedupe_toolbar(html: str, *, mode: str = "master") -> str:
    """
    mode="master": 각 .folder마다 .folder-actions 1개만 유지
    mode="child" : .folder-actions 전부 제거
    """
    soup = BeautifulSoup(html, "html.parser")
    folders = soup.select(".folder")

    for folder in folders:
        actions = folder.select(".folder-actions")
        if not actions:
            continue

        if mode == "child":
            for node in actions:
                node.decompose()
            continue

        keep = actions[0]
        for node in actions[1:]:
            node.decompose()

        head = folder.select_one(".folder-head")
        if head and keep.parent != head:
            keep.extract()
            head.append(keep)

    return str(soup)
