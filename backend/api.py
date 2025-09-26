from pathlib import Path
from typing import Dict, Any, Union
import re
import time
import os  # TODO: fail 테스트 끝나면 제거

from thumbs import make_thumbnail_for_folder
from builder import run_sync_all, render_master_index, render_child_index

# 분리된 모듈들
from sanitizer import sanitize_for_publish
from htmlops import (
    extract_body_inner,
    prefix_resource_paths_for_root,
    strip_back_to_master,
    adjust_paths_for_folder,
    extract_inner_html_only,
)
from thumbops import (
    ensure_thumb_in_head,
    inject_thumbs_for_preview,
    persist_thumbs_in_master,
    make_clean_block_html_for_master,
)

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

# -------- 상수 --------
ROOT_MASTER = "master_index.html"
FOLDER_INDEX = "index.html"

# AC2: sanitizer 로그 토글
SAN_VERBOSE = os.getenv("ARTIDX_SAN_VERBOSE") == "1"


# -------- 메인 API --------
class MasterApi:
    """
    - 화면은 항상 master_content.html을 로드/저장
    - Sync:
        1) run_sync_all()로 리소스 스캔/썸네일(기계 작업)
        2) master_content.html을 **정본**으로 resource/master_index.html과 각 폴더 index.html **덮어쓰기(푸시)**
    """

    def __init__(self, base_dir: Union[str, Path]):
        base_dir = Path(base_dir).resolve()
        # 외부 노출은 문자열만 (pywebview 안전)
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
            html_for_view = inject_thumbs_for_preview(raw, self._p_resource_dir())
            return {"html": html_for_view}

        if resource_master.exists():
            inner = extract_body_inner(self._read(resource_master))
            inner = prefix_resource_paths_for_root(inner)
            self._write(master_file, inner)
            html_for_view = inject_thumbs_for_preview(inner, self._p_resource_dir())
            return {"html": html_for_view}

        return {"html": ""}

    def save_master(self, html: str) -> Dict[str, Any]:
        """편집 저장: master_content.html만 갱신(사용자 작성 HTML 그대로 저장)"""
        fixed = persist_thumbs_in_master(html, self._p_resource_dir())
        self._write(self._p_master_file(), fixed)
        return {"ok": True}

    # ---- 푸시: master_content → resource/*.html ----
    def _push_master_to_resource(self) -> int:
        html = self._read(self._p_master_file())
        if not html:
            print("[push] no master_content.html, skip")
            return 0

        if BeautifulSoup is None:
            print("[push] bs4 missing; cannot safely render without sanitizer/dedupe")
            return 0

        soup = BeautifulSoup(html, "html.parser")
        block_count = 0
        resource_dir = self._p_resource_dir()

        folders_for_master: list[dict] = []

        for div in soup.find_all("div", class_="folder"):
            h2 = div.find("h2")
            if not h2:
                continue
            folder = h2.get_text(strip=True)
            block_count += 1

            # AC2: snatizer 메트릭 활성화
            cleaned_div_html, san_m = sanitize_for_publish(
                str(div), return_metrics=True
            )
            # 누적치를 sync 메트릭으로 올리기 위해 임시 저장
            # self._san_metrics는 sync() 호출마다 초기화
            if not hasattr(self, "_san_metrics"):
                self._san_metrics = {
                    "removed_nodes": 0,
                    "removed_attrs": 0,
                    "unwrapped_tags": 0,
                    "blocked_urls": 0,
                }
            for k, v in san_m.items():
                self._san_metrics[k] += v

            # (옵션) 폴더별 상세 로그
            if SAN_VERBOSE and any(san_m.values()):
                print(
                    f"[san] folder='{folder}' "
                    f"removed_nodes={san_m['removed_nodes']} "
                    f"removed_attrs={san_m['removed_attrs']} "
                    f"unwrapped_tags={san_m['unwrapped_tags']} "
                    f"blocked_urls={san_m['blocked_urls']}"
                )

            cleaned_div_html = ensure_thumb_in_head(
                cleaned_div_html, folder, resource_dir
            )

            # .inner '내용만' 추출
            inner_only = extract_inner_html_only(cleaned_div_html)

            # master_index용
            inner_for_master = adjust_paths_for_folder(
                inner_only, folder, for_resource_master=True
            )
            inner_for_master = strip_back_to_master(inner_for_master)

            # child index용
            inner_for_folder = adjust_paths_for_folder(
                inner_only, folder, for_resource_master=False
            )

            # 썸네일 경로
            from thumbs import _safe_name as _thumb_safe_name

            safe = _thumb_safe_name(folder)
            thumb_rel_for_master = None
            if (resource_dir / folder / "thumbs" / f"{safe}.jpg").exists():
                thumb_rel_for_master = f"{folder}/thumbs/{safe}.jpg"

            # 마스터 렌더 입력
            folders_for_master.append(
                {
                    "title": folder,
                    "html": inner_for_master,
                    "thumb": thumb_rel_for_master,
                }
            )

            # child index 생성
            child_html = render_child_index(
                title=folder,
                html_body=inner_for_folder,
                thumb_src=(f"thumbs/{safe}.jpg" if thumb_rel_for_master else None),
            )
            self._write(self._p_resource_dir() / folder / "index.html", child_html)

        master_html = render_master_index(folders_for_master)
        self._write(self._p_resource_master(), master_html)

        print(f"[push] blocks={block_count} ok=True")
        return block_count

    # ---- 동기화 ----
    def sync(self) -> Dict[str, Any]:
        t0 = time.perf_counter()
        base = self._p_base_dir()
        resource = self._p_resource_dir()
        print(f"[sync] start base={base} resource={resource}")

        errors: list[str] = []
        metrics: Dict[str, Any] = {
            "foldersAdded": 0,
            "blocksUpdated": 0,
            "scanRc": None,
            "durationMs": None,
            "sanRemovedNodes": 0,  # AC2: sanitizer 메트릭
            "sanRemovedAttrs": 0,  # AC2: sanitizer 메트릭
            "sanUnwrappedTags": 0,  # AC2: sanitizer 메트릭
            "sanBlockedUrls": 0,  # AC2: sanitizer 메트릭
        }

        # AC2: sanitizer 누적치 초기화
        self._san_metrics = {
            "removed_nodes": 0,
            "removed_attrs": 0,
            "unwrapped_tags": 0,
            "blocked_urls": 0,
        }

        # 1) 썸네일/리소스 스캔
        scan_rc = run_sync_all(resource_dir=self._p_resource_dir(), thumb_width=640)
        scan_ok = scan_rc == 0
        metrics["scanRc"] = scan_rc
        print(f"[scan] ok={scan_ok} rc={scan_rc}")

        # DEBUG: 강제 실패 주입
        forced_scan_fail = os.getenv("ARTIDX_FAIL_SCAN") == "1"
        if forced_scan_fail:
            scan_ok = False
            metrics["scanRc"] = -1

        if not scan_ok:
            errors.append(
                "DEBUG: ARTIDX_FAIL_SCAN=1로 인해 스캔을 실패로 강제 설정"
                if forced_scan_fail
                else f"썸네일/리소스 스캔 실패(rc={metrics['scanRc']})"
            )

        # 2) 신규 폴더를 master_content에 자동 머지
        try:
            added = self._ensure_new_folders_in_master()
            if added > 0:
                metrics["foldersAdded"] = added
                print(f"[merge] added folders={added}")
        except Exception as e:
            errors.append(f"신규 폴더 자동 병합 실패: {e}")
            print(f"[merge] failed: {e}")

        # 3) 푸시
        push_ok = True
        block_count = 0
        try:
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

        # AC2: sanitizer 누적치 반영
        san = getattr(self, "_san_metrics", None) or {}
        metrics["sanRemovedNodes"] = san.get("removed_nodes", 0)
        metrics["sanRemovedAttrs"] = san.get("removed_attrs", 0)
        metrics["sanUnwrappedTags"] = san.get("unwrapped_tags", 0)
        metrics["sanBlockedUrls"] = san.get("blocked_urls", 0)

        # AC2: 누적치 반영
        san = getattr(self, "_san_metrics", None) or {}
        metrics["sanRemovedNodes"] = san.get("removed_nodes", 0)
        metrics["sanRemovedAttrs"] = san.get("removed_attrs", 0)
        metrics["sanUnwrappedTags"] = san.get("unwrapped_tags", 0)
        metrics["sanBlockedUrls"] = san.get("blocked_urls", 0)

        print(
            f"[sync] done ok={ok} scanOk={scan_ok} pushOk={push_ok} "
            f"blocks={block_count} durationMs={metrics['durationMs']} "
            f"sanRemovedNodes={metrics['sanRemovedNodes']} "
            f"sanRemovedAttrs={metrics['sanRemovedAttrs']} "
            f"sanUnwrappedTags={metrics['sanUnwrappedTags']} "
            f"sanBlockedUrls={metrics['sanBlockedUrls']}"
        )

        return {
            "ok": ok,
            "scanOk": scan_ok,
            "pushOk": push_ok,
            "errors": errors,
            "metrics": metrics,
        }

    # ---- (옵션) 리빌드 → master_content 초기화 ----
    def rebuild_master(self) -> Dict[str, Any]:
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
            blocks.append(make_clean_block_html_for_master(p.name, resource_dir))

        new_html = "\n\n".join(blocks) + ("\n" if blocks else "")
        self._write(self._p_master_file(), new_html)
        return {"ok": True, "added": len(blocks)}

    # ---- 썸네일 1건 ----
    def refresh_thumb(self, folder_name: str, width: int = 640) -> Dict[str, Any]:
        folder = self._p_resource_dir() / folder_name
        thumbs_dir = folder / "thumbs"
        try:
            if thumbs_dir.exists() and thumbs_dir.is_file():
                return {
                    "ok": False,
                    "error": f"'thumbs' 경로가 파일입니다: {thumbs_dir}. 폴더로 복구해 주세요.",
                }

            ok = make_thumbnail_for_folder(folder, max_width=width)
            if ok:
                return {"ok": True}
            else:
                return {
                    "ok": False,
                    "error": "썸네일 생성 실패(소스 이미지 없음, 포맷 미지원, 또는 권한 문제)",
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _ensure_new_folders_in_master(self) -> int:
        """resource/<폴더> 중 master_content.html에 카드가 없는 폴더를 '깨끗한 기본 카드'로 자동 추가"""
        if BeautifulSoup is None:
            print("[merge] bs4 missing; skip adding new folders")
            return 0

        master_file = self._p_master_file()
        resource_dir = self._p_resource_dir()

        html = self._read(master_file)
        soup = BeautifulSoup(html or "", "html.parser")

        existing: set[str] = set()
        for div in soup.find_all("div", class_="folder"):
            h2 = div.find("h2")
            if h2:
                name = (h2.get_text() or "").strip()
                if name:
                    existing.add(name)

        fs_folders: list[str] = []
        for p in sorted(resource_dir.iterdir(), key=lambda x: x.name):
            if not p.is_dir():
                continue
            if p.name.startswith(".") or p.name.lower() == "thumbs":
                continue
            fs_folders.append(p.name)

        new_blocks: list[str] = []
        for folder in fs_folders:
            if folder not in existing:
                new_blocks.append(
                    make_clean_block_html_for_master(folder, resource_dir)
                )

        if not new_blocks:
            return 0

        new_html = (html or "").rstrip() + "\n\n" + "\n\n".join(new_blocks) + "\n"
        self._write(master_file, new_html)
        print(
            f"[merge] added={len(new_blocks)} folders: {', '.join([f for f in fs_folders if f not in existing])}"
        )
        return len(new_blocks)
