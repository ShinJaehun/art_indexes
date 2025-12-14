from pathlib import Path
import sys
import webview
from typing import Optional

from backend.api import MasterApi

from backend.constants import BACKEND_DIR, RESOURCE_DIR

def _resolve_base_dir() -> Path:
    """
    Data root:
    - dev: project root
    - PyInstaller (onedir/onefile): folder containing the executable
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _resolve_index_path(base_dir: Path) -> Optional[Path]:
    candidates = [
        # PyInstaller onedir(6.x): <exe_dir>/_internal/backend/ui/index.html
        base_dir / "_internal" / BACKEND_DIR / "ui" / "index.html",
        # dev 배치: <project_root>/backend/ui/index.html
        base_dir / BACKEND_DIR / "ui" / "index.html",
        base_dir / "index.html",  # (구버전 폴백)
    ]
    for p in candidates:
        if p is not None and p.exists():
            return p
    return None


def main():
    base_dir = _resolve_base_dir()
    index_path = _resolve_index_path(base_dir)
    if index_path is None:
        tried = [
            str(base_dir / "backend" / "ui" / "index.html"),
            str(base_dir / "_internal" / "backend" / "ui" / "index.html"),
            str(base_dir / "index.html"),
        ]
        if getattr(sys, "frozen", False):
            tried.append(str(Path(sys.executable).resolve().parent / BACKEND_DIR / "ui" / "index.html"))

        print("[app] ERROR: UI index.html not found. tried:\n  " + "\n  ".join(tried))
        raise SystemExit(1)

    # resource 폴더 보장
    resource_dir = base_dir / RESOURCE_DIR
    resource_dir.mkdir(parents=True, exist_ok=True)

    # JS API 객체 준비
    api = MasterApi(base_dir=base_dir)

    # 창 먼저 생성 (중요)
    window = webview.create_window(
        title="쑥쑥인덱스",
        url=index_path.as_uri(),
        js_api=api,  # 여기에 먼저 주입
        width=1100,
        height=800,
        resizable=True,
    )

    # pywebview 시작 이후, JS에서 API 노출 확인 로그
    def on_start():
        try:
            window.evaluate_js(
                "console.log('API keys:', Object.keys(window.pywebview?.api || {}))"
            )
        except Exception:
            pass

    print(f"[app] base_dir={base_dir}")
    print(f"[app] url={index_path.as_uri()}")

    # 시작 (일부 구버전 백업: js_api 인자도 같이 전달)
    try:
        # webview.start(func=on_start, debug=True)
        webview.start(func=on_start, debug=False)
    except TypeError:
        webview.start(func=on_start, debug=True, js_api=api)


if __name__ == "__main__":
    main()
