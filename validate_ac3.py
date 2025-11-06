#!/usr/bin/env python3
# validate_ac3.py
import sys
import re
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("BeautifulSoup4가 필요합니다. 설치: pip install beautifulsoup4")
    sys.exit(2)

# --- 설정 ---
ALLOWED_TAGS = {
    "p",
    "br",
    "img",
    "a",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "strong",
    "em",
    "span",
    "div",
    "figure",
    "figcaption",
}
# 허용 속성(태그별 최소화). on* 이벤트 속성은 무조건 금지.
ALLOWED_ATTRS = {
    "img": {"src", "alt", "title", "width", "height", "class", "id", "style"},
    "a": {"href", "title", "target", "rel", "class", "id", "style"},
    # 공통 허용(명시되지 않은 태그는 아래 COMMON으로 처리)
}
COMMON_ATTRS = {"class", "id", "style"}

FORBIDDEN_TAGS = {"button", "form", "input", "select", "textarea"}

# on* 이벤트 속성, javascript: 스킴, contenteditable
EVENT_ATTR_RE = re.compile(r"^on[a-z]+$", re.IGNORECASE)
JS_SCHEME_RE = re.compile(r"^\s*javascript\s*:", re.IGNORECASE)


def is_js_scheme(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return bool(JS_SCHEME_RE.match(value.strip()))


def scan_inner_editable(file_path: Path):
    html = file_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    results = {
        "file": str(file_path),
        "forbidden_tags": 0,
        "event_attrs": 0,
        "js_scheme_links": 0,
        "contenteditable": 0,
        "unknown_tags": set(),
        "unknown_tags_count": 0,
        "details": [],
    }

    targets = soup.select(".inner.editable")
    if not targets:
        # 없으면 스킵(파일 구조에 따라 다를 수 있음)
        return results

    for root in targets:
        # 1) 금지 태그
        for t in root.find_all(True):
            tag = t.name.lower()

            # contenteditable 잔재
            if t.has_attr("contenteditable"):
                results["contenteditable"] += 1
                results["details"].append(("contenteditable", str(t)[:120]))

            # 금지 태그
            if tag in FORBIDDEN_TAGS:
                results["forbidden_tags"] += 1
                results["details"].append(("forbidden_tag", f"<{tag} ...>"))

            # on* 이벤트 속성
            for attr in list(t.attrs.keys()):
                if EVENT_ATTR_RE.match(attr):
                    results["event_attrs"] += 1
                    results["details"].append(("event_attr", f"<{tag} {attr}=...>"))

            # javascript: 스킴 (href/src)
            for attr in ("href", "src"):
                if t.has_attr(attr) and is_js_scheme(t.get(attr, "")):
                    results["js_scheme_links"] += 1
                    results["details"].append(
                        ("js_scheme", f"<{tag} {attr}='javascript:...'>")
                    )

            # 2) 허용 태그 외 탐지 (옵션: 경고/차단)
            if tag not in ALLOWED_TAGS and tag not in FORBIDDEN_TAGS:
                results["unknown_tags"].add(tag)

            # 3) 허용 속성 점검(선택적 경고)
            #    on*과 javascript는 위에서 이미 잡으므로, 여기선 '허용 목록 밖 속성'을 참고용 경고로만 집계
            allowed = ALLOWED_ATTRS.get(tag, COMMON_ATTRS)
            for attr in list(t.attrs.keys()):
                if attr in ("href", "src"):  # 링크 스킴은 위에서 별도 검사
                    continue
                if EVENT_ATTR_RE.match(attr):
                    continue
                if attr not in allowed:
                    # 필요 시 세부 정책 강화 가능
                    pass

    results["unknown_tags_count"] = len(results["unknown_tags"])
    return results


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="AC3 검증기: .inner.editable 내부 금지 요소/허용 태그 외 탐지"
    )
    ap.add_argument(
        "--root", required=True, help="resource 루트 디렉토리 (예: resource)"
    )
    ap.add_argument(
        "--glob", default="**/index.html", help="검색 패턴 (기본: **/index.html)"
    )
    args = ap.parse_args()

    root = Path(args.root)
    files = list(root.glob(args.glob))

    if not files:
        print("검사 대상 index.html 파일이 없습니다.")
        sys.exit(1)

    total = {
        "forbidden_tags": 0,
        "event_attrs": 0,
        "js_scheme_links": 0,
        "contenteditable": 0,
        "unknown_files": 0,
    }
    any_fail = False

    print("=== AC3 검사 시작 ===")
    for f in files:
        r = scan_inner_editable(f)
        if r is None:
            continue

        # PASS/FAIL 판정
        fail = (
            r["forbidden_tags"] > 0
            or r["event_attrs"] > 0
            or r["js_scheme_links"] > 0
            or r["contenteditable"] > 0
        )
        if fail:
            any_fail = True

        # 합계
        total["forbidden_tags"] += r["forbidden_tags"]
        total["event_attrs"] += r["event_attrs"]
        total["js_scheme_links"] += r["js_scheme_links"]
        total["contenteditable"] += r["contenteditable"]
        if r["unknown_tags_count"] > 0:
            total["unknown_files"] += 1

        # 파일별 요약 출력
        status = "FAIL" if fail else "PASS"
        print(f"\n[{status}] {r['file']}")
        print(f"  - forbidden_tags:  {r['forbidden_tags']}")
        print(f"  - event_attrs:     {r['event_attrs']}")
        print(f"  - js_scheme_links: {r['js_scheme_links']}")
        print(f"  - contenteditable: {r['contenteditable']}")
        if r["unknown_tags_count"] > 0:
            print(
                f"  - unknown_tags({r['unknown_tags_count']}): {', '.join(sorted(r['unknown_tags']))}"
            )
        if fail and r["details"]:
            print("  * details (first few):")
            for kind, snippet in r["details"][:5]:
                print(f"    - {kind}: {snippet}")

    print("\n=== AC3 전체 합계 ===")
    for k, v in total.items():
        print(f"  {k}: {v}")

    if any_fail:
        print(
            "\n결론: AC3 **FAIL** (금지 요소가 남아있습니다). Sanitizer/저장 로직을 점검하세요."
        )
        sys.exit(3)
    else:
        print("\n결론: AC3 **PASS** ✅")
        sys.exit(0)


if __name__ == "__main__":
    main()
