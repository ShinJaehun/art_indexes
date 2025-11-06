import re
import html as _py_html
from typing import Tuple, Dict, Union
from bs4 import BeautifulSoup, NavigableString

DangerTags = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "link",
    "form",
    "input",
    "button",
    "video",
    "audio",
}

AllowedTags = {
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
    "figure",
    "figcaption",
}

AllowedAttrs = {
    "img": {"src", "alt", "title", "width", "height"},
    "a": {"href", "title", "target", "rel"},
}
# 허용 URL 스킴(상대경로는 따로 허용)
ALLOWED_SCHEMES = ("http://", "https://", "mailto:", "tel:", "/", "./", "../")


def _safe_unescape_tag_texts_in_inner(soup: BeautifulSoup):
    """.inner 내부의 텍스트 노드 중 &lt;...&gt; 패턴을 허용 태그만 실제 HTML로 복원"""
    inners = soup.select(".inner")
    for inner in inners:
        # 텍스트 노드만 순회
        for node in list(inner.descendants):
            if isinstance(node, NavigableString):
                s = str(node)
                if ("&lt;" in s and "&gt;" in s) or ("<" in s and ">" in s):
                    un = _py_html.unescape(s)
                    # 파싱해서 허용태그만 보존
                    frag = BeautifulSoup(un, "html.parser")
                    # 위험/이벤트 속성 제거는 기존 sanitize에서 다시 수행됨
                    # 여기선 단순히 노드를 교체
                    parent = node.parent
                    if parent is None:
                        continue
                    # replace NavigableString with parsed fragment children
                    for child in list(frag.contents):
                        parent.insert(parent.contents.index(node), child)
                    node.extract()


def _is_allowed_url(u: str) -> bool:
    if not u:
        return True
    low = u.strip().lower()
    if low.startswith("javascript:"):
        return False
    if low.startswith("data:"):
        # 내부 프로젝트 특성상 data:URI는 배포물에서 금지(파일만 허용)
        return False
    if low.startswith(ALLOWED_SCHEMES) or not re.match(r"^[a-z]+:", low):
        return True
    return False


def _normalize_lists(soup: BeautifulSoup):
    """
    - 부모가 UL/OL이 아닌 LI들을 가장 가까운 '이전 형제의 UL/OL'로 이동.
    - 없다면 새 UL을 만들어 감싼다.
    - 빈 UL/OL 제거.
    """
    # 1) 고아 LI 모으기
    orphans = []
    for li in soup.find_all("li"):
        if li.parent and li.parent.name in ("ul", "ol"):
            continue
        orphans.append(li)

    for li in orphans:
        # 이전 형제들 중 가장 가까운 UL/OL 찾기 (DIV 래핑을 건너뛰어 탐색)
        prev = li.previous_sibling
        target = None
        while prev:
            if getattr(prev, "name", None) in ("ul", "ol"):
                target = prev
                break
            # div 같은 래퍼 안쪽에 ul/ol이 있는 경우
            if getattr(prev, "name", None) and prev.find(["ul", "ol"]):
                inner_list = prev.find(["ul", "ol"])
                if inner_list:
                    target = inner_list
                    break
            prev = prev.previous_sibling

        if not target:
            # 앞에 없으면 li 앞에 새 UL 생성해서 감싼다
            target = soup.new_tag("ul")
            li.insert_before(target)

        target.append(li)

    # 2) 빈 UL/OL 정리
    for t in soup.find_all(["ul", "ol"]):
        if not t.find("li"):
            t.decompose()


def sanitize_for_publish(
    div_html: str, *, return_metrics: bool = False
) -> Union[str, Tuple[str, Dict[str, int]]]:
    """
    편집용 div.card → 배포용 정화
    - 제거: .card-actions, .btn*, DangerTags
    - 속성: on*, data-*, style, contenteditable, draggable 제거
    - 태그: 화이트리스트 외는 unwrap
    - URL: javascript:, data: 차단(속성 제거)
    - 메트릭 반환 옵션
    """
    metrics = {
        "removed_nodes": 0,
        "removed_attrs": 0,
        "unwrapped_tags": 0,
        "blocked_urls": 0,
    }

    # --- BeautifulSoup 경로 ---
    soup = BeautifulSoup(div_html, "html.parser")

    # .inner 안에서 텍스트에 들어있는 &lt;...&gt; 를 허용 태그로 복원
    # _safe_unescape_tag_texts_in_inner(soup) # <- 저장 시점에서만 복원되므로 publish 단계에서는 복원 시도 안함

    # 1) 컨트롤 UI 제거
    # - 카드 액션 바 전체 제거
    for n in soup.select(".card-actions"):
        n.decompose()
        metrics["removed_nodes"] += 1

    # - 편집용 버튼만 제거 (a.btn 등 링크는 보존)
    for n in soup.find_all("button"):
        n.decompose()
        metrics["removed_nodes"] += 1

    # 2) 위험 태그 제거
    for t in list(DangerTags):
        for node in soup.find_all(t):
            node.decompose()
            metrics["removed_nodes"] += 1

    # 3) 태그/속성 정리
    for tag in list(soup.find_all(True)):
        # 속성 정리
        for attr in list(tag.attrs.keys()):
            low = attr.lower()
            if (
                low.startswith("on")
                or low.startswith("data-")
                or low in {"contenteditable", "draggable", "style"}
            ):
                tag.attrs.pop(attr, None)
                metrics["removed_attrs"] += 1

        # URL 안전화
        if tag.name == "a" and tag.has_attr("href"):
            href = str(tag["href"]).strip()
            if not _is_allowed_url(href):
                tag.attrs.pop("href", None)
                metrics["blocked_urls"] += 1
        if tag.name == "img" and tag.has_attr("src"):
            src = str(tag["src"]).strip()
            if not _is_allowed_url(src):
                tag.attrs.pop("src", None)
                metrics["blocked_urls"] += 1

        # 태그 화이트리스트
        if tag.name not in AllowedTags:
            tag.unwrap()
            metrics["unwrapped_tags"] += 1
            continue

        # 허용 속성만 유지(+ class 허용)
        if tag.name in AllowedAttrs:
            keep = AllowedAttrs[tag.name]
            for a in list(tag.attrs.keys()):
                if a not in keep and a != "class":
                    tag.attrs.pop(a, None)
                    metrics["removed_attrs"] += 1

        # a 태그 보안 속성 보정
        if tag.name == "a":
            # target/_blank면 rel 강제
            tgt = (tag.get("target") or "").strip().lower()
            if tgt == "_blank":
                # 기존 rel을 타입 안전하게 집합으로 변환
                rel_val = tag.get("rel")
                if isinstance(rel_val, (list, tuple)):
                    existing = set(
                        x for x in rel_val if isinstance(x, str) and x.strip()
                    )
                elif isinstance(rel_val, str):
                    existing = set(rel_val.split())
                else:
                    existing = set()

                needed = {"noopener", "noreferrer"}
                if not needed.issubset(existing):
                    tag["rel"] = " ".join(sorted(existing | needed))

    out = str(soup)
    return (out, metrics) if return_metrics else out
