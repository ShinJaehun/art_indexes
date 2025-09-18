from pathlib import Path
import webview
from api import MasterApi

# ANNO: 데스크톱 전용 pywebview 앱 엔트리포인트.
# - base_dir: backend/의 부모(프로젝트 루트)로 설정 → index.html, master_content.html, resource/ 등을 상대 경로로 참조.
# - url=index_path.as_uri(): 로컬 파일을 직접 띄운다.
# HAZARD: index.html 내에서 master_content.html을 로드/세이브하는 JS가 버튼을 DOM에 주입했다면,
#         저장 직전 반드시 UI 컨트롤 제거(clean) 루틴이 필요. (지금은 주석만)


def main():
    base_dir = Path(__file__).resolve().parents[1]
    index_path = base_dir / "index.html"
    api = MasterApi(base_dir=base_dir)

    window = webview.create_window(
        title="미술 수업 자료 Index",
        url=index_path.as_uri(),
        js_api=api,
        width=1100,
        height=800,
        resizable=True,
    )
    webview.start()


if __name__ == "__main__":
    main()
