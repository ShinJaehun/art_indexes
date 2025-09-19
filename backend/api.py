from pathlib import Path
from typing import Dict, Any, Union
import re

from thumbs import make_thumbnail_for_folder
from builder import run_sync_all, rebuild_master_from_sources

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # bs4 없으면 일부 기능 제한

# -------- 상수 --------
ROOT_MASTER = "master_index.html"
FOLDER_INDEX = "index.html"

# ANNO: 정규식 본문 추출. 편집 후 body 속성/스크립트 배치가 달라지면 실패 가능 → 가능하면 bs4 권장.
_BODY_RE = re.compile(r"<body[^>]*>([\s\S]*?)</body>", re.IGNORECASE)
# ANNO: resource 접두어를 붙이지 않을 예외 접두사.
# HAZARD: mailto:, data:, tel: 등은 여기에 포함되어 있지 않다 → 예외 케이스 추가 여지.
_SKIP_PREFIX = re.compile(r"^(https?://|/|\.\./|#|resource/)", re.IGNORECASE)


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


def _inner_without_h2(div_html: str) -> str:
    """<div class="folder"> 블록에서 <h2>를 제거하고 내부만 반환한다."""
    if BeautifulSoup is None:
        # 정규식 폴백(간이)
        html = re.sub(r"<h2[^>]*>.*?</h2>", "", div_html, flags=re.I | re.S)
        m = re.search(
            r'<div class="folder"[^>]*>(.*)</div>\s*$', html, flags=re.I | re.S
        )
        return m.group(1).strip() if m else html
    soup = BeautifulSoup(div_html, "html.parser")
    root = soup.find("div", class_="folder") or soup
    h2 = root.find("h2")
    if h2:
        h2.decompose()
    return "".join(str(x) for x in root.contents).strip()


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


def _wrap_folder_index(title: str, inner: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{title}</title>
  <link rel="stylesheet" href="../master.css" />
</head>
<body>
  <div class="folder">
    <h2>{title}</h2>
    {inner}
    <a href="../{ROOT_MASTER}">⬅ 전체 목록으로</a>
  </div>
</body>
</html>"""


def _build_master_from_blocks(blocks_html: list[str]) -> str:
    head = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>미술 수업 자료 Index</title>
  <link rel="stylesheet" href="../master.css" />
  <script defer src="../master.js"></script>
</head>
<body>
  <h1>미술 수업 자료 Index</h1>
"""
    tail = "\n</body>\n</html>"
    return head + "\n".join(blocks_html) + tail


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
            return {"html": self._read(master_file)}

        if resource_master.exists():
            inner = _extract_body_inner(self._read(resource_master))
            inner = _prefix_resource_paths_for_root(inner)
            self._write(master_file, inner)
            return {"html": inner}

        return {"html": ""}

    def save_master(self, html: str) -> Dict[str, Any]:
        """편집 저장: master_content.html만 갱신(사용자 작성 HTML 그대로 저장)"""
        self._write(self._p_master_file(), html)
        return {"ok": True}

    # ---- 푸시: master_content → resource/*.html ----
    def _push_master_to_resource(self) -> None:
        """
        master_content.html을 소스로 삼아
        - resource/master_index.html
        - resource/<폴더>/index.html
        을 직접 생성/덮어쓴다.
        """
        html = self._read(self._p_master_file())
        if not html:
            return
        if BeautifulSoup is None:
            # bs4 없으면 안전망: 중앙 master만 덮어씀(폴더별 반영은 skip)
            inner = _extract_body_inner(html)
            self._write(self._p_resource_master(), _build_master_from_blocks([inner]))
            return

        soup = BeautifulSoup(html, "html.parser")
        blocks_for_master: list[str] = []

        for div in soup.find_all("div", class_="folder"):
            h2 = div.find("h2")
            if not h2:
                continue
            folder = h2.get_text(strip=True)

            # 배포용 정화본 생성(원본 div는 건드리지 않음)
            cleaned_div_html = _clean_for_publish(str(div))

            # 1) 마스터용 블록
            div_for_master = _strip_back_to_master(cleaned_div_html)
            # ★ master_index 관점으로 경로 치환
            div_for_master = _adjust_paths_for_folder(
                div_for_master, folder, for_resource_master=True
            )
            blocks_for_master.append(div_for_master)

            # 2) 폴더 index.html용 (옵션 False)
            # inner_for_folder = _adjust_paths_for_folder(
            #     cleaned_div_html, folder, for_resource_master=False
            # )
            # folder_html = _wrap_folder_index(folder, inner_for_folder)
            # self._write(self._p_resource_dir() / folder / FOLDER_INDEX, folder_html)

            # --- 폴더 index.html용: h2 제거한 '내부만' 사용 ---
            inner_only = _inner_without_h2(cleaned_div_html)
            inner_for_folder = _adjust_paths_for_folder(
                inner_only, folder, for_resource_master=False
            )
            folder_html = _wrap_folder_index(folder, inner_for_folder)
            self._write(self._p_resource_dir() / folder / FOLDER_INDEX, folder_html)

        # 3) resource/master_index.html 갱신
        master_html = _build_master_from_blocks(blocks_for_master)
        self._write(self._p_resource_master(), master_html)

    # ---- 동기화 ----
    def sync(self) -> Dict[str, Any]:
        """
        1) 리소스 스캔/썸네일 등 기계 작업 실행
        2) 사용자 편집본(master_content.html)을 기준으로 resource 쪽 파일들을 덮어씀(푸시)
        3) (선택) root 표시용 파일(master_content.html)은 그대로 유지
        """
        # 1) 썸네일 스캔
        code = run_sync_all(
            resource_dir=self._p_resource_dir(),
            thumb_width=640,
        )
        scan_ok = code == 0

        # 2) 푸시
        push_ok = True
        try:
            self._push_master_to_resource()
        except Exception as e:
            push_ok = False
            # 실패 원인을 로그로 남겨 두자 (콘솔/pywebview 콘솔에서 확인)
            print(f"[sync] push failed: {e}")

        return {"ok": (scan_ok and push_ok), "scanOk": scan_ok, "pushOk": push_ok}

    # ---- (옵션) 리빌드 → master_content 갱신 ----
    def rebuild_master(self) -> Dict[str, Any]:
        """
        스크립트로부터 순수 빌드 결과를 받아 master_content.html을 새로 설정.
        (사용자 편집 초기화 목적일 때만 사용 권장)
        HAZARD(yesterday): builder.rebuild_master_from_sources()는 .folder-actions 버튼이 포함된 블록을 반환한다.
        → _prefix_resource_paths_for_root()를 거쳐도 버튼 자체는 남는다.
        """
        html = rebuild_master_from_sources(resource_dir=self._p_resource_dir())
        inner = _extract_body_inner(html)
        inner = _prefix_resource_paths_for_root(inner)
        self._write(self._p_master_file(), inner)
        return {"ok": True}

    # ---- 썸네일 1건 ----
    def refresh_thumb(self, folder_name: str, width: int = 640) -> Dict[str, Any]:
        folder = self._p_resource_dir() / folder_name
        ok = make_thumbnail_for_folder(folder, max_width=width)
        return {"ok": ok}
