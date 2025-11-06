from pathlib import Path

# 프로젝트 기본 디렉토리
BACKEND_DIR = "backend"
RESOURCE_DIR = "resource"

# 핵심 파일명
MASTER_INDEX = "master_index.html"
MASTER_CONTENT = "master_content.html"

# 기본 락 파일
DEFAULT_LOCK_PATH = Path(BACKEND_DIR) / ".sync.lock"

# CSS 배포 관련
PUBLISH_CSS = "backend/ui/publish.css"
CSS_PREFIX = "master"
