from pathlib import Path
import sys
import webview
from typing import Optional
from typing import Any
import os
import logging
from logging.handlers import RotatingFileHandler

from backend.api import MasterApi

from backend.constants import BACKEND_DIR, RESOURCE_DIR

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _show_error_box(title: str, message: str) -> None:
    """
    Windows: MessageBox로 안내
    (실패해도 무시하고 콘솔/로그로만 남겨도 되도록 설계)
    """
    try:
        import ctypes
        MB_OK = 0x0
        MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(None, message, title, MB_OK | MB_ICONERROR)
    except Exception:
        pass

def _is_protected_install_dir(base_dir: Path) -> bool:
    """
    B안: Program Files 같은 권한 제한 경로면 실행 차단.
    - 문자열 기반 1차 감지 + 실제 쓰기 테스트 2차 감지
    """
    s = str(base_dir).lower()
    if ("\\program files\\" in s) or ("\\program files (x86)\\" in s):
        return True
    # 2차: 쓰기 테스트(가장 확실)
    try:
        test = base_dir / ".suksukidx_write_test.tmp"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        return False
    except Exception:
        return True

class _StreamToLogger:
    """print()로 찍히는 stdout/stderr를 logger로 흡수."""
    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.level = level
        self._buf = ""

    def write(self, msg: str) -> int:
        if not msg:
            return 0
        self._buf += msg
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip()
            if line:
                self.logger.log(self.level, line)
        return len(msg)

    def flush(self) -> None:
        if self._buf.strip():
            self.logger.log(self.level, self._buf.strip())
        self._buf = ""

def _setup_logging(base_dir: Path) -> logging.Logger:
    logs_dir = base_dir / "logs"
    _ensure_dir(logs_dir)
    log_path = logs_dir / "suksukidx.log"

    logger = logging.getLogger("suksukidx")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # 핸들러 중복 방지(재실행/재주입 대비)
    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        fh = RotatingFileHandler(
            str(log_path),
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fmt = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    # stdout/stderr를 파일 로그로 흡수(콘솔 OFF 환경에서도 print 로그를 남기기 위함)
    sys.stdout = _StreamToLogger(logger, logging.INFO)   # type: ignore[assignment]
    sys.stderr = _StreamToLogger(logger, logging.ERROR)  # type: ignore[assignment]

    logger.info("[log] started (path=%s)", str(log_path))
    return logger


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

def _resolve_icon_path(base_dir: Path) -> Optional[Path]:
    candidates = [
        base_dir / "_internal" / BACKEND_DIR / "ui" / "suksukidx.ico",
        base_dir / BACKEND_DIR / "ui" / "suksukidx.ico",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def main():
    base_dir = _resolve_base_dir()
    logger = _setup_logging(base_dir)

    # logs/resource 루트 자동 생성
    resource_dir = base_dir / RESOURCE_DIR
    _ensure_dir(resource_dir)

    # Program Files 등 권한 제한 경로 감지 시 안내 후 차단/안전 종료 (B안)
    if getattr(sys, "frozen", False) and _is_protected_install_dir(base_dir):
        msg = (
            "쑥쑥인덱스는 'Program Files' 같은 권한 제한 폴더에서 실행할 수 없습니다.\n\n"
            "✅ 해결 방법:\n"
            "- suksukidx 폴더 전체를 바탕화면/문서/다운로드 같은 사용자 폴더로 옮긴 뒤 실행하세요.\n\n"
            f"현재 경로:\n{base_dir}"
        )
        logger.error("[guard] blocked in protected dir: %s", str(base_dir))
        _show_error_box("쑥쑥인덱스 실행 불가", msg)
        raise SystemExit(2)

    index_path = _resolve_index_path(base_dir)
    if index_path is None:
        tried = [
            str(base_dir / "backend" / "ui" / "index.html"),
            str(base_dir / "_internal" / "backend" / "ui" / "index.html"),
            str(base_dir / "index.html"),
        ]
        if getattr(sys, "frozen", False):
            tried.append(str(Path(sys.executable).resolve().parent / BACKEND_DIR / "ui" / "index.html"))

        logger.error("[app] UI index.html not found. tried:\n  %s", "\n  ".join(tried))
        raise SystemExit(1)

    # JS API 객체 준비
    api = MasterApi(base_dir=base_dir)

    icon_path = _resolve_icon_path(base_dir)
    if icon_path:
        logger.info("[app] icon=%s", str(icon_path))

    # 창 먼저 생성 (중요)
    # NOTE: 일부 pywebview 버전/백엔드에서 create_window(icon=...)를 지원하지 않음.
    # exe 아이콘은 PyInstaller(spec)로 처리하고, 런타임에서는 icon 인자를 넘기지 않는다.
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

    logger.info("[app] base_dir=%s", str(base_dir))
    logger.info("[app] url=%s", index_path.as_uri())

    # 시작 (일부 구버전 백업: js_api 인자도 같이 전달)
    try:
        # webview.start(func=on_start, debug=True)
        webview.start(func=on_start, debug=False)
    except TypeError:
        webview.start(func=on_start, debug=True, js_api=api)


if __name__ == "__main__":
    main()
