#!/usr/bin/env python3
# validate_ac4.py
import sys, re
from pathlib import Path

try:
    from bs4 import BeautifulSoup, Comment
except ImportError:
    print("BeautifulSoup4가 필요합니다. 설치: pip install beautifulsoup4")
    sys.exit(2)

MASTER = "resource/master_index.html"


def _norm_path_for_compare(folder: str, s: str) -> str:
    if not s:
        return s
    s = s.strip()
    # master 쪽: "관절 인형 만들기/..." → 접두어 제거
    if s.lower().startswith(folder.lower() + "/"):
        s = s[len(folder) + 1 :]
    # 양쪽 공통: ./, ../, resource/ 접두어 등 가벼운 정리 (필요시 확장)
    s = s.lstrip("./")
    if s.lower().startswith("resource/"):
        s = s[9:]
    return s


def _normalize_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "")
    return s.strip()


def _has_escaped_tags(html: str) -> bool:
    return ("&lt;" in html) or ("&gt;" in html)


def _extract_block_map_from_master(master_html: str):
    soup = BeautifulSoup(master_html, "html.parser")
    blocks = {}
    for div in soup.select("div.folder"):
        title_el = div.select_one(".folder-head h2") or div.find("h2")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        inner = div.select_one(".inner") or div
        # 주석 제거
        for n in list(inner.descendants):
            if isinstance(n, Comment):
                n.extract()
        inner_html = inner.decode_contents().strip()
        blocks[title] = {
            "html": inner_html,
            "text": _normalize_text(inner.get_text(" ", strip=True)),
            "links": [
                _norm_path_for_compare(title, a.get("href", "").strip())
                for a in inner.find_all("a", href=True)
            ],
            "imgs": [
                _norm_path_for_compare(title, i.get("src", "").strip())
                for i in inner.find_all("img", src=True)
            ],
        }
    return blocks


def _extract_from_child(child_html: str, folder: str):
    soup = BeautifulSoup(child_html, "html.parser")
    # AC2: child에 툴바 없어야 함
    has_toolbar = bool(soup.select(".folder-actions"))
    # back-to-master 링크 존재
    back_link = bool(soup.select_one('a.back-to-master[href="../master_index.html"]'))

    inner = soup.select_one(".inner") or soup
    for n in list(inner.descendants):
        if isinstance(n, Comment):
            n.extract()
    inner_html = inner.decode_contents().strip()
    return {
        "html": inner_html,
        "text": _normalize_text(inner.get_text(" ", strip=True)),
        "links": [
            _norm_path_for_compare(folder, a.get("href", "").strip())
            for a in inner.find_all("a", href=True)
        ],
        "imgs": [
            _norm_path_for_compare(folder, i.get("src", "").strip())
            for i in inner.find_all("img", src=True)
        ],
        "has_toolbar": has_toolbar,
        "has_back": back_link,
    }


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="AC4 검증: master↔child 동등성 + 이스케이프/툴바/뒤로가기 링크 검사"
    )
    ap.add_argument("--root", default="resource", help="resource 루트 (기본: resource)")
    ap.add_argument(
        "--master",
        default=MASTER,
        help="마스터 파일 경로 (기본: resource/master_index.html)",
    )
    args = ap.parse_args()

    root = Path(args.root)
    master_path = Path(args.master)
    if not master_path.exists():
        print(f"마스터 파일이 없습니다: {master_path}")
        sys.exit(1)

    master_html = master_path.read_text(encoding="utf-8", errors="ignore")
    master_blocks = _extract_block_map_from_master(master_html)

    total = {
        "folders": 0,
        "ok": 0,
        "fail_render": 0,
        "fail_toolbar": 0,
        "fail_back": 0,
        "fail_escaped_master": 0,
        "fail_escaped_child": 0,
    }

    print("=== AC4 검사 시작 ===")

    for folder_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
        folder = folder_dir.name
        idx = folder_dir / "index.html"
        if not idx.exists():
            continue

        total["folders"] += 1
        child = _extract_from_child(
            idx.read_text(encoding="utf-8", errors="ignore"), folder
        )
        mb = master_blocks.get(folder)

        status = "PASS"
        reasons = []

        # 0) 이스케이프 여부
        if mb:
            if _has_escaped_tags(mb["html"]):
                total["fail_escaped_master"] += 1
                status = "FAIL"
                reasons.append("master: &lt;…&gt; 발견(렌더 실패)")
        if _has_escaped_tags(child["html"]):
            total["fail_escaped_child"] += 1
            status = "FAIL"
            reasons.append("child: &lt;…&gt; 발견(렌더 실패)")

        # 1) 동등성 비교(텍스트/링크/이미지 수집 비교)
        if mb:
            if (
                mb["text"] != child["text"]
                or mb["links"] != child["links"]
                or mb["imgs"] != child["imgs"]
            ):
                total["fail_render"] += 1
                status = "FAIL"
                reasons.append("master↔child 본문 불일치(텍스트/링크/이미지)")
        else:
            # 마스터에 블록이 없는데 child만 있는 경우
            total["fail_render"] += 1
            status = "FAIL"
            reasons.append("master에 해당 폴더 블록 없음")

        # 2) AC2 수반 체크
        if child["has_toolbar"]:
            total["fail_toolbar"] += 1
            status = "FAIL"
            reasons.append("child에 툴바 존재(금지)")
        if not child["has_back"]:
            total["fail_back"] += 1
            status = "FAIL"
            reasons.append('child에 "⬅ 전체 목록으로" 링크 없음')

        print(f"\n[{status}] {folder}")
        if reasons:
            for r in reasons[:6]:
                print("  -", r)

    print("\n=== 요약 ===")
    print(f"대상 폴더: {total['folders']}")
    ok_count = total["folders"] - (
        total["fail_render"]
        + total["fail_toolbar"]
        + total["fail_back"]
        + total["fail_escaped_master"]
        + total["fail_escaped_child"]
    )
    total["ok"] = ok_count
    print(f"PASS     : {ok_count}")
    print(f"불일치   : {total['fail_render']}")
    print(f"툴바위반 : {total['fail_toolbar']}")
    print(f"뒤로링크 : {total['fail_back']}")
    print(f"이스케이프(master): {total['fail_escaped_master']}")
    print(f"이스케이프(child) : {total['fail_escaped_child']}")

    if ok_count == total["folders"]:
        print("\n결론: AC4 **PASS** ✅")
        sys.exit(0)
    else:
        print("\n결론: AC4 **FAIL** ❌ — 위 항목 참고해 수정 필요")
        sys.exit(3)


if __name__ == "__main__":
    main()
