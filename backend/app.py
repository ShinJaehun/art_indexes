from pathlib import Path
import sys
import webview

try:
    from .api import MasterApi
except ImportError:
    from api import MasterApi

# ANNO: 데스크톱 전용 pywebview 앱 엔트리포인트.
# - base_dir: 개발 환경은 backend의 부모(프로젝트 루트), 배포(EXE) 환경은 실행 파일 위치.
# - 시작 시 index.html 존재 가드 + resource 폴더 보장 + get_master() 워밍업.
# - 디버그 로그로 base_dir / url을 한 번 출력.


def _resolve_base_dir() -> Path:
    """개발/배포 모두에서 일관된 base_dir 결정"""
    if getattr(sys, "frozen", False):
        # PyInstaller 등으로 묶인 실행 파일 환경
        return Path(sys.executable).resolve().parent
    # 개발 환경: backend/의 부모(프로젝트 루트)
    return Path(__file__).resolve().parents[1]


def main():
    base_dir = _resolve_base_dir()
    index_path = base_dir / "index.html"

    # 1) 필수 파일 존재 가드
    if not index_path.exists():
        print(f"[app] ERROR: index.html not found at {index_path}")
        raise SystemExit(1)

    # 2) 리소스 폴더 초기 보장
    resource_dir = base_dir / "resource"
    resource_dir.mkdir(parents=True, exist_ok=True)

    # API 주입
    api = MasterApi(base_dir=base_dir)

    # 3) 초기 워밍업: master_content 초기화/프리뷰 썸네일 주입
    try:
        _ = api.get_master()
    except Exception as e:
        print(f"[app] WARN: get_master() failed: {e}")

    # 4) 디버그 로그
    print(f"[app] base_dir={base_dir}")
    print(f"[app] url={index_path.as_uri()}")

    # 창 생성
    window = webview.create_window(
        title="미술 수업 자료 Index",
        url=index_path.as_uri(),
        js_api=api,
        width=1100,
        height=800,
        resizable=True,
    )

    # webview.start()
    webview.start(debug=True)


if __name__ == "__main__":
    main()
