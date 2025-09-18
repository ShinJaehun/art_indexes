from pathlib import Path
import subprocess
from html import escape
import sys
from thumbs import _safe_name  # ← 추가

# ANNO: 이 모듈의 역할
# - run_sync_all: 리소스 디렉토리(cwd)를 바꿔 'build_art_indexes.py'를 직접 실행한다.
#   * 외부 프로세스 호출(서브프로세스)이므로 실패/반환코드로만 성공여부를 판단한다.
# - rebuild_master_from_sources: resource/<폴더> 구조만을 읽어 순수 HTML 블록을 구성한다.
#   * 현재 구현은 .folder-actions(버튼)까지 포함해 "관리 UI를 가진 카드"를 생성한다.
#
# HAZARD(yesterday): rebuild_master_from_sources가 생성하는 블록은 버튼/편집 UI까지 포함한다.
# - 이 결과를 api.rebuild_master()가 master_content.html로 재주입하면, 저장물에 버튼이 남아 이후 중복 삽입/경계 붕괴를 유발한다.
# - 리팩토링 시 이 함수는 "콘텐츠만"(예: .inner) 또는 화이트리스트된 태그만 생성하도록 조정 필요. (지금은 주석만)


def run_sync_all(base_dir: Path, resource_dir: Path, thumb_width: int = 640) -> int:
    # ANNO: base_dir는 스크립트가 있는 루트(backend 옆), resource_dir는 실제 콘텐츠 폴더.
    script = base_dir / "build_art_indexes.py"
    if not script.exists():
        print("❌ build_art_indexes.py not found", file=sys.stderr)
        return 1
    # ANNO: resource_dir를 cwd로 설정하여 스크립트 내부의 CWD 기반 경로 탐지를 맞춘다.
    args = [
        sys.executable,
        str(script),
        "--refresh-thumbs",
        "--thumb-width",
        str(thumb_width),
    ]
    result = subprocess.run(args, cwd=str(resource_dir), text=True, shell=False)
    return result.returncode


def rebuild_master_from_sources(resource_dir: Path) -> str:
    # ANNO: resource/<폴더>들을 스캔해, 각 폴더 카드(.folder)를 조립한다.
    # HAZARD(yesterday): .folder-actions(편집/저장/썸네일) UI까지 함께 그려 넣는 구조 → 저장물 오염 위험.
    blocks = []
    for child in sorted(resource_dir.iterdir()):
        if not child.is_dir():
            continue
        title = child.name
        safe = _safe_name(title)
        thumb = child / "thumbs" / f"{safe}.jpg"

        # ANNO: 썸네일 존재 시에만 img 블록을 렌더링.
        thumb_html = (
            f"""
          <div class="thumb-wrap">
            <img class="thumb"
                 src="resource/{escape(title)}/thumbs/{escape(safe)}.jpg"
                 alt="썸네일" />
          </div>"""
            if thumb.exists()
            else """<div class="thumb-wrap"></div>"""
        )

        # HAZARD(yesterday): 아래 .folder-actions(버튼들)은 파일 저장물에 포함되면 안 된다(브라우저 UI에서만).
        block = f"""
        <div class="folder" data-folder="{escape(title)}">
          <div class="folder-head">
            <h2>{escape(title)}</h2>
            <div class="folder-actions">
              <button class="btn btnEditOne">편집</button>
              <button class="btn btnSaveOne" disabled>저장</button>
              <button class="btn btnThumb">썸네일 갱신</button>
            </div>
            {thumb_html}
          </div>
          <div class="inner">
            <!-- 편집 가능 영역 -->
          </div>
        </div>
        """
        blocks.append(block.strip())

    return "\n\n".join(blocks)
