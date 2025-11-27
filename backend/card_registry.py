from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json
from datetime import datetime

try:
    from .fsutil import atomic_write_text
except Exception:
    from fsutil import atomic_write_text

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None


class CardRegistry:
    """
    카드 ID ↔ 폴더 매핑 및 관련 메타를 관리하는 레지스트리.

    - registry_path: backend/.suksukidx.registry.json
    - resource_dir : resource/ 루트
    """

    def __init__(self, registry_path: Union[str, Path], resource_dir: Union[str, Path]):
        self._registry_path = Path(registry_path)
        self._resource_dir = Path(resource_dir)

    # ---- 내부 유틸 ----

    def _empty(self) -> Dict[str, Any]:
        return {"version": 1, "items": []}

    # ---- 기본 IO ----

    def load(self) -> Dict[str, Any]:
        """
        레지스트리 JSON을 읽어 Dict 형태로 반환한다.
        문제가 있으면 기본 구조를 반환한다.
        """
        path = self._registry_path
        if not path.exists():
            return self._empty()

        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                return self._empty()
            data = json.loads(text)
            if not isinstance(data, dict):
                return self._empty()
            if "version" not in data:
                data["version"] = 1
            if "items" not in data or not isinstance(data["items"], list):
                data["items"] = []
            return data
        except Exception as exc:
            print(f"[registry] load failed: {exc}")
            return self._empty()

    def save(self, data: Dict[str, Any]) -> None:
        """
        레지스트리를 디스크에 저장한다.
        atomic_write_text를 사용해 부분 손상을 방지한다.
        """
        if not isinstance(data, dict):
            data = self._empty()
        if "version" not in data:
            data["version"] = 1
        if "items" not in data or not isinstance(data["items"], list):
            data["items"] = []

        path = self._registry_path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = json.dumps(data, ensure_ascii=False, indent=2)
            atomic_write_text(str(path), text, encoding="utf-8")
        except Exception as exc:
            print(f"[registry] save failed: {exc}")

    def items(self) -> List[Dict[str, Any]]:
        data = self.load()
        items = data.get("items")
        if not isinstance(items, list):
            return []
        return items

    # ---- 조회/갱신 ----

    def find_by_card_id(self, card_id: str) -> Optional[Dict[str, Any]]:
        """
        card_id(=UUID)로 레지스트리 한 줄 찾기.
        """
        for item in self.items():
            if item.get("id") == card_id:
                return dict(item)
        return None

    def find_by_folder(self, folder: str) -> Optional[Dict[str, Any]]:
        """
        folder(폴더 경로/이름)로 레지스트리 한 줄 찾기.
        """
        folder = (folder or "").strip()
        if not folder:
            return None
        for item in self.items():
            if (item.get("folder") or "").strip() == folder:
                return dict(item)
        return None

    def upsert_item(
        self,
        *,
        card_id: str,
        folder: Optional[str] = None,
        title: Optional[str] = None,
        created_at: Optional[str] = None,
        hidden: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        주어진 card_id에 대해 레지스트리 아이템을 생성/갱신.

        - card_id 는 필수
        - folder/title/created_at/hidden 은 주어진 값만 덮어씀
        - created_at 은 기존 값이 없을 때만 세팅(이미 있으면 유지)
        """
        data = self.load()
        items = data.get("items")
        if not isinstance(items, list):
            items = []

        item = None
        for it in items:
            if it.get("id") == card_id:
                item = it
                break

        if item is None:
            item = {"id": card_id}
            items.append(item)

        if folder is not None:
            item["folder"] = folder
        if title is not None:
            item["title"] = title

        if not item.get("created_at") and created_at is not None:
            item["created_at"] = created_at

        if hidden is not None:
            item["hidden"] = bool(hidden)

        data["items"] = items
        self.save(data)
        return item

    def remove_by_card_id(self, card_id: str) -> bool:
        """
        card_id 로 레지스트리에서 항목 제거.
        실제로 삭제되면 True, 없으면 False.
        """
        data = self.load()
        items = data.get("items")
        if not isinstance(items, list):
            return False

        new_items: List[Dict[str, Any]] = [
            it for it in items if it.get("id") != card_id
        ]
        if len(new_items) == len(items):
            return False

        data["items"] = new_items
        self.save(data)
        return True

    def prune_missing_folders(self) -> int:
        """
        resource/ 에서 사라진 폴더를 가진 레지스트리 항목 정리.
        반환값: 제거된 항목 수
        """
        data = self.load()
        items = data.get("items")
        if not isinstance(items, list) or not items:
            return 0

        kept: List[Dict[str, Any]] = []
        removed = 0
        for it in items:
            folder = (it.get("folder") or "").strip()
            if folder and not (self._resource_dir / folder).is_dir():
                removed += 1
            else:
                kept.append(it)

        if removed:
            data["items"] = kept
            self.save(data)
        return removed

    # ---- master_content 기반 부트스트랩 ----

    def bootstrap_from_master(
        self, master_content_path: Union[str, Path]
    ) -> Dict[str, Any]:
        """
        master_content.html 기반으로 ID 레지스트리를 재구성한다.

        - master_content의 <div class="card">를 스캔해서
          id / folder / title / hidden / order 정보를 추출
        - 기존 레지스트리 내용을 id 기준으로 upsert
        - master_content에 더 이상 존재하지 않는 id는 그대로 두되
          나중에 prune 단계에서 정리할 수 있도록 남겨둔다.
        - 실제 저장까지 수행하고, 최종 데이터를 반환한다.
        """
        master_path = Path(master_content_path)
        if not master_path.exists():
            data = self._empty()
            self.save(data)
            return data

        try:
            html = master_path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"[registry] bootstrap: read master_content failed: {exc}")
            return self.load()

        if not html.strip():
            data = self._empty()
            self.save(data)
            return data

        if BeautifulSoup is None:
            print("[registry] bootstrap: BeautifulSoup not available, skip")
            return self.load()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all("div", class_="card")

        reg = self.load()
        items_by_id: Dict[str, Dict[str, Any]] = {}
        for item in reg.get("items", []):
            iid = item.get("id")
            if iid:
                items_by_id[iid] = dict(item)

        for card_div in cards:
            card_id = (card_div.get("data-card-id") or "").strip()
            if not card_id:
                title_el = card_div.find("h2")
                title_txt = (title_el.get_text(strip=True) if title_el else "").strip()
                print(
                    f"[registry] bootstrap: skip card without id (title='{title_txt}')"
                )
                continue

            folder = (card_div.get("data-card") or "").strip()

            title_el = card_div.find("h2")
            title = (title_el.get_text(strip=True) if title_el else "").strip()

            hidden_attr = (card_div.get("data-hidden") or "").strip().lower()
            classes = card_div.get("class") or []
            hidden = hidden_attr == "true" or ("is-hidden" in classes)

            order_val = card_div.get("data-order")
            try:
                order = int(order_val) if order_val is not None else None
            except ValueError:
                order = None

            item = items_by_id.get(card_id, {})
            item.update(
                {
                    "id": card_id,
                    "folder": folder or item.get("folder"),
                    "title": title or item.get("title"),
                    "hidden": hidden,
                }
            )
            if order is not None:
                item["order"] = order

            items_by_id[card_id] = item

        new_items = list(items_by_id.values())
        data = {
            "version": reg.get("version", 1),
            "items": new_items,
        }
        self.save(data)
        print(f"[registry] bootstrap: synced items={len(new_items)}")
        return data
