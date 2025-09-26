from pathlib import Path
from typing import Dict, Any, Union

import re
import time
import os  # fail test 직후 삭제

from thumbs import make_thumbnail_for_folder
from thumbs import _safe_name as _thumb_safe_name

from builder import run_sync_all, render_master_index, render_child_index

try:
    from bs4 import BeautifulSoup, Comment
except Exception:
    BeautifulSoup = None  # bs4 없으면 일부 기능 제한
    Comment = None

# -------- 상수 --------
ROOT_MASTER = "master_index.html"
FOLDER_INDEX = "index.html"

# ANNO: 정규식 본문 추출. 편집 후 body 속성/스크립트 배치가 달라지면 실패 가능 → 가능하면 bs4 권장.
_BODY_RE = re.compile(r"<body[^>]*>([\s\S]*?)</body>", re.IGNORECASE)
# ANNO: resource 접두어를 붙이지 않을 예외 접두사.
# HAZARD: mailto:, data:, tel: 등은 여기에 포함되어 있지 않다 → 예외 케이스 추가 여지.
_SKIP_PREFIX = re.compile(
    r"^(https?://|/|\.\./|#|resource/|mailto:|tel:|data:)", re.IGNORECASE
)


# -------- 유틸 --------
def _extract_body_inner(html_text: str) -> str:
    m = _BODY_RE.search(html_text or "")
    return m.group(1).strip() if m else (html_text or "")


def _prefix_resource_paths_for_root(html: str) -> str:
    """root(index.html)에서 사용할 내용에 대해 src/href 앞에 resource/ 접두어를 붙임(이미 절대/외부/..//resource 는 제외)"""

    def fix_src(m):
        val = m.group(2)
        return (
            f'{m.group(1)}resource/{val}"'
            if not _SKIP_PREFIX.search(val)
            else m.group(0)
        )

    html = re.sub(r'(<img[^>]+src=")([^"]+)"', fix_src, html, flags=re.IGNORECASE)
    html = re.sub(r'(<a[^>]+href=")([^"]+)"', fix_src, html, flags=re.IGNORECASE)
    return html


def _strip_back_to_master(div_html: str) -> str:
    """폴더 카드 안의 '⬅ 전체 목록으로' 링크는 마스터에선 제거(이미지 감싸면 unwrap)"""
    if BeautifulSoup is None:
        # 정규식 폴백: 단순 제거
        return re.sub(
            r'<a[^>]+href="\.\./master_index\.html"[^>]*>.*?</a>',
            "",
            div_html,
            flags=re.IGNORECASE | re.DOTALL,
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


def _extract_inner_html_only(div_folder_html: str) -> str:
    """
    <div class="folder"> 블록에서 .inner의 '자식 노드들'만 문자열로 반환.
    헤더/툴바/썸네일은 포함되지 않음.
    """
    if BeautifulSoup is None:
        # 간단 폴백(정규식)
        m = re.search(
            r'<div\s+class="inner"[^>]*>([\s\S]*?)</div>',
            div_folder_html,
            re.IGNORECASE,
        )
        inner = m.group(1) if m else ""
        # 주석 제거
        inner = re.sub(r"<!--[\s\S]*?-->", "", inner)
        return inner.strip()

    soup = BeautifulSoup(div_folder_html, "html.parser")
    folder = soup.find("div", class_="folder") or soup
    inner = folder.find("div", class_="inner")
    if not inner:
        return ""
    # 🔑 코멘트 노드 제거(placeholder가 텍스트로 노출되는 것 방지)
    for node in list(inner.contents):
        if Comment is not None and isinstance(node, Comment):
            node.extract()
    return "".join(str(x) for x in inner.contents).strip()


def _clean_for_publish(div_html: str) -> str:
    """
    편집용 DOM(div.folder)을 배포용으로 정화한다.
    - 제거: .folder-actions, .btn* 요소, contenteditable/draggable, 모든 on* 이벤트, data-* 속성, style
    - 화이트리스트: 태그/속성 제한 (img/a 중심)
    - 주의: master_content.html 자체는 수정하지 않고, 출력용 변환에만 사용
    """
    if BeautifulSoup is None:
        # 폴백(간소): 가장 위험한 것들만 제거
        html = re.sub(
            r'<[^>]+class="[^"]*\bfolder-actions\b[^"]*"[^>]*>.*?</[^>]+>',
            "",
            div_html,
            flags=re.I | re.S,
        )
        html = re.sub(
            r'<[^>]+class="[^"]*\bbtn[^"]*"[^>]*>.*?</[^>]+>',
            "",
            html,
            flags=re.I | re.S,
        )
        # 속성류 제거
        html = re.sub(r'\scontenteditable="[^"]*"', "", html, flags=re.I)
        html = re.sub(r'\sdraggable="[^"]*"', "", html, flags=re.I)
        html = re.sub(r'\sdata-[\w-]+="[^"]*"', "", html, flags=re.I)
        html = re.sub(
            r'\son[a-zA-Z]+\s*=\s*"[^"]*"', "", html, flags=re.I
        )  # onClick 등
        html = re.sub(r'\sstyle="[^"]*"', "", html, flags=re.I)
        return html

    soup = BeautifulSoup(div_html, "html.parser")

    # 1) 제어 UI 제거
    for n in soup.select('.folder-actions, .btn, [class^="btn"]'):
        n.decompose()

    # 2) 속성 정리 + 태그 화이트리스트
    allowed_tags = {
        "div",
        "p",
        "img",
        "a",
        "ul",
        "ol",
        "li",
        "br",
        "h2",
        "h3",
        "h4",
        "span",
        "strong",
        "em",
    }
    allowed_attrs = {
        "img": {"src", "alt", "title", "width", "height"},
        "a": {"href", "title", "target", "rel"},
        # 나머지는 최소화(필요 시 확장)
    }

    for tag in list(soup.find_all(True)):
        # 이벤트/데이터/편집 속성 제거(전 태그 공통)
        bad_attrs = []
        for attr in list(tag.attrs.keys()):
            if attr.lower().startswith("on"):  # onClick 등
                bad_attrs.append(attr)
            if attr.lower().startswith("data-"):  # data-*
                bad_attrs.append(attr)
            if attr.lower() in ("contenteditable", "draggable", "style"):
                bad_attrs.append(attr)
        for a in bad_attrs:
            tag.attrs.pop(a, None)

        # 태그 화이트리스트 적용
        if tag.name not in allowed_tags:
            tag.unwrap()
            continue

        # 태그별 허용 속성만 유지
        if tag.name in allowed_attrs:
            keep = allowed_attrs[tag.name]
            for a in list(tag.attrs.keys()):
                if a not in keep and a != "class":  # class는 CSS 위해 허용
                    tag.attrs.pop(a, None)

    return str(soup)


def _adjust_paths_for_folder(
    div_html: str, folder: str, *, for_resource_master: bool = False
) -> str:
    """
    master_content 기준(대개 resource/<폴더>/...)의 경로를 치환.

    - for_resource_master=False (기본): 해당 폴더의 index.html 관점(상대경로 ./...)으로 치환.
    - for_resource_master=True: resource/master_index.html 관점(상대경로 "<folder>/...")로 치환.

    HAZARD(yesterday): 경로만 바꾸고, .folder-actions/.btn/contenteditable 등의 편집/제어 요소는 제거하지 않는다.
    """
    if BeautifulSoup is None:
        # 정규식 폴백
        if not for_resource_master:
            # 폴더 index 관점
            div_html = re.sub(
                rf'(<img[^>]+src=")resource/{re.escape(folder)}/',
                r"\1",
                div_html,
                flags=re.IGNORECASE,
            )
            div_html = re.sub(
                rf'(<a[^>]+href=")resource/{re.escape(folder)}/index\.html"',
                r'\1index.html"',
                div_html,
                flags=re.IGNORECASE,
            )
            div_html = re.sub(
                rf'(<a[^>]+href=")resource/{re.escape(folder)}/',
                r"\1",
                div_html,
                flags=re.IGNORECASE,
            )
            return div_html
        else:
            # resource/master_index 관점
            div_html = re.sub(
                rf'(<img[^>]+src=")resource/{re.escape(folder)}/',
                r"\1" + folder + "/",
                div_html,
                flags=re.IGNORECASE,
            )
            div_html = re.sub(
                rf'(<a[^>]+href=")resource/{re.escape(folder)}/index\.html"',
                r"\1" + folder + '/index.html"',
                div_html,
                flags=re.IGNORECASE,
            )
            div_html = re.sub(
                rf'(<a[^>]+href=")resource/{re.escape(folder)}/',
                r"\1" + folder + "/",
                div_html,
                flags=re.IGNORECASE,
            )
            return div_html

    # BeautifulSoup 사용 분기
    soup = BeautifulSoup(div_html, "html.parser")
    prefix = f"resource/{folder}/"

    for tag in soup.find_all(["img", "a"]):
        if tag.name == "img" and tag.has_attr("src"):
            src = tag["src"]
            if src.startswith(prefix):
                rest = src[len(prefix) :]
                if for_resource_master:
                    tag["src"] = f"{folder}/{rest}"
                else:
                    tag["src"] = rest

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


def _make_clean_block_html_for_master(folder: str, resource_dir: Path) -> str:
    """
    master_content.html에 삽입할 '깨끗한 기본 카드' HTML 문자열을 만든다.
    - .folder-head/h2
    - .thumb-wrap (있으면 썸네일 img 1장)
    - .inner (비어 있음)
    """
    safe = _thumb_safe_name(folder)
    thumb_path = resource_dir / folder / "thumbs" / f"{safe}.jpg"
    thumb_html = (
        f"""
      <div class="thumb-wrap">
        <img class="thumb" src="resource/{folder}/thumbs/{safe}.jpg" alt="썸네일" />
      </div>"""
        if thumb_path.exists()
        else """<div class="thumb-wrap"></div>"""
    )
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


def _ensure_thumb_in_head(div_html: str, folder: str, resource_dir: Path) -> str:
    """
    div.folder HTML에서 .folder-head 내부의 .thumb-wrap이 비어 있으면,
    파일시스템에 존재하는 대표 썸네일을 자동 삽입한다.
    (발행 직전 안전망)
    """
    if BeautifulSoup is None:
        # bs4 없으면 보강 불가 — 그대로 반환
        return div_html

    soup = BeautifulSoup(div_html, "html.parser")
    head = soup.select_one(".folder-head") or soup
    tw = head.select_one(".thumb-wrap")
    if not tw:
        tw = soup.new_tag("div", **{"class": "thumb-wrap"})
        head.append(tw)

    has_img = bool(tw.find("img"))
    if not has_img:
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


def _inject_thumbs_for_preview(html: str, resource_dir: Path) -> str:
    """
    webview 편집 화면에 뿌릴 때만 사용하는 미리보기 보강.
    - 각 .folder의 .thumb-wrap이 비어 있으면 파일시스템에 있는 썸네일 <img>를 주입한다.
    - master_content.html 파일은 수정하지 않음(미리보기 렌더링에만 사용).
    """
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
            continue  # 이미 있음

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


def _persist_thumbs_in_master(html: str, resource_dir: Path) -> str:
    """
    저장 직전에 master_content.html에 '썸네일 이미지를 영구 반영'한다.
    - 각 .folder의 .folder-head/.thumb-wrap을 보정하고,
    - 파일시스템에 썸네일이 있으면 <img class="thumb" ...>를 1개 채워 넣는다.
    - 불필요한 편집 속성(draggable, contenteditable 등)은 제거.
    """
    if BeautifulSoup is None:
        return html

    soup = BeautifulSoup(html or "", "html.parser")

    for div in soup.find_all("div", class_="folder"):
        # 0) 제목(폴더명)
        h2 = div.find("h2")
        if not h2:
            continue
        folder = (h2.get_text() or "").strip()
        if not folder:
            continue

        # 1) head normalize: 없으면 만들고, 순서를 h2 -> thumb-wrap로 정돈
        head = div.find(class_="folder-head")
        if not head:
            head = soup.new_tag("div", **{"class": "folder-head"})
            # h2를 head 안으로 이동
            h2.replace_with(head)
            head.append(h2)

        tw = head.find(class_="thumb-wrap")
        if not tw:
            tw = soup.new_tag("div", **{"class": "thumb-wrap"})
            head.append(tw)

        # 2) .inner 안/주변에서 흩어진 썸네일 이미지가 있으면 head로 이동
        #    (src에 /thumbs/ 포함 혹은 class="thumb" 혹은 alt="썸네일")
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
            # 첫 후보만 사용
            tw.append(candidates[0])

        # 3) 파일시스템 기준으로 최종 보강 (없으면 새로 삽입)
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

        # 4) 편집용 속성 정리
        for el in [div, head, tw] + list(div.find_all(True)):
            if hasattr(el, "attrs"):
                el.attrs.pop("contenteditable", None)
                el.attrs.pop("draggable", None)
                # serializeMaster가 붙였을 수 있는 임시 클래스 제거
                cls = el.get("class")
                if cls:
                    el["class"] = [c for c in cls if c != "editable"]

    return str(soup)


# -------- 메인 API --------
class MasterApi:
    """
    - 화면은 항상 master_content.html을 로드/저장
    - Sync:
        1) run_sync_all()로 리소스 스캔/썸네일(기계 작업)
        2) master_content.html을 **정본**으로 resource/master_index.html과 각 폴더 index.html **덮어쓰기(푸시)**

    pywebview가 js_api 객체의 속성을 직렬화하려다 Path 내부 필드(_drv 등)에 접근해 경고를 내는 문제를 피하기 위해
    공개 속성/프로퍼티에 Path를 노출하지 않는다. 내부적으로는 문자열을 보관하고, 사용할 때만 Path로 변환한다.

    HAZARD(yesterday): _push_master_to_resource는 경로만 조정하고, 버튼/편집 속성 제거는 하지 않는다.
    → 브라우저 UI용 컨트롤이 저장물에 들어가면, 이후 build/Sync에서 중복 삽입/경계 붕괴.
    """

    def __init__(self, base_dir: Union[str, Path]):
        base_dir = Path(base_dir).resolve()
        # 외부로는 문자열만 보관 (pywebview가 객체 속성 스캔 시 안전)
        self._base_dir_str = str(base_dir)
        self._master_file_str = str(base_dir / "master_content.html")
        self._resource_dir_str = str(base_dir / "resource")
        self._resource_master_str = str(Path(self._resource_dir_str) / ROOT_MASTER)

    # ---- 내부 Path 헬퍼 ----
    def _p_base_dir(self) -> Path:
        return Path(self._base_dir_str)

    def _p_master_file(self) -> Path:
        return Path(self._master_file_str)

    def _p_resource_dir(self) -> Path:
        return Path(self._resource_dir_str)

    def _p_resource_master(self) -> Path:
        return Path(self._resource_master_str)

    # ---- 파일 IO ----
    def _read(self, p: Union[str, Path]) -> str:
        p = Path(p)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def _write(self, p: Union[str, Path], s: str) -> None:
        p = Path(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(s, encoding="utf-8")

    # ---- 로드 / 저장 ----
    def get_master(self) -> Dict[str, Any]:
        """
        우선 master_content.html을 보여줌.
        없으면 resource/master_index.html의 body-inner를 추출해 초기화 + 경로접두어 보정 후 반환.
        """
        master_file = self._p_master_file()
        resource_master = self._p_resource_master()

        if master_file.exists():
            raw = self._read(master_file)
            # ✅ 편집 화면 표시용으로만 썸네일 주입 (파일은 수정하지 않음)
            html_for_view = (
                _inject_thumbs_for_preview(raw, self._p_resource_dir())
                if BeautifulSoup is not None
                else raw
            )
            return {"html": html_for_view}

        if resource_master.exists():
            inner = _extract_body_inner(self._read(resource_master))
            inner = _prefix_resource_paths_for_root(inner)
            self._write(master_file, inner)
            # 초기화 직후에도 미리보기 주입
            html_for_view = (
                _inject_thumbs_for_preview(inner, self._p_resource_dir())
                if BeautifulSoup is not None
                else inner
            )
            return {"html": html_for_view}

        return {"html": ""}

    def save_master(self, html: str) -> Dict[str, Any]:
        """편집 저장: master_content.html만 갱신(사용자 작성 HTML 그대로 저장)"""
        # ✅ 저장 전에 썸네일/헤더 보정 → 파일에도 영구 반영
        fixed = _persist_thumbs_in_master(html, self._p_resource_dir())
        self._write(self._p_master_file(), fixed)
        return {"ok": True}

    # ---- 푸시: master_content → resource/*.html ----
    def _push_master_to_resource(self) -> int:
        """
        master_content.html을 소스로 삼아
        - resource/master_index.html
        - resource/<폴더>/index.html
        을 직접 생성/덮어쓴다.
        반환: 처리한 folder 블록 수
        """
        html = self._read(self._p_master_file())
        if not html:
            print("[push] no master_content.html, skip")
            return 0

        if BeautifulSoup is None:
            # 최소 동작(퇴행 방지): 그대로 중단 처리
            print("[push] bs4 missing; cannot safely render without sanitizer/dedupe")
            return 0

        soup = BeautifulSoup(html, "html.parser")
        block_count = 0
        resource_dir = self._p_resource_dir()

        # 마스터 렌더에 전달할 데이터 수집
        folders_for_master: list[dict] = []

        for div in soup.find_all("div", class_="folder"):
            h2 = div.find("h2")
            if not h2:
                continue
            folder = h2.get_text(strip=True)
            block_count += 1

            cleaned_div_html = _clean_for_publish(str(div))

            # 썸네일 자동 보강: thumb-wrap이 비면 파일시스템 기반으로 채워 넣기
            cleaned_div_html = _ensure_thumb_in_head(
                cleaned_div_html, folder, resource_dir
            )

            # 공통: h2/썸네일을 제외한 본문(inner)만 추출
            inner_only = _extract_inner_html_only(cleaned_div_html)

            # 1) 마스터용: resource/master_index 기준 경로로 보정 + back 링크 제거
            inner_for_master = _adjust_paths_for_folder(
                inner_only, folder, for_resource_master=True
            )
            inner_for_master = _strip_back_to_master(inner_for_master)

            # 2) 하위 index.html용: 해당 폴더 기준 상대 경로로 보정
            inner_for_folder = _adjust_paths_for_folder(
                inner_only, folder, for_resource_master=False
            )

            # 썸네일 경로 계산
            safe = _thumb_safe_name(folder)
            thumb_rel_for_master = None
            if (resource_dir / folder / "thumbs" / f"{safe}.jpg").exists():
                # master_index에서는 "<folder>/thumbs/.."
                thumb_rel_for_master = f"{folder}/thumbs/{safe}.jpg"

            # 마스터 렌더 입력 누적
            folders_for_master.append(
                {
                    "title": folder,
                    "html": inner_for_master,
                    "thumb": thumb_rel_for_master,
                }
            )

            # 하위 index.html 생성 (툴바 없음)
            child_html = render_child_index(
                title=folder,
                html_body=inner_for_folder,
                # child 기준 경로: "thumbs/.."
                thumb_src=(f"thumbs/{safe}.jpg" if thumb_rel_for_master else None),
            )
            self._write(self._p_resource_dir() / folder / FOLDER_INDEX, child_html)

        # 마스터(캐시) 생성 (툴바 1회/중복 제거는 builder에서 보장)
        master_html = render_master_index(folders_for_master)
        self._write(self._p_resource_master(), master_html)

        print(f"[push] blocks={block_count} ok=True")
        return block_count

    # ---- 동기화 ----
    def sync(self) -> Dict[str, Any]:
        """
        1) 리소스 스캔/썸네일 등 기계 작업 실행
        2) 사용자 편집본(master_content.html)을 기준으로 resource 쪽 파일들을 덮어씀(푸시)
        3) 결과를 {ok, scanOk, pushOk, errors, metrics}로 세분화해 반환
        """
        t0 = time.perf_counter()
        base = self._p_base_dir()
        resource = self._p_resource_dir()
        print(f"[sync] start base={base} resource={resource}")

        errors: list[str] = []
        metrics: Dict[str, Any] = {
            "foldersAdded": 0,  # master_content에 자동 추가된 새 폴더 수
            "blocksUpdated": 0,  # 푸시된 folder 블록 수
            "scanRc": None,  # run_sync_all의 반환 코드(참고용)
            "durationMs": None,  # 전체 소요 시간(ms)
        }

        # 1) 썸네일/리소스 스캔
        scan_rc = run_sync_all(
            resource_dir=self._p_resource_dir(),
            thumb_width=640,
        )
        scan_ok = scan_rc == 0
        metrics["scanRc"] = scan_rc
        print(f"[scan] ok={scan_ok} rc={scan_rc}")

        # DEBUG: 강제 스캔 실패 주입
        forced_scan_fail = False
        if os.getenv("ARTIDX_FAIL_SCAN") == "1":
            forced_scan_fail = True
            scan_ok = False
            metrics["scanRc"] = -1  # 가독성: 강제 실패 표시

        if not scan_ok:
            if forced_scan_fail:
                errors.append(
                    "DEBUG: ARTIDX_FAIL_SCAN=1로 인해 스캔을 실패로 강제 설정"
                )
            else:
                errors.append(f"썸네일/리소스 스캔 실패(rc={metrics['scanRc']})")

        # 2) 신규 폴더를 master_content에 자동 머지
        try:
            added = self._ensure_new_folders_in_master()
            if added > 0:
                metrics["foldersAdded"] = added
                print(f"[merge] added folders={added}")
        except Exception as e:
            # 실패하더라도 전체 Sync는 계속 진행
            errors.append(f"신규 폴더 자동 병합 실패: {e}")
            print(f"[merge] failed: {e}")

        # 3) 푸시: master_content → resource/*.html
        push_ok = True
        block_count = 0
        try:

            # DEBUG: 강제 푸시 실패 주입
            if os.getenv("ARTIDX_FAIL_PUSH") == "1":
                raise RuntimeError("DEBUG: ARTIDX_FAIL_PUSH=1 강제 푸시 예외")

            block_count = self._push_master_to_resource()
            metrics["blocksUpdated"] = block_count
        except Exception as e:
            push_ok = False
            errors.append(f"파일 반영(푸시) 실패: {e}")
            print(f"[push] failed: {e}")

        ok = scan_ok and push_ok
        metrics["durationMs"] = int((time.perf_counter() - t0) * 1000)

        print(
            f"[sync] done ok={ok} scanOk={scan_ok} pushOk={push_ok} "
            f"blocks={block_count} durationMs={metrics['durationMs']}"
        )
        return {
            "ok": ok,
            "scanOk": scan_ok,
            "pushOk": push_ok,
            "errors": errors,
            "metrics": metrics,
        }

    # ---- (옵션) 리빌드 → master_content 갱신 ----
    def rebuild_master(self) -> Dict[str, Any]:
        """
        master_content.html을 초기 상태로 재구성(사용자 편집 초기화 용도).
        - resource/<폴더>를 스캔해 '깨끗한 기본 카드'만 채워넣음(툴바/버튼 없음).
        """
        if BeautifulSoup is None:
            return {
                "ok": False,
                "error": "bs4가 없어 초기화 빌드를 수행할 수 없습니다.",
            }

        resource_dir = self._p_resource_dir()
        blocks: list[str] = []
        for p in sorted(resource_dir.iterdir(), key=lambda x: x.name):
            if not p.is_dir():
                continue
            if p.name.startswith(".") or p.name.lower() == "thumbs":
                continue
            blocks.append(_make_clean_block_html_for_master(p.name, resource_dir))

        new_html = "\n\n".join(blocks) + ("\n" if blocks else "")
        self._write(self._p_master_file(), new_html)
        return {"ok": True, "added": len(blocks)}

    # ---- 썸네일 1건 ----
    def refresh_thumb(self, folder_name: str, width: int = 640) -> Dict[str, Any]:
        folder = self._p_resource_dir() / folder_name
        thumbs_dir = folder / "thumbs"
        try:
            # 흔한 실패: thumbs가 '파일'인 경우 (폴더가 아니라 생성 불가)
            if thumbs_dir.exists() and thumbs_dir.is_file():
                return {
                    "ok": False,
                    "error": f"'thumbs' 경로가 파일입니다: {thumbs_dir}. 폴더로 복구해 주세요.",
                }

            ok = make_thumbnail_for_folder(folder, max_width=width)
            if ok:
                return {"ok": True}
            else:
                # 라이브러리 내부에서 False만 반환하는 경우를 위한 친절 메시지
                return {
                    "ok": False,
                    "error": "썸네일 생성 실패(소스 이미지 없음, 포맷 미지원, 또는 권한 문제)",
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _ensure_new_folders_in_master(self) -> int:
        """
        resource/<폴더> 중 master_content.html에 카드가 없는 폴더를
        '깨끗한 기본 카드'로 자동 추가한다.
        반환: 추가된 카드 개수
        """
        if BeautifulSoup is None:
            # 편집본 병합은 bs4 의존 — 없으면 스킵
            print("[merge] bs4 missing; skip adding new folders")
            return 0

        master_file = self._p_master_file()
        resource_dir = self._p_resource_dir()

        html = self._read(master_file)
        soup = BeautifulSoup(html or "", "html.parser")

        # 현재 master에 존재하는 폴더 이름 수집 (h2 텍스트 기준)
        existing: set[str] = set()
        for div in soup.find_all("div", class_="folder"):
            h2 = div.find("h2")
            if h2:
                name = (h2.get_text() or "").strip()
                if name:
                    existing.add(name)

        # 파일시스템의 폴더 수집
        fs_folders: list[str] = []
        for p in sorted(resource_dir.iterdir(), key=lambda x: x.name):
            if not p.is_dir():
                continue
            if p.name.startswith(".") or p.name.lower() == "thumbs":
                continue
            fs_folders.append(p.name)

        # master에 없는 폴더만 추가할 블록 생성
        new_blocks: list[str] = []
        for folder in fs_folders:
            if folder not in existing:
                new_blocks.append(
                    _make_clean_block_html_for_master(folder, resource_dir)
                )

        if not new_blocks:
            return 0

        # soup를 건드리지 않고 원문 텍스트 뒤에 문자열로 덧붙여, fragment 특성 유지
        new_html = (html or "").rstrip() + "\n\n" + "\n\n".join(new_blocks) + "\n"
        self._write(master_file, new_html)
        print(
            f"[merge] added={len(new_blocks)} folders: {', '.join([f for f in fs_folders if f not in existing])}"
        )
        return len(new_blocks)
