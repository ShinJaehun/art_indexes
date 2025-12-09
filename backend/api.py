from pathlib import Path
from typing import Dict, Any, Union, List, Optional, Tuple
import re
import time
import os
import traceback
import shutil
from datetime import datetime

try:
    from .fsutil import atomic_write_text
except Exception:
    from fsutil import atomic_write_text

try:
    from .lockutil import SyncLock, SyncLockError
except Exception:
    from lockutil import SyncLock, SyncLockError

try:
    from .thumbs import make_thumbnail_for_folder, has_ffmpeg, has_poppler
except Exception:
    from thumbs import make_thumbnail_for_folder, has_ffmpeg, has_poppler

try:
    # ensure_css_assets 포함하여 가져옴
    from .builder import (
        run_sync_all,
        render_master_index,
        render_child_index,
        ensure_css_assets,
        ensure_card_ids,
    )
except Exception:
    from builder import (
        run_sync_all,
        render_master_index,
        render_child_index,
        ensure_css_assets,
        ensure_card_ids,
    )

try:
    from .sanitizer import sanitize_for_publish
except Exception:
    from sanitizer import sanitize_for_publish

# 공개 API 우선 사용, 없으면 프라이빗 심볼로 폴백(하위호환)
try:
    from .sanitizer import safe_unescape_tag_texts_in_inner as _safe_unescape_api
except Exception:
    try:
        from .sanitizer import _safe_unescape_tag_texts_in_inner as _safe_unescape_api  # type: ignore
    except Exception:
        try:
            from sanitizer import safe_unescape_tag_texts_in_inner as _safe_unescape_api
        except Exception:
            try:
                from sanitizer import _safe_unescape_tag_texts_in_inner as _safe_unescape_api  # type: ignore
            except Exception:
                _safe_unescape_api = None  # bs4 미사용

try:
    from .pruner import DiffReporter, PruneReport, PruneApplier
except ImportError:
    from pruner import DiffReporter, PruneReport, PruneApplier

try:
    from .htmlops import (
        extract_body_inner,
        prefix_resource_paths_for_root,
        strip_back_to_master,
        adjust_paths_for_folder,
        extract_inner_html_only,
    )
except Exception:
    from htmlops import (
        extract_body_inner,
        prefix_resource_paths_for_root,
        strip_back_to_master,
        adjust_paths_for_folder,
        extract_inner_html_only,
    )

try:
    from .thumbops import (
        ensure_thumb_in_head,
        inject_thumbs_for_preview,
        persist_thumbs_in_master,
        make_clean_block_html_for_master,
    )
except Exception:
    from thumbops import (
        ensure_thumb_in_head,
        inject_thumbs_for_preview,
        persist_thumbs_in_master,
        make_clean_block_html_for_master,
    )

try:
    from .card_registry import CardRegistry
except Exception:
    from card_registry import CardRegistry

try:
    from bs4 import BeautifulSoup, Comment
except Exception:
    BeautifulSoup = None
    Comment = None

# -------- 상수 --------
try:
    from .constants import (
        MASTER_INDEX,
        MASTER_CONTENT,
        BACKEND_DIR,
        RESOURCE_DIR,
        DEFAULT_LOCK_PATH,
    )
except Exception:
    from constants import (
        MASTER_INDEX,
        MASTER_CONTENT,
        BACKEND_DIR,
        RESOURCE_DIR,
        DEFAULT_LOCK_PATH,
    )

# sanitizer 로그 토글
SAN_VERBOSE = os.getenv("SUKSUKIDX_SAN_VERBOSE") == "1"

# 디버깅용 강제 실패 플래그(문서화용 메모)
# - SUKSUKIDX_FAIL_SCAN=1  → 썸네일/리소스 스캔 실패로 취급
# - SUKSUKIDX_FAIL_PUSH=1  → push 단계 예외 강제 발생
# 실배포에서는 사용하지 말고, 개발/테스트시에만 사용하세요.


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
        self._master_content_path_str = str(base_dir / BACKEND_DIR / MASTER_CONTENT)
        self._resource_dir_str = str(base_dir / RESOURCE_DIR)
        self._master_index_path_str = str(Path(self._resource_dir_str) / MASTER_INDEX)

        # ID 레지스트리: backend/.suksukidx.registry.json 기준
        self._registry = CardRegistry(
            registry_path=base_dir / BACKEND_DIR / ".suksukidx.registry.json",
            resource_dir=base_dir / RESOURCE_DIR,
        )

        super().__init__() if hasattr(super(), "__init__") else None
        # ENV로 락 경로 오버라이드 허용(멀티 인스턴스/테스트 편의)
        env_lock = os.getenv("SUKSUKIDX_LOCK_PATH")
        default_lock = base_dir / DEFAULT_LOCK_PATH
        self._lock_path = Path(env_lock) if env_lock else default_lock

    # ---- 내부 Path 헬퍼 ----
    def _p_base_dir(self) -> Path:
        return Path(self._base_dir_str)

    def _p_master_content(self) -> Path:
        return Path(self._master_content_path_str)

    def _p_resource_dir(self) -> Path:
        return Path(self._resource_dir_str)

    def _p_master_index(self) -> Path:
        return Path(self._master_index_path_str)

    # ---- 파일 IO ----
    def _read(self, p: Union[str, Path]) -> str:
        path_obj = Path(p)
        return path_obj.read_text(encoding="utf-8") if path_obj.exists() else ""

    def _write(self, p: Union[str, Path], s: str) -> None:
        # 모든 산출물 저장은 원자적 write로 고정
        path_obj = Path(p)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(str(path_obj), s, encoding="utf-8", newline="\n")

    def _prefix_resource_for_ui(self, html: str) -> str:
        """backend/ui/index.html에서 주입해 렌더링할 때만 resource/ 경로에 ../../ 프리픽스"""
        try:
            from bs4 import BeautifulSoup as _BS
        except Exception:
            _BS = None

        if not html:
            return html
        if _BS is None:
            # 최소 안전망: 단순 치환(속성값 내에서만)
            return (
                html.replace('src="resource/', 'src="../../resource/')
                .replace("src='resource/", "src='../../resource/")
                .replace('href="resource/', 'href="../../resource/')
                .replace("href='resource/", "href='../../resource/")
            )

        soup = _BS(html, "html.parser")
        for tag in soup.find_all(True):
            for attr in ("src", "href"):
                value = tag.get(attr)
                if not value or not isinstance(value, str):
                    continue
                if value.startswith("resource/"):
                    tag[attr] = f"../../{value}"
        return str(soup)

    def get_current_index_path(self) -> Dict[str, Any]:
        """
        현재 사용 중인 인덱스 파일(예: resource/master_index.html)의
        절대 경로를 UI에 알려주기 위한 헬퍼.
        """
        master_index = self._p_resource_dir() / MASTER_INDEX
        return {"path": str(master_index.resolve())}

    # ---- 로드 / 저장 ----
    def get_master(self) -> Dict[str, Any]:
        """
        우선 master_content.html을 보여줌.
        없으면 resource/master_index.html의 body-inner를 추출해 초기화 + 경로접두어 보정 후 반환.
        """
        master_content = self._p_master_content()
        master_index = self._p_master_index()

        if master_content.exists():
            raw_html = self._read(master_content)
            html_for_view = inject_thumbs_for_preview(raw_html, self._p_resource_dir())
            html_for_view = self._prefix_resource_for_ui(html_for_view)
            return {"html": html_for_view}

        if master_index.exists():
            inner = extract_body_inner(self._read(master_index))
            inner = prefix_resource_paths_for_root(inner)
            self._write(master_content, inner)
            html_for_view = inject_thumbs_for_preview(inner, self._p_resource_dir())
            html_for_view = self._prefix_resource_for_ui(html_for_view)
            return {"html": html_for_view}

        return {"html": ""}

    def save_master(self, html: str) -> Dict[str, Any]:
        """
        편집 저장:
        - master_content.html 저장
        - 곧바로 master_index / child index까지 재빌드(_push_master_to_resource)
        """
        if "<h2>" not in html and "&lt;h2&gt;" in html:
            print("[save_master] WARN: incoming HTML is already escaped")

        fixed_html = persist_thumbs_in_master(html, self._p_resource_dir())

        # 저장 전에 .inner 내부의 &lt;...&gt;를 '허용 태그'만 실제 태그로 복원
        if BeautifulSoup is not None:
            soup = BeautifulSoup(fixed_html, "html.parser")
            # 엔티티로 들어온 <a> 등을 실제 노드로 변환
            if _safe_unescape_api is not None:
                _safe_unescape_api(soup)

            # href 정규화: 스킴 없는 외부 도메인에 https:// 붙이기
            for anchor in soup.select(".inner a[href]"):
                href = (anchor.get("href") or "").strip()
                if href and not re.match(
                    r"^(https?://|mailto:|tel:|#|/|\.\./)", href, re.I
                ):
                    if re.match(r"^(www\.|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})", href):
                        anchor["href"] = f"https://{href}"

            fixed_html = str(soup)

        # 1) master_content 저장
        self._write(self._p_master_content(), fixed_html)

        # 2) 파생물(master_index + child index) 재빌드
        errors: List[str] = []
        blocks: Optional[int] = None
        try:
            blocks = self._push_master_to_resource()
        except Exception as exc:
            msg = f"_push_master_to_resource 실패: {exc}"
            print(f"[save_master] {msg}")
            errors.append(msg)

        return {
            "ok": not errors,
            "blocks": blocks,
            "errors": errors or None,
        }

    # ---- 푸시: master_content → resource/*.html ----
    def _push_master_to_resource(self) -> int:
        master_content = self._p_master_content()
        master_index = self._p_master_index()
        master_html = self._read(master_content)
        if not master_html:
            # Case B: master_index는 있는데 master_content만 없는 경우 → 의도적 삭제로 간주, 푸시 스킵
            if (not master_content.exists()) and master_index.exists():
                print(
                    "[push] skip: master_content missing while master_index exists "
                    "(treat as intentional delete; no bootstrap)"
                )
            else:
                # 일반 보호: 내용이 비거나 파일이 없으면 푸시 불가
                print("[push] no master_content.html, skip")
            return 0

        if BeautifulSoup is None:
            print("[push] bs4 missing; cannot safely render without sanitizer/dedupe")
            return 0

        soup = BeautifulSoup(master_html, "html.parser")
        block_count = 0
        resource_dir = self._p_resource_dir()

        # P3-1: resource/ 폴더에 대한 카드 ID 보장 (.suksukidx.id)
        try:
            folder_id_map = ensure_card_ids(resource_dir)
        except Exception as exc:
            folder_id_map = {}
            print(f"[id] WARN: ensure_card_ids failed in push: {exc}")

        cards_for_master: List[Dict[str, Any]] = []

        hidden_count = 0

        for card_div in soup.find_all("div", class_="card"):
            heading = card_div.find("h2")
            if not heading:
                continue
            card_title = heading.get_text(strip=True)
            if not card_title:
                print("[push] WARN: empty <h2> text in a .card block; skipped")
                continue
            block_count += 1

            # --- 생성 시각 메타 보완: 없으면 폴더 mtime 기준으로 채움 ---
            if not card_div.get("data-created-at"):
                created_at: Optional[str] = None
                folder_path = resource_dir / card_title
                try:
                    if folder_path.exists() and folder_path.is_dir():
                        ts = folder_path.stat().st_mtime
                        dt = datetime.fromtimestamp(ts).astimezone()
                        created_at = dt.isoformat(timespec="seconds")
                except Exception:
                    created_at = None
                if created_at is None:
                    try:
                        dt = datetime.now().astimezone()
                        created_at = dt.isoformat(timespec="seconds")
                    except Exception:
                        created_at = None
                if created_at:
                    card_div["data-created-at"] = created_at

            # --- P3-2: 메타 읽기 ---
            def _as_bool(value: Any) -> Optional[bool]:
                if value is None:
                    return None
                if isinstance(value, str):
                    return value.strip().lower() == "true"
                return bool(value)

            meta_hidden = _as_bool(card_div.get("data-hidden"))

            try:
                meta_order = (
                    int(card_div.get("data-order"))
                    if card_div.get("data-order")
                    not in (
                        None,
                        "",
                    )
                    else None
                )
            except Exception:
                meta_order = None

            if meta_hidden:
                hidden_count += 1

            # P3-1: 제목(=폴더명 가정)으로 card_id 주입
            card_id = folder_id_map.get(card_title)
            if card_id:
                card_div["data-card-id"] = card_id
            else:
                print(f"[id] WARN: no card_id for title='{card_title}'")

            # sanitizer 메트릭 활성화
            cleaned_div_html, san_metrics = sanitize_for_publish(
                str(card_div), return_metrics=True
            )

            # 누적치를 sync 메트릭으로 올리기 위해 임시 저장
            if not hasattr(self, "_san_metrics"):
                self._san_metrics = {
                    "removed_nodes": 0,
                    "removed_attrs": 0,
                    "unwrapped_tags": 0,
                    "blocked_urls": 0,
                }
            for k, v in san_metrics.items():
                self._san_metrics[k] += v

            # 카드별 상세 로그
            if SAN_VERBOSE and any(san_metrics.values()):
                print(
                    f"[san] card='{card_title}' "
                    f"removed_nodes={san_metrics['removed_nodes']} "
                    f"removed_attrs={san_metrics['removed_attrs']} "
                    f"unwrapped_tags={san_metrics['unwrapped_tags']} "
                    f"blocked_urls={san_metrics['blocked_urls']}"
                )

            cleaned_div_html = ensure_thumb_in_head(
                cleaned_div_html, card_title, resource_dir
            )

            # .inner '내용만' 추출
            inner_only = extract_inner_html_only(cleaned_div_html)

            # master_index용
            inner_for_master = adjust_paths_for_folder(
                inner_only, card_title, for_resource_master=True
            )
            inner_for_master = strip_back_to_master(inner_for_master)

            # 썸네일 경로
            try:
                from .thumbs import _safe_name as _thumb_safe_name
            except Exception:
                from thumbs import _safe_name as _thumb_safe_name

            safe_name = _thumb_safe_name(card_title)
            thumb_rel_for_master = None
            if (resource_dir / card_title / "thumbs" / f"{safe_name}.jpg").exists():
                thumb_rel_for_master = f"{card_title}/thumbs/{safe_name}.jpg"

            # master 렌더 입력
            # 숨김(meta_hidden=True) 카드는 master_index에서 제외(렌더러 의존 없이 보장)
            if not meta_hidden:
                cards_for_master.append(
                    {
                        "title": card_title,
                        "html": inner_for_master,
                        "thumb": thumb_rel_for_master,
                        "id": card_id,
                        "hidden": meta_hidden,
                        "order": meta_order,
                    }
                )

        # CSS 자산 보장 + 파일명 획득
        css_basename = ensure_css_assets(resource_dir)  # e.g., master.<HASH>.css

        # master/child 모두 최종 렌더 후 파일 기록
        # master_index 순서는 master_content.html의 카드 등장 순서를 그대로 따른다
        master_html = render_master_index(cards_for_master, css_basename=css_basename)
        self._write(self._p_master_index(), master_html)

        # master_content.html에도 data-card-id가 채워진 soup를 반영 (P3-1)
        try:
            self._write(self._p_master_content(), str(soup))
        except Exception as exc:
            print(
                f"[push] WARN: failed to persist data-card-id into master_content: {exc}"
            )

        # child
        for card_div in soup.find_all("div", class_="card"):
            heading = card_div.find("h2")
            if not heading:
                continue
            title = heading.get_text(strip=True)
            if not title:
                continue

            # 🔹 파일시스템에 폴더가 실제로 존재할 때만 child index 생성
            folder_path = resource_dir / title
            if not (folder_path.exists() and folder_path.is_dir()):
                print(f"[push] skip child for missing folder: {title}")
                continue

            card_id = folder_id_map.get(title)

            cleaned_div_html, _ = sanitize_for_publish(
                str(card_div), return_metrics=True
            )
            inner_only = extract_inner_html_only(cleaned_div_html)
            inner_for_folder = adjust_paths_for_folder(
                inner_only, title, for_resource_master=False
            )

            # 썸네일 다시 계산
            try:
                from .thumbs import _safe_name as _thumb_safe_name
            except Exception:
                from thumbs import _safe_name as _thumb_safe_name
            safe_name = _thumb_safe_name(title)
            has_thumb = (resource_dir / title / "thumbs" / f"{safe_name}.jpg").exists()
            thumb_src = f"thumbs/{safe_name}.jpg" if has_thumb else None

            child_html = render_child_index(
                title=title,
                html_body=inner_for_folder,
                thumb_src=thumb_src,
                css_basename=css_basename,
                card_id=card_id,
            )
            self._write(folder_path / "index.html", child_html)

        print(f"[push] ok=True blocks={block_count} css={css_basename}")

        if hidden_count:
            print(f"[push] meta: hidden={hidden_count}")
        return block_count

    # ---- 동기화 ----
    def sync(self) -> Dict[str, Any]:
        """
        Lock & Error Safety 적용 + print 로깅
        - 중복 실행 방지: backend/.sync.lock 파일 기반
        - 예외 발생 시 반환하고, traceback 일부를 errors에 포함
        - 기존 메트릭/리턴 형태 최대한 유지
        """
        start_ts = time.perf_counter()
        base_dir = self._p_base_dir()
        resource_dir = self._p_resource_dir()
        print(f"[sync] start base={base_dir} resource={resource_dir}")

        # 잠금 만료시간(초): 기본 3600, 환경변수로 조절 가능
        stale_after = int(os.getenv("SUKSUKIDX_LOCK_STALE_AFTER", "3600"))

        try:
            with SyncLock(self._lock_path, stale_after=stale_after):
                errors: list[str] = []
                metrics: Dict[str, Any] = {
                    "foldersAdded": 0,
                    "blocksUpdated": 0,
                    "scanRc": None,
                    "durationMs": None,
                    "sanRemovedNodes": 0,
                    "sanRemovedAttrs": 0,
                    "sanUnwrappedTags": 0,
                    "sanBlockedUrls": 0,
                    "prunedFromMaster": 0,
                    "childRebuilt": 0,
                    "thumbsDeleted": 0,
                }

                # sanitizer 누적치 초기화
                self._san_metrics = {
                    "removed_nodes": 0,
                    "removed_attrs": 0,
                    "unwrapped_tags": 0,
                    "blocked_urls": 0,
                }

                # 1) 썸네일/리소스 스캔
                scan_rc = run_sync_all(
                    resource_dir=self._p_resource_dir(), thumb_width=640
                )
                scan_ok = scan_rc == 0
                metrics["scanRc"] = scan_rc
                print(f"[scan] ok={scan_ok} rc={scan_rc}")

                # DEBUG: 강제 실패 주입
                forced_scan_fail = os.getenv("SUKSUKIDX_FAIL_SCAN") == "1"
                if forced_scan_fail:
                    scan_ok = False
                    metrics["scanRc"] = -1

                if not scan_ok:
                    errors.append(
                        "DEBUG: SUKSUKIDX_FAIL_SCAN=1로 인해 스캔을 실패로 강제 설정"
                        if forced_scan_fail
                        else f"썸네일/리소스 스캔 실패(rc={metrics['scanRc']})"
                    )

                # 2) 콜드스타트 부트스트랩
                try:
                    mc = self._p_master_content()
                    mi = self._p_master_index()
                    if (not mc.exists()) and (not mi.exists()):
                        rebuild_result = self.rebuild_master()
                        added_blocks = (rebuild_result or {}).get("added", 0)
                        print(
                            f"[bootstrap] coldstart: created master_content.html with {added_blocks} blocks"
                        )
                except Exception as exc:
                    errors.append(f"부트스트랩 실패: {exc}")
                    print(f"[bootstrap] failed: {exc}")

                # 3) 신규 카드 자동 머지 (기본 ON) + ID 기반 rename 반영
                try:
                    if os.getenv("SUKSUKIDX_AUTO_MERGE_NEW", "1") != "0":
                        master_content_path = self._p_master_content()
                        current_master_html = (
                            master_content_path.read_text(encoding="utf-8")
                            if master_content_path.exists()
                            else ""
                        )
                        merged_html, added_count = self._ensure_cards_for_new_folders(
                            current_master_html
                        )

                        # ✅ 내용이 실제로 바뀌었으면, 새 카드가 없더라도 저장
                        if merged_html != current_master_html:
                            self._write(master_content_path, merged_html)

                        if added_count > 0:
                            metrics["foldersAdded"] = added_count
                            print(f"[merge] added cards={added_count}")
                except Exception as exc:
                    errors.append(f"신규 카드 자동 병합 실패: {exc}")
                    print(f"[merge] failed: {exc}")

                # 4) prune 적용: 파일시스템 기준으로 사라진 폴더 정리
                prune_removed = 0
                prune_child_built = 0
                prune_thumbs = 0
                try:
                    # 기본 ON, 필요하면 SUKSUKIDX_PRUNE_ON_SYNC=0 으로 비활성화 가능
                    if os.getenv("SUKSUKIDX_PRUNE_ON_SYNC", "1") != "0":
                        # 썸네일 실제 삭제는 기본 OFF
                        # 필요 시 SUKSUKIDX_PRUNE_DELETE_THUMBS=1 로 고아 썸네일도 함께 삭제
                        delete_thumbs = (
                            os.getenv("SUKSUKIDX_PRUNE_DELETE_THUMBS", "0") == "1"
                        )

                        # 기존 prune_apply 재사용 (DiffReporter + PruneApplier 내부 호출)
                        prune_result = self.prune_apply(
                            report=None, delete_thumbs=delete_thumbs
                        )
                        prune_removed = prune_result.get("removed_from_master", 0)
                        prune_child_built = prune_result.get("child_built", 0)
                        prune_thumbs = prune_result.get("thumbs_deleted", 0)

                        if (
                            prune_removed != 0
                            or prune_child_built != 0
                            or prune_thumbs != 0
                        ):
                            print(
                                "[prune] applied: "
                                f"removed_from_master={prune_removed} "
                                f"child_built={prune_child_built} "
                                f"thumbs_deleted={prune_thumbs} "
                                f"delete_thumbs={delete_thumbs}"
                            )

                        # 레지스트리 GC: prune으로 제거된 card_id 들을 registry 에서도 정리
                        removed_ids = prune_result.get("removed_card_ids") or []
                        for cid in removed_ids:
                            try:
                                removed_reg = self._registry.remove_by_card_id(cid)
                                if removed_reg:
                                    print(
                                        f"[registry] GC removed entry from prune id={cid}"
                                    )
                            except Exception as exc:
                                msg = f"레지스트리 GC 실패(id={cid}): {exc}"
                                print(f"[registry] {msg}")
                                errors.append(msg)

                except Exception as exc:
                    errors.append(f"프룬 적용 실패: {exc}")
                    print(f"[prune] failed: {exc}")

                metrics["prunedFromMaster"] = prune_removed
                metrics["childRebuilt"] = prune_child_built
                metrics["thumbsDeleted"] = prune_thumbs

                # 5) 푸시
                push_ok = True
                blocks_updated = 0
                try:
                    if os.getenv("SUKSUKIDX_FAIL_PUSH") == "1":
                        raise RuntimeError(
                            "DEBUG: SUKSUKIDX_FAIL_PUSH=1 강제 푸시 예외"
                        )

                    blocks_updated = self._push_master_to_resource()
                    metrics["blocksUpdated"] = blocks_updated
                except Exception as exc:
                    push_ok = False
                    errors.append(f"파일 반영(푸시) 실패: {exc}")
                    print(f"[push] failed: {exc}")

                # 6) ID 레지스트리 부트스트랩(현재는 항상 ON)
                #    - 반드시 push 이후에 실행해서
                #      .suksukidx.id / data-card-id 가 동기화된 최종 master_content 기준으로 갱신
                try:
                    reg = self._registry.bootstrap_from_master(self._p_master_content())
                    if isinstance(reg, dict):
                        metrics["idRegistryItems"] = len(reg.get("items", []))

                        # P5: 썸네일 실존 여부에 맞게 thumb_source 정리
                        items = reg.get("items") or []
                        resource_dir = self._p_resource_dir()

                        try:
                            from .thumbs import _safe_name as _thumb_safe_name
                        except Exception:
                            from thumbs import _safe_name as _thumb_safe_name

                        for item in items:
                            cid = (item.get("id") or "").strip()
                            folder = (item.get("folder") or "").strip()
                            if not cid or not folder:
                                continue

                            safe_name = _thumb_safe_name(folder)
                            thumb_file = (
                                resource_dir / folder / "thumbs" / f"{safe_name}.jpg"
                            )

                            # 1) 썸네일 파일이 없는데 thumb_source가 남아 있으면 → None으로 클리어
                            if (not thumb_file.exists()) and item.get("thumb_source"):
                                try:
                                    self._registry.upsert_item(
                                        card_id=cid,
                                        folder=folder,
                                        thumb_source=None,
                                    )
                                    print(
                                        f"[registry] cleared thumb_source for id={cid} "
                                        f"(folder={folder}, file missing)"
                                    )
                                except Exception as exc2:
                                    msg = f"레지스트리 thumb_source 정리 실패(id={cid}): {exc2}"
                                    print(f"[registry] {msg}")
                                    errors.append(msg)

                except Exception as exc:
                    errors.append(f"ID 레지스트리 갱신 실패: {exc}")
                    print(f"[registry] refresh failed: {exc}")

                overall_ok = scan_ok and push_ok
                metrics["durationMs"] = int((time.perf_counter() - start_ts) * 1000)

                # sanitizer 누적치 반영
                san = getattr(self, "_san_metrics", None) or {}
                metrics["sanRemovedNodes"] = san.get("removed_nodes", 0)
                metrics["sanRemovedAttrs"] = san.get("removed_attrs", 0)
                metrics["sanUnwrappedTags"] = san.get("unwrapped_tags", 0)
                metrics["sanBlockedUrls"] = san.get("blocked_urls", 0)

                print(
                    f"[sync] done ok={overall_ok} scanOk={scan_ok} pushOk={push_ok} "
                    f"blocks={blocks_updated} durationMs={metrics['durationMs']} "
                    f"sanRemovedNodes={metrics['sanRemovedNodes']} "
                    f"sanRemovedAttrs={metrics['sanRemovedAttrs']} "
                    f"sanUnwrappedTags={metrics['sanUnwrappedTags']} "
                    f"sanBlockedUrls={metrics['sanBlockedUrls']}"
                )

                dbg_flags = []
                if os.getenv("SUKSUKIDX_FAIL_SCAN") == "1":
                    dbg_flags.append("FAIL_SCAN")
                if os.getenv("SUKSUKIDX_FAIL_PUSH") == "1":
                    dbg_flags.append("FAIL_PUSH")
                if dbg_flags:
                    print(f"[sync] debugFlags={','.join(dbg_flags)}")

                return {
                    "ok": overall_ok,
                    "scanOk": scan_ok,
                    "pushOk": push_ok,
                    "errors": errors,
                    "metrics": metrics,
                }

        except SyncLockError as exc:
            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            print(
                f"[sync] LOCKED: {exc} (lock={self._lock_path}, stale_after={stale_after}s)"
            )
            return {
                "ok": False,
                "scanOk": None,
                "pushOk": None,
                "errors": ["locked"],
                "metrics": {
                    "durationMs": duration_ms,
                    "foldersAdded": 0,
                    "blocksUpdated": 0,
                    "scanRc": None,
                    "sanRemovedNodes": 0,
                    "sanRemovedAttrs": 0,
                    "sanUnwrappedTags": 0,
                    "sanBlockedUrls": 0,
                    "prunedFromMaster": 0,
                    "childRebuilt": 0,
                    "thumbsDeleted": 0,
                },
                "locked": True,
            }

        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            tb = traceback.format_exc(limit=5)
            print(f"[sync] EXCEPTION: {exc}\n{tb}")
            return {
                "ok": False,
                "scanOk": None,
                "pushOk": False,
                "errors": [f"exception: {exc}", tb.strip()],
                "metrics": {
                    "durationMs": duration_ms,
                    "foldersAdded": 0,
                    "blocksUpdated": 0,
                    "scanRc": None,
                    "sanRemovedNodes": 0,
                    "sanRemovedAttrs": 0,
                    "sanUnwrappedTags": 0,
                    "sanBlockedUrls": 0,
                    "prunedFromMaster": 0,
                    "childRebuilt": 0,
                    "thumbsDeleted": 0,
                },
            }

    def _ensure_cards_for_new_folders(self, master_html: str) -> Tuple[str, int]:
        """
        master_content.html이 이미 존재하는 상태에서,
        resource/ 아래 새로 생긴 폴더에 대한 기본 카드 블럭을 생성해 붙인다.

        + P3-3: 폴더 rename 지원
          - .suksukidx.id(폴더) ↔ data-card-id(카드)를 매칭해서
            같은 ID인데 폴더 이름과 카드 제목이 다르면 'rename'으로 간주하고
            카드의 data-card / <h2> 텍스트를 새 폴더명으로 갱신한다.
          - 같은 폴더명을 가진 중복 카드가 여러 개 있을 경우,
            해당 ID를 가진 '주 카드'만 남기고 나머지 카드는 제거한다.

        반환값:
          (변경된_html, 추가된_카드_개수)
        """
        if BeautifulSoup is None:
            return master_html, 0

        # 0) soup 준비
        if not master_html.strip():
            soup = BeautifulSoup("<div id='content'></div>", "html.parser")
        else:
            soup = BeautifulSoup(master_html, "html.parser")

        root_container = soup  # 카드들이 body 바로 아래에 있다고 가정

        # 1) 기존 카드 메타 수집
        existing_names: set[str] = set()
        id_to_card: dict[str, Any] = {}
        name_to_cards: dict[str, list[Any]] = {}

        for card in root_container.find_all("div", class_="card"):
            # 이름 우선순위: data-card → <h2> 텍스트
            name_attr = (card.get("data-card") or "").strip()
            if not name_attr:
                h2_tag = card.select_one(".card-head h2") or card.find("h2")
                if h2_tag:
                    name_attr = (h2_tag.get_text(strip=True) or "").strip()

            if name_attr:
                existing_names.add(name_attr)
                name_to_cards.setdefault(name_attr, []).append(card)

            cid = (card.get("data-card-id") or "").strip()
            if cid:
                id_to_card[cid] = card

        added_count = 0
        resource_dir = self._p_resource_dir()

        # 2) resource/ 폴더 스캔하면서
        #    - 같은 ID의 카드가 있으면 rename 처리(+중복 카드 정리)
        #    - 그렇지 않고 새 폴더명이면 새 카드 생성
        for folder in sorted(resource_dir.iterdir(), key=lambda p: p.name):
            if not folder.is_dir():
                continue
            name = folder.name
            if name.startswith(".") or name.lower() == "thumbs":
                continue

            # 2-1) 폴더의 카드 ID 읽기 (.suksukidx.id)
            card_id: Optional[str] = None
            id_file = folder / ".suksukidx.id"
            try:
                if id_file.exists():
                    val = id_file.read_text(encoding="utf-8").strip()
                    card_id = val or None
            except Exception:
                card_id = None

            # 2-2) ID 기준 rename 감지
            #      - 폴더에는 card_id가 있고
            #      - master_content 안에 같은 ID의 .card가 이미 있다면
            #        → 그 카드를 이 폴더 이름으로 "이름 변경" 처리
            if card_id and card_id in id_to_card:
                card_el = id_to_card[card_id]

                # 기존 이름(우선 data-card, 없으면 <h2>)
                old_name = (card_el.get("data-card") or "").strip()
                if not old_name:
                    h2_tag = card_el.select_one(".card-head h2") or card_el.find("h2")
                    if h2_tag:
                        old_name = (h2_tag.get_text(strip=True) or "").strip()

                # 이름이 다르면 rename 로그
                if old_name != name:
                    print(f"[id] rename detected: {old_name} -> {name} (id={card_id})")

                # data-card / data-card-id / <h2> 를 새 폴더명으로 정렬
                card_el["data-card"] = name
                card_el["data-card-id"] = card_id

                h2_tag = card_el.select_one(".card-head h2") or card_el.find("h2")
                if h2_tag is not None:
                    # 문자열 노드만 교체 (기존 children 보존)
                    h2_tag.string = name

                existing_names.add(name)

                # name_to_cards 갱신 (새 이름으로 등록)
                name_to_cards.setdefault(name, []).append(card_el)

                # ★ 같은 이름인데 다른 ID를 가진 중복 카드 제거
                dup_cards = [
                    c
                    for c in name_to_cards.get(name, [])
                    if c is not card_el
                    and (c.get("data-card-id") or "").strip() != card_id
                ]
                for dup in dup_cards:
                    old_id = (dup.get("data-card-id") or "").strip()
                    print(
                        f"[id] remove duplicate card for folder '{name}' "
                        f"(old_id={old_id}, keep_id={card_id})"
                    )
                    dup.decompose()

                # 이 이름에 대해선 주 카드 하나만 남기도록 재정리
                name_to_cards[name] = [card_el]

                # 이 폴더는 카드가 이미 있으므로 추가 생성 X
                continue

            # 2-3) 이름 기준으로도 이미 카드가 있으면 스킵
            if name in existing_names:
                continue

            # 2-4) 여기까지 왔으면 "진짜 새 폴더" → 새 카드 생성
            #      이 시점에서는 card_id 를 만들지 않는다.
            card_div = soup.new_tag(
                "div",
                attrs={
                    "class": "card",
                    "data-card": name,
                },
            )

            # 생성 시각 메타: 폴더 mtime 우선, 없으면 현재 시각
            created_at: Optional[str] = None
            try:
                ts = folder.stat().st_mtime
                dt = datetime.fromtimestamp(ts).astimezone()
                created_at = dt.isoformat(timespec="seconds")
            except Exception:
                try:
                    dt = datetime.now().astimezone()
                    created_at = dt.isoformat(timespec="seconds")
                except Exception:
                    created_at = None
            if created_at:
                card_div["data-created-at"] = created_at

            head_div = soup.new_tag("div", attrs={"class": "card-head"})
            h2_tag = soup.new_tag("h2")
            h2_tag.string = name
            head_div.append(h2_tag)
            card_div.append(head_div)

            inner_div = soup.new_tag("div", attrs={"class": "inner"})
            inner_div.append(Comment(" 새 카드 기본 본문 "))
            card_div.append(inner_div)

            root_container.append(card_div)
            existing_names.add(name)
            name_to_cards.setdefault(name, []).append(card_div)
            added_count += 1

        return str(soup), added_count

    # ---- 리빌드 → master_content 초기화 ----
    def rebuild_master(self) -> Dict[str, Any]:
        if BeautifulSoup is None:
            return {
                "ok": False,
                "error": "bs4가 없어 초기화 빌드를 수행할 수 없습니다.",
            }

        resource_dir = self._p_resource_dir()
        blocks: list[str] = []
        for folder_path in sorted(resource_dir.iterdir(), key=lambda x: x.name):
            if not folder_path.is_dir():
                continue
            if folder_path.name.startswith(".") or folder_path.name.lower() == "thumbs":
                continue
            blocks.append(
                make_clean_block_html_for_master(folder_path.name, resource_dir)
            )

        new_html = "\n\n".join(blocks) + ("\n" if blocks else "")
        self._write(self._p_master_content(), new_html)
        return {"ok": True, "added": len(blocks)}

    # ---- 카드 삭제 (ID 기준, 즉시 삭제) ----
    def delete_card_by_id(self, card_id: str) -> Dict[str, Any]:
        """
        data-card-id 기반으로 카드를 즉시 삭제한다.
        - master_content.html에서 해당 .card 블록 제거
        - resource/<folder> 폴더 삭제
        - master_index.html / child index 재생성(_push_master_to_resource)

        UI에서는 폴더/제목이 아니라 card_id(예: .suksukidx.id)를 넘겨야 한다.
        """
        if not card_id:
            return {"ok": False, "error": "card_id가 비어 있습니다."}

        if BeautifulSoup is None:
            return {
                "ok": False,
                "error": "bs4(BeautifulSoup)가 필요합니다. `pip install beautifulsoup4` 후 다시 시도해 주세요.",
            }

        master_content = self._p_master_content()
        master_index = self._p_master_index()

        html = self._read(master_content)

        # 파일이 없거나(=read 결과도 빈 문자열) 내용이 비어 있으면
        # 1차: master_index.html 기준으로 master_content를 한 번 부트스트랩
        if not html.strip():
            if master_index.exists():
                try:
                    inner = extract_body_inner(self._read(master_index))
                    inner = prefix_resource_paths_for_root(inner)
                    self._write(master_content, inner)
                    html = inner
                    print("[delete] bootstrap master_content from master_index")
                except Exception as exc:
                    print(f"[delete] WARN: bootstrap from master_index failed: {exc}")

        # 2차: 그래도 비어 있으면, 최후 수단으로 rebuild_master() 사용
        if not html.strip():
            try:
                rb = self.rebuild_master()
                print(
                    f"[delete] fallback rebuild_master used: "
                    f"added={rb.get('added') if isinstance(rb, dict) else '??'}"
                )
                html = self._read(master_content)
            except Exception as exc:
                print(f"[delete] WARN: rebuild_master fallback failed: {exc}")

        # 3차: 그래도 비어 있으면 진짜 에러
        if not html.strip():
            return {
                "ok": False,
                "error": "master_content.html이 비어 있거나 존재하지 않습니다.",
            }

        soup = BeautifulSoup(html, "html.parser")
        target = soup.select_one(f'div.card[data-card-id="{card_id}"]')
        if target is None:
            return {
                "ok": False,
                "error": f"data-card-id={card_id} 카드를 찾을 수 없습니다.",
            }

        resource_dir = self._p_resource_dir()
        folder_name: Optional[str] = None
        errors: List[str] = []

        # 1) ID 레지스트리에서 card_id 기준으로 폴더명 조회(우선)
        try:
            entry = self._registry.find_by_card_id(card_id)
        except Exception as exc:
            entry = None
            msg = f"레지스트리 조회 실패(id={card_id}): {exc}"
            print(f"[delete] {msg}")
            errors.append(msg)
        else:
            if entry and entry.get("folder"):
                folder_name = (entry.get("folder") or "").strip()

        # 2) 레지스트리에서 찾지 못했다면 .suksukidx.id → card_id 역매핑으로 폴더명 찾기(폴백)
        if not folder_name:
            try:
                folder_id_map = ensure_card_ids(resource_dir)
            except Exception as exc:
                folder_id_map = {}
                print(
                    f"[delete] WARN: ensure_card_ids failed in delete_card_by_id: {exc}"
                )

            if folder_id_map:
                id_to_folder = {v: k for k, v in folder_id_map.items()}
                folder_name = id_to_folder.get(card_id)

        # 3) 그래도 폴더명을 찾지 못했다면 DOM 메타에서 폴더 후보 추출(최종 폴백)
        if not folder_name:
            h = target.select_one(".card-head h2") or target.find("h2")
            title = (h.get_text(strip=True) if h else "").strip()
            data_card = (target.get("data-card") or "").strip()
            data_folder = (target.get("data-folder") or "").strip()
            for cand in (data_card, data_folder, title):
                if cand:
                    folder_name = cand
                    break

        deleted_folder = False
        removed_from_master = False

        # 4) 파일시스템 폴더 삭제
        if folder_name:
            folder_path = resource_dir / folder_name
            try:
                if folder_path.exists() and folder_path.is_dir():
                    shutil.rmtree(folder_path)
                    deleted_folder = True
                else:
                    print(
                        f"[delete] WARN: folder not found or not a dir: {folder_path}"
                    )
            except Exception as exc:
                msg = f"폴더 삭제 실패: {exc}"
                print(f"[delete] {msg}")
                errors.append(msg)
        else:
            msg = "폴더명을 결정할 수 없어 파일시스템 삭제를 건너뜁니다."
            print(f"[delete] {msg}")
            errors.append(msg)

        # 5) master_content에서 카드 블록 제거
        try:
            target.decompose()
            self._write(master_content, str(soup))
            removed_from_master = True
        except Exception as exc:
            msg = f"master_content 카드 제거/저장 실패: {exc}"
            print(f"[delete] {msg}")
            errors.append(msg)

        # 6) master_index / child index 재빌드
        push_ok = True
        try:
            self._push_master_to_resource()
        except Exception as exc:
            push_ok = False
            msg = f"인덱스 재생성(_push_master_to_resource) 실패: {exc}"
            print(f"[delete] {msg}")
            errors.append(msg)

        # 7) 레지스트리에서 이 card_id 제거 (master에서 제거된 경우에만)
        try:
            if removed_from_master:
                removed_reg = self._registry.remove_by_card_id(card_id)
                if removed_reg:
                    print(f"[registry] removed entry for id={card_id}")
        except Exception as exc:
            msg = f"레지스트리 정리 실패(id={card_id}): {exc}"
            print(f"[registry] {msg}")
            errors.append(msg)

        ok = removed_from_master and push_ok and not errors
        result: Dict[str, Any] = {
            "ok": bool(ok),
            "card_id": card_id,
            "folder": folder_name,
            "removed_from_master": removed_from_master,
            "deleted_folder": deleted_folder,
            "pushOk": push_ok,
        }
        if errors:
            result["errors"] = errors
        return result

    # ---- ID 레지스트리 수동 갱신 헬퍼 ----
    def refresh_id_registry(self) -> Dict[str, Any]:
        """
        외부(예: 디버깅용)에서 수동으로 레지스트리를 재구성할 때 사용할 헬퍼.
        - master_content.html의 최신 상태를 기준으로
          backend/.suksukidx.registry.json을 재구성한다.
        """
        return self._registry.bootstrap_from_master(self._p_master_content())

    # ---- 썸네일 1건 ----
    def refresh_thumb(self, folder_name: str, width: int = 640) -> Dict[str, Any]:
        folder_path = self._p_resource_dir() / folder_name
        thumbs_dir = folder_path / "thumbs"
        try:
            if not folder_path.exists() or not folder_path.is_dir():
                return {
                    "ok": False,
                    "error": f"폴더가 존재하지 않습니다: {folder_name}",
                }

            if thumbs_dir.exists() and thumbs_dir.is_file():
                return {
                    "ok": False,
                    "error": f"'thumbs' 경로가 파일입니다: {thumbs_dir}. 폴더로 복구해 주세요.",
                }

            # 썸네일 파일 경로 계산(폴더 이름 기반 safe name)
            try:
                from .thumbs import _safe_name as _thumb_safe_name
            except Exception:
                from thumbs import _safe_name as _thumb_safe_name

            safe_name = _thumb_safe_name(folder_name)
            thumb_file = thumbs_dir / f"{safe_name}.jpg"

            # 폴더 ↔ 카드 ID 매핑(성공/실패 모두에서 사용)
            try:
                folder_id_map = ensure_card_ids(self._p_resource_dir())
            except Exception as exc:
                folder_id_map = {}
                print(f"[thumb] WARN: ensure_card_ids failed in refresh_thumb: {exc}")

            card_id = folder_id_map.get(folder_name)

            ok, src = make_thumbnail_for_folder(folder_path, max_width=width)

            if ok:
                # 성공: registry에 thumb_source 기록
                if card_id:
                    try:
                        self._registry.upsert_item(
                            card_id=card_id,
                            folder=folder_name,
                            thumb_source=src,
                        )
                    except Exception as exc:
                        print(
                            f"[thumb] WARN: registry update failed for {folder_name}: {exc}"
                        )
                return {
                    "ok": True,
                    "source": src,
                    "source_type": src,
                }

            # === ok=False 케이스 ===
            # src == None  → 캡처 가능한 소스가 전혀 없음(이미지/PDF/VIDEO 모두 X)
            # src != None  → 포맷 문제, 권한 문제 등 "진짜 에러"

            thumb_deleted = False
            if thumb_file.exists():
                try:
                    thumb_file.unlink()
                    thumb_deleted = True
                    print(
                        f"[thumb] removed thumb for '{folder_name}' (no source or error): {thumb_file}"
                    )
                except Exception as exc:
                    print(
                        f"[thumb] WARN: failed to delete thumb for {folder_name}: {exc}"
                    )

            # 레지스트리에서도 thumb_source 정리
            if card_id:
                try:
                    self._registry.upsert_item(
                        card_id=card_id,
                        folder=folder_name,
                        thumb_source=None,
                    )
                except Exception as exc:
                    print(
                        f"[thumb] WARN: registry update(clear) failed for {folder_name}: {exc}"
                    )

            # 1) 캡처 후보 자체가 없는 경우(src is None)
            #    → 정상적인 "제거" 케이스로 간주: 오류 아님
            if src is None:
                return {
                    "ok": True,
                    "source": None,
                    "source_type": None,
                    "deleted": thumb_deleted,
                }
            # 2) 캡처 후보는 있었지만, 필수 도구(ffmpeg/poppler)가 없어서 실패한 경우
            #    → 이것도 "조용한 스킵"으로 처리 (에러 X, 썸네일만 제거되었을 수 있음)
            if src == "video" and not has_ffmpeg():
                return {
                    "ok": True,
                    "source": None,
                    "source_type": None,
                    "deleted": thumb_deleted,
                }

            if src == "pdf" and not has_poppler():
                return {
                    "ok": True,
                    "source": None,
                    "source_type": None,
                    "deleted": thumb_deleted,
                }

            # 3) 여기까지 왔다면 도구는 있는데, 실제 변환이 실패한 "진짜 에러"
            msg = "썸네일 생성 실패(포맷 미지원 또는 권한 문제)"
            if thumb_deleted:
                msg += " — 기존 썸네일을 삭제했습니다."

            result: Dict[str, Any] = {
                "ok": False,
                "error": msg,
                "source_type": src,
            }
            if thumb_deleted:
                result["deleted"] = True
            return result

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    # --- Diff & Dry-run ---
    def diff_and_report(self, *, include_thumbs: bool = True) -> dict:
        """
        파일시스템 vs master_content/master_index 의 차이를 계산해
        드라이런 리포트를 반환한다. 실제 삭제/수정은 하지 않는다.
        """
        reporter = DiffReporter(
            resource_root=self._p_resource_dir(),
            master_content_path=self._p_master_content(),
            master_index_path=self._p_master_index(),
            check_thumbs=include_thumbs,
        )
        report = reporter.make_report()
        try:
            summary = report.summary or {}
            print(
                "[prune] DRY-RUN: "
                f"fs={summary.get('fs_slugs')} "
                f"master={summary.get('master_content_slugs')} "
                f"index={summary.get('master_index_slugs')}"
            )
            print(
                "[prune] DRY-RUN: "
                f"missing_in_fs={len(report.folders_missing_in_fs or [])} "
                f"child_missing={len(report.child_indexes_missing or [])} "
                f"orphans_in_master_only={len(report.orphans_in_master_index_only or [])} "
                f"thumbs_orphans={len(report.thumbs_orphans or [])}"
            )
        except Exception:
            pass
        return report.to_dict()

    def prune_apply(
        self, report: Optional[PruneReport] = None, delete_thumbs: bool = False
    ) -> Dict[str, Any]:
        """
        PruneReport를 실제로 반영한다.
        - master_content: folders_missing_in_fs 제거
        - child index   : 누락분 생성
        - master_index  : master_content 기준 재렌더
        - thumbs        : 옵션 시 고아 파일 삭제
        """
        if report is None:
            report = DiffReporter(
                resource_root=self._p_resource_dir(),
                master_content_path=self._p_master_content(),
                master_index_path=self._p_master_index(),
            ).make_report()
        applier = PruneApplier(
            resource_root=self._p_resource_dir(),
            master_content_path=self._p_master_content(),
            master_index_path=self._p_master_index(),
            delete_thumbs=delete_thumbs,
        )
        result = applier.apply(report)
        try:
            print(
                "[prune] APPLY: "
                f"removed_from_master={result.get('removed_from_master', 0)} "
                f"child_built={result.get('child_built', 0)} "
                f"thumbs_deleted={result.get('thumbs_deleted', 0)} "
                f"delete_thumbs={delete_thumbs}"
            )
        except Exception:
            pass
        return result
