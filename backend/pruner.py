# backend/pruner.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Dict, Set, Optional
from pathlib import Path
import json
import re
import sys
import os

try:
    from .fsutil import atomic_write_text
except ImportError:
    from fsutil import atomic_write_text

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None

# ---- 유틸: 폴더 스캔 ----

DEFAULT_RESOURCE = "resource"
MASTER_CONTENT = "master_content.html"
ROOT_MASTER = "resource/master_index.html"

_HIDDEN_DIR = re.compile(r"^(\.|__pycache__|_tmp|_cache)$", re.I)


def list_fs_slugs(resource_root: str | Path) -> Set[str]:
    root = Path(resource_root)
    if not root.exists():
        return set()
    slugs: Set[str] = set()
    for p in root.iterdir():
        if not p.is_dir():
            continue
        if _HIDDEN_DIR.match(p.name):
            continue
        # child index 용 폴더 판단: thumbs, css 등 상위 공용 폴더는 제외
        # 기준: 폴더 아래에 'index.html' 또는 임의의 리소스가 존재하는 “자료 폴더”
        slugs.add(p.name)
    return slugs


# ---- HTML 파싱: master_content / master_index 에서 카드(폴더) 슬러그 추출 ----


def _extract_slugs_with_bs4(html_text: str) -> Set[str]:
    """
    가정:
    - 각 카드가 div.folder 등으로 묶여 있고 내부에 링크/이미지 경로가 'resource/<slug>/' 또는 '<slug>/' 형태로 등장
    - 혹은 우리가 쓰던 데이터 속성(data-folder) 또는 h2 텍스트가 폴더명과 동일한 경우가 있음
    가능한 힌트를 다 긁어 slug 후보를 모은 뒤 폴더명으로 합리적으로 필터링
    """
    soup = BeautifulSoup(html_text, "html.parser")
    candidates: Set[str] = set()

    # (1) data-folder 속성
    for el in soup.select("[data-folder]"):
        val = (el.get("data-folder") or "").strip()
        if val:
            candidates.add(val)

    # (2) 링크/이미지 src/href 내 경로 패턴
    for el in soup.select("a[href], img[src]"):
        url = el.get("href") or el.get("src") or ""
        m = re.search(
            r"(?:^|/)([A-Za-z0-9_\-가-힣\.\[\]\(\) ]+)(?:/index\.html|/thumbs/|/[^/]+\.(?:png|jpe?g|gif|mp4|pdf))",
            url,
        )
        if m:
            candidates.add(m.group(1))

    # (3) h2 텍스트가 폴더명인 경우(한글 포함)
    for h in soup.select("h2"):
        t = (h.get_text() or "").strip()
        # 슬러그로 안전치 않더라도 파일시스템에서 실제 존재하면 나중에 교차검증됨
        if t:
            candidates.add(t)

    # 가벼운 클린업: 경로분리자/공백
    cleaned = {
        c.strip().strip("/").replace("\\", "/").split("/")[-1]
        for c in candidates
        if c and not c.startswith("#")
    }
    return set([c for c in cleaned if c])


def _extract_slugs_fallback(html_text: str) -> Set[str]:
    # 최소 패턴: resource/<slug>/ 또는 href/src="./<slug>/index.html"
    found: Set[str] = set()
    for m in re.finditer(
        r"(?:^|/)([A-Za-z0-9_\-가-힣\.\[\]\(\) ]+)(?:/index\.html|/thumbs/|/\S+\.(?:png|jpe?g|gif|mp4|pdf))",
        html_text,
    ):
        found.add(m.group(1))
    return found


def extract_slugs_from_html(html_text: str) -> Set[str]:
    if BeautifulSoup is not None:
        try:
            return _extract_slugs_with_bs4(html_text)
        except Exception:
            pass
    return _extract_slugs_fallback(html_text)


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def list_master_content_slugs(path: str | Path = MASTER_CONTENT) -> Set[str]:
    p = Path(path)
    if not p.exists():
        # fallback: 루트의 master_content.html 자동 탐색
        alt = Path("master_content.html")
        if alt.exists():
            p = alt
        else:
            return set()
    return extract_slugs_from_html(read_text_safe(p))


def list_master_index_slugs(path: str | Path = ROOT_MASTER) -> Set[str]:
    p = Path(path)
    if not p.exists():
        # fallback: 루트의 master_content.html 자동 시도
        alt = Path("master_content.html")
        if alt.exists():
            p = alt
        else:
            return set()
    return extract_slugs_from_html(read_text_safe(p))


# ---- 썸네일 고아 검출(옵션) ----


def find_orphan_thumbs(resource_root: str | Path, fs_slugs: Set[str]) -> List[str]:
    """
    간단 규칙:
    - resource/<slug>/thumbs/* 가 실제 존재하고, slug 가 fs_slugs 에 없으면 orphan 후보
    - 리포트는 경로 문자열 리스트로 반환(적용 단계에서 삭제 결정)
    """
    root = Path(resource_root)
    orphans: List[str] = []
    for slug in fs_slugs:
        # 존재하는 폴더는 고아가 아님
        pass
    # 폴더 전체를 확인하여, fs_slugs 에 없는데 thumbs 가 남아 있는 경우 수집
    for p in root.iterdir():
        if not p.is_dir() or _HIDDEN_DIR.match(p.name):
            continue
        if p.name not in fs_slugs:
            thumbs = p / "thumbs"
            if thumbs.exists() and thumbs.is_dir():
                for f in thumbs.glob("*"):
                    orphans.append(str(f))
    return orphans


# ---- 드라이런 리포트 모델 ----


@dataclass
class PruneReport:
    folders_missing_in_fs: List[str]
    child_indexes_missing: List[str]
    orphans_in_master_index_only: List[str]
    thumbs_orphans: List[str]
    summary: Dict[str, int]

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_pretty(self) -> str:
        lines = []
        lines.append("== Prune Dry-run Report ==")
        lines.append(
            f"- missing_in_fs ({len(self.folders_missing_in_fs)}): {', '.join(self.folders_missing_in_fs) or '-'}"
        )
        lines.append(
            f"- child_indexes_missing ({len(self.child_indexes_missing)}): {', '.join(self.child_indexes_missing) or '-'}"
        )
        lines.append(
            f"- orphans_in_master_index_only ({len(self.orphans_in_master_index_only)}): {', '.join(self.orphans_in_master_index_only) or '-'}"
        )
        lines.append(
            f"- thumbs_orphans ({len(self.thumbs_orphans)}): {('…'+str(len(self.thumbs_orphans))+' files') if len(self.thumbs_orphans)>8 else ', '.join(self.thumbs_orphans) or '-'}"
        )
        lines.append("-- summary --")
        for k, v in self.summary.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)


# ---- 메인 계산기 ----


class DiffReporter:
    def __init__(
        self,
        resource_root: str | Path = DEFAULT_RESOURCE,
        master_content_path: str | Path = MASTER_CONTENT,
        master_index_path: str | Path = ROOT_MASTER,
        check_thumbs: bool = True,
    ) -> None:
        self.resource_root = Path(resource_root)
        self.master_content_path = Path(master_content_path)
        self.master_index_path = Path(master_index_path)
        self.check_thumbs = check_thumbs

    def make_report(self) -> PruneReport:
        fs_slugs = list_fs_slugs(self.resource_root)

        mc_slugs = list_master_content_slugs(self.master_content_path)
        mi_slugs = list_master_index_slugs(self.master_index_path)

        # 파일시스템(SSOT)에 없는데 캐시에만 남은 것 = 프룬 대상
        missing_in_fs_mc = sorted([s for s in mc_slugs if s not in fs_slugs])
        missing_in_fs_mi = sorted([s for s in mi_slugs if s not in fs_slugs])
        # 통합: 둘 중 하나라도 남아 있으면 프룬 후보
        folders_missing_in_fs = sorted(set(missing_in_fs_mc) | set(missing_in_fs_mi))

        # child index 없는 폴더
        child_indexes_missing: List[str] = []
        for slug in sorted(fs_slugs):
            child = self.resource_root / slug / "index.html"
            if not child.exists():
                child_indexes_missing.append(slug)

        # master_index 에만 있고 master_content 에는 없는 카드(동기화 불일치)
        orphans_in_master_index_only = sorted(
            [s for s in mi_slugs if s not in mc_slugs]
        )

        # thumbs 고아(옵션)
        thumbs_orphans: List[str] = []
        if self.check_thumbs:
            thumbs_orphans = find_orphan_thumbs(self.resource_root, fs_slugs)

        summary = {
            "fs_slugs": len(fs_slugs),
            "master_content_slugs": len(mc_slugs),
            "master_index_slugs": len(mi_slugs),
            "folders_missing_in_fs": len(folders_missing_in_fs),
            "child_indexes_missing": len(child_indexes_missing),
            "orphans_in_master_index_only": len(orphans_in_master_index_only),
            "thumbs_orphans_files": len(thumbs_orphans),
        }

        return PruneReport(
            folders_missing_in_fs=folders_missing_in_fs,
            child_indexes_missing=child_indexes_missing,
            orphans_in_master_index_only=orphans_in_master_index_only,
            thumbs_orphans=thumbs_orphans,
            summary=summary,
        )


# ---- 실제 적용기 -------------------------------------------------------


class PruneApplier:
    """
    Diff 결과를 실제 파일에 반영한다.
    - master_content.html : folders_missing_in_fs 제거
    - child indexes       : child_indexes_missing 재생성
    - master_index.html   : master_content 기준 재렌더
    - thumbs_orphans      : 옵션 시 실제 파일 삭제
    """

    def __init__(
        self,
        resource_root: str | Path = DEFAULT_RESOURCE,
        master_content_path: str | Path = MASTER_CONTENT,
        master_index_path: str | Path = ROOT_MASTER,
        delete_thumbs: bool = False,
    ) -> None:
        self.resource_root = Path(resource_root)
        self.master_content_path = Path(master_content_path)
        self.master_index_path = Path(master_index_path)
        self.delete_thumbs = delete_thumbs

        if not self.master_content_path.exists():
            alt = Path("master_content.html")
            if alt.exists():
                self.master_content_path = alt

    def _imports(self):
        try:
            # 패키지 실행(backend.*)일 때
            from .htmlops import (
                extract_inner_html_only,
                adjust_paths_for_folder,
                strip_back_to_master,
            )
            from .builder import render_master_index, render_child_index
            from .thumbs import _safe_name as _thumb_safe_name
        except Exception:
            # 스크립트 실행(top-level)일 때
            from htmlops import (
                extract_inner_html_only,
                adjust_paths_for_folder,
                strip_back_to_master,
            )
            from builder import render_master_index, render_child_index
            from thumbs import _safe_name as _thumb_safe_name

        return (
            extract_inner_html_only,
            adjust_paths_for_folder,
            strip_back_to_master,
            render_master_index,
            render_child_index,
            _thumb_safe_name,
        )

    def _load_master_soup(self) -> "BeautifulSoup":
        if BeautifulSoup is None:
            raise RuntimeError("P1-4 requires bs4. `pip install beautifulsoup4`")
        html = read_text_safe(self.master_content_path)
        return BeautifulSoup(html or "", "html.parser")

    def _write_atomic(self, path: Path, s: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(str(path), s, encoding="utf-8", newline="\n")

    def apply(self, report: Optional[PruneReport] = None) -> Dict[str, int]:
        # 1) diff 준비
        if report is None:
            report = DiffReporter(
                resource_root=self.resource_root,
                master_content_path=self.master_content_path,
                master_index_path=self.master_index_path,
            ).make_report()

        (
            extract_inner_html_only,
            adjust_paths_for_folder,
            strip_back_to_master,
            render_master_index,
            render_child_index,
            _thumb_safe_name,
        ) = self._imports()

        soup = self._load_master_soup()
        removed = 0

        # 2) master_content: folders_missing_in_fs 제거
        targets = set(report.folders_missing_in_fs)
        if targets:
            for div in list(soup.select("div.folder")):
                title_el = div.select_one(".folder-head h2") or div.find("h2")
                title = (title_el.get_text(strip=True) if title_el else "").strip()
                data_folder = (div.get("data-folder") or "").strip()
                if title in targets or data_folder in targets:
                    div.decompose()
                    removed += 1

        # 3) child index 재생성
        child_built = 0
        if report.child_indexes_missing:
            for slug in report.child_indexes_missing:
                div = None
                for cand in soup.select("div.folder"):
                    h = cand.select_one(".folder-head h2") or cand.find("h2")
                    tt = (h.get_text(strip=True) if h else "").strip()
                    if tt == slug or (cand.get("data-folder") or "").strip() == slug:
                        div = cand
                        break
                if not div:
                    continue
                inner_only = extract_inner_html_only(str(div))
                inner_for_folder = adjust_paths_for_folder(
                    inner_only, slug, for_resource_master=False
                )
                safe = _thumb_safe_name(slug)
                thumb_rel = None
                if (self.resource_root / slug / "thumbs" / f"{safe}.jpg").exists():
                    thumb_rel = f"thumbs/{safe}.jpg"
                child_html = render_child_index(
                    title=slug, html_body=inner_for_folder, thumb_src=thumb_rel
                )
                self._write_atomic(self.resource_root / slug / "index.html", child_html)
                child_built += 1

        # 4) master_index 재렌더 (master_content → 목록 생성)
        folders_for_master: List[Dict[str, Optional[str]]] = []
        for div in soup.select("div.folder"):
            h2 = div.select_one(".folder-head h2") or div.find("h2")
            title = (h2.get_text(strip=True) if h2 else "").strip()
            if not title:
                continue
            inner_only = extract_inner_html_only(str(div))
            inner_for_master = adjust_paths_for_folder(
                inner_only, title, for_resource_master=True
            )
            inner_for_master = strip_back_to_master(inner_for_master)
            safe = _thumb_safe_name(title)
            thumb_rel_for_master = None
            if (self.resource_root / title / "thumbs" / f"{safe}.jpg").exists():
                thumb_rel_for_master = f"{title}/thumbs/{safe}.jpg"
            folders_for_master.append(
                {
                    "title": title,
                    "html": inner_for_master,
                    "thumb": thumb_rel_for_master,
                }
            )

        # 4-1) master_content 저장
        self._write_atomic(self.master_content_path, str(soup))
        # 4-2) master_index 저장
        master_html = render_master_index(folders_for_master)
        self._write_atomic(self.master_index_path, master_html)

        # 5) 고아 썸네일 삭제(옵션)
        thumbs_deleted = 0
        if self.delete_thumbs and report.thumbs_orphans:
            for p in report.thumbs_orphans:
                try:
                    Path(p).unlink(missing_ok=True)
                    thumbs_deleted += 1
                except Exception:
                    pass

        return {
            "removed_from_master": removed,
            "child_built": child_built,
            "thumbs_deleted": thumbs_deleted,
        }


# ---- CLI ----


def _main(argv: List[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="ArtIndex Diff & Prune Dry-run Reporter")
    ap.add_argument(
        "--resource", default=DEFAULT_RESOURCE, help="resource root (default: resource)"
    )
    ap.add_argument(
        "--no-thumbs", action="store_true", help="skip scanning orphan thumbnails"
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--print", action="store_true", help="print human-readable report")
    g.add_argument("--json", action="store_true", help="print JSON report")
    ap.add_argument("--apply", action="store_true", help="apply prune changes (P1-4)")
    ap.add_argument(
        "--delete-thumbs", action="store_true", help="also delete orphan thumbnails"
    )
    args = ap.parse_args(argv)

    reporter = DiffReporter(
        resource_root=args.resource, check_thumbs=not args.no_thumbs
    )
    report = reporter.make_report()

    if args.apply:
        applier = PruneApplier(
            resource_root=args.resource,
            master_content_path=MASTER_CONTENT,
            master_index_path=ROOT_MASTER,
            delete_thumbs=args.delete_thumbs,
        )
        result = applier.apply(report)
        print("== Prune Applied ==")
        print(f"- removed_from_master: {result['removed_from_master']}")
        print(f"- child_built       : {result['child_built']}")
        print(f"- thumbs_deleted    : {result['thumbs_deleted']}")
    else:
        if args.json:
            print(report.to_json())
        else:
            # default to pretty if --print or nothing provided
            print(report.to_pretty())


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
