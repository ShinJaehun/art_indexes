from __future__ import annotations
from pathlib import Path
import subprocess, sys, shlex
import tempfile
import re, unicodedata
from io import BytesIO
import os

try:
    from .fsutil import atomic_write_bytes
except ImportError:  # 스크립트 모드 대비
    from fsutil import atomic_write_bytes

# ANNO: Windows 배포를 전제로 exe 동봉 경로를 우선 탐색하되, PATH에도 의존 가능.
BASE_DIR = Path(__file__).parent
BIN_DIR = BASE_DIR / "bin"
FFMPEG_EXE = BIN_DIR / "ffmpeg.exe"
PDFTOPPM_EXE = BIN_DIR / "poppler" / "pdftoppm.exe"  # bin/poppler
PDFINFO_EXE = BIN_DIR / "poppler" / "pdfinfo.exe"  # 페이지 수 조회용


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """
    모든 외부 도구 호출의 출력은 바이너리로 받고, UTF-8로 디코드(errors='ignore').
    - Windows 로케일(cp949)에서도 안전
    - 한글/이모지 섞여도 예외 없이 디코드
    """
    try:
        p = subprocess.run(cmd, capture_output=True, text=False, shell=False)
        out = (p.stdout or b"").decode("utf-8", errors="ignore")
        err = (p.stderr or b"").decode("utf-8", errors="ignore")
        return p.returncode, out, err
    except FileNotFoundError as e:
        return 127, "", f"FileNotFoundError: {e}"
    except Exception as e:
        return 1, "", f"Exception: {e}"


def _safe_name(name: str) -> str:
    # 폴더 → 썸네일 파일명 규칙: 공백은 _ 로, 금지문자는 _ 로
    # 유니코드 표준화(NFKC)로 보기엔 공백인데 다른 문자 문제 완화
    name = unicodedata.normalize("NFKC", name)
    # 모든 공백류(스페이스, 탭, NBSP, 얇은공백 등)를 '_'로
    name = re.sub(r"[\s\u00A0\u202F\u2009\u2007\u2060]+", "_", name)
    out = []
    for c in name:
        if c in r'\/:*?"<>|':
            out.append("_")
        else:
            out.append(c)
    return "".join(out)


def _which(exe_path: Path, fallback: str) -> str:
    """
    exe_path가 존재하면 그 절대경로, 아니면 fallback 이름 그대로 반환.
    (PATH 상에 있으면 시스템이 실행)
    """
    return str(exe_path) if exe_path.exists() else fallback


def _ascii_tmp_prefix(out_jpg: Path) -> tuple[Path, Path]:
    r"""
    ASCII 전용 임시 디렉터리에 파일 prefix를 만든다.
    반환: (tmp_dir, tmp_prefix)
    예) C:\Users\<me>\AppData\Local\Temp\pdfthumb_tmp\out_temp_pdfthumb
    """
    base_tmp = Path(tempfile.gettempdir()) / "pdfthumb_tmp"
    base_tmp.mkdir(parents=True, exist_ok=True)
    tmp_prefix = base_tmp / "out_temp_pdfthumb"
    return base_tmp, tmp_prefix


def _cleanup_tmp_dir(tmp_dir: Path):
    try:
        # 너무 자주 지우면 경쟁조건 날 수 있으니, 파일만 지우고 폴더는 남겨도 OK
        for p in tmp_dir.glob("out_temp_pdfthumb*"):
            p.unlink(missing_ok=True)
    except Exception:
        pass


def _pdf_num_pages(pdf_path: Path) -> int | None:
    pdfinfo = _which(PDFINFO_EXE, "pdfinfo")
    try:
        # 강제 UTF-8 + 에러 무시 (Windows cp949 문제 회피)
        p = subprocess.run(
            [pdfinfo, str(pdf_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            shell=False,
        )
        if p.returncode != 0:
            return None
        for line in (p.stdout or "").splitlines():
            if line.lower().startswith("pages:"):
                try:
                    return int(line.split(":")[1].strip())
                except Exception:
                    return None
        return None
    except Exception:
        return None


def make_pdf_thumb(pdf_path: Path, out_jpg: Path, dpi: int = 144) -> bool:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)

    pdftoppm = _which(PDFTOPPM_EXE, "pdftoppm")

    # 중앙 페이지 계산(1-based)
    n_pages = _pdf_num_pages(pdf_path)
    mid_page = 1 if not n_pages or n_pages <= 0 else max(1, (n_pages + 1) // 2)

    # ASCII-only 임시 폴더 사용
    tmp_dir, tmp_prefix = _ascii_tmp_prefix(out_jpg)

    cmd = [
        pdftoppm,
        "-singlefile",
        "-f",
        str(mid_page),
        "-l",
        str(mid_page),
        "-jpeg",
        "-r",
        str(dpi),
        str(pdf_path),
        str(tmp_prefix),
    ]

    rc, _out, err = _run(cmd)
    if rc != 0:
        # ▼ 추가: 암호 문서면 조용히 스킵(로그만 친절히 남김)
        if "Incorrect password" in err or "password" in err.lower():
            print(
                f"[thumb] PDF is password-protected, skip: {pdf_path}", file=sys.stderr
            )
        else:
            print(
                f"[thumb] PDF->JPG FAIL rc={rc}\nCMD: {shlex.join(cmd)}\nSTDERR:\n{err}",
                file=sys.stderr,
            )
        _cleanup_tmp_dir(tmp_dir)
        return False

    # 결과 후보
    cand1 = tmp_prefix.with_suffix(".jpg")
    cand2 = tmp_prefix.with_name(tmp_prefix.name + f"-{mid_page}").with_suffix(".jpg")
    made = cand1 if cand1.exists() else (cand2 if cand2.exists() else None)
    if not made:
        alts = list(tmp_dir.glob(tmp_prefix.name + "*.jpg"))
        made = alts[0] if alts else None
        if not made:
            print(f"[thumb] PDF->JPG MISSING (tmp in {tmp_dir})", file=sys.stderr)
            _cleanup_tmp_dir(tmp_dir)
            return False

    # temp 파일을 메모리로 읽어 원자 저장
    try:
        data = Path(made).read_bytes()
        atomic_write_bytes(str(out_jpg), data)
        print(f"[thumb] PDF->JPG OK (mid={mid_page}): {out_jpg}")
        return True
    finally:
        _cleanup_tmp_dir(tmp_dir)


def make_video_thumb(video_path: Path, out_jpg: Path, width: int = 640) -> bool:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    exe = FFMPEG_EXE if FFMPEG_EXE.exists() else Path("ffmpeg")
    vf = f"thumbnail,scale={width}:-1"

    # 임시 파일에 먼저 생성(어떤 드라이브여도 OK) → 메모리 로드 → atomic_write_bytes
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="vidthumb_", suffix=".jpg")
    os_tmp_path = Path(tmp_path)

    # ffmpeg 실행 전 FD 닫기(Windows 파일 잠금 방지)
    try:
        os.close(tmp_fd)
    except Exception:
        pass

    try:
        cmd = [
            str(exe),
            "-y",
            "-ss",
            "00:00:10",  # P5-썸네일 v2: 10초 지점 캡처
            "-i",
            str(video_path),
            "-vframes",
            "1",
            "-vf",
            vf,
            str(os_tmp_path),
        ]
        rc, out, err = _run(cmd)
        if rc != 0:
            print(
                f"[thumb] VIDEO->JPG FAIL rc={rc}\nCMD: {shlex.join(cmd)}\nSTDERR:\n{err}",
                file=sys.stderr,
            )
            return False

        if not os_tmp_path.exists():
            print(f"[thumb] VIDEO->JPG MISSING: {out_jpg}", file=sys.stderr)
            return False

        data = os_tmp_path.read_bytes()
        atomic_write_bytes(str(out_jpg), data)
        print(f"[thumb] VIDEO->JPG OK: {out_jpg}")
        return True
    finally:
        try:
            os_tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _find_capture_candidate(folder: Path) -> tuple[str | None, Path | None]:
    """
    폴더 내 썸네일 캡처 후보 탐색:
      1) 이미지(.png/.jpg/.jpeg/.webp)
      2) PDF
      3) MP4
    반환: (kind, Path)  예) ("image", Path(...)) / (None, None)
    """
    # 1) 대표 이미지
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        img = next(folder.glob(f"*{ext}"), None)
        if img:
            return "image", img

    # 2) PDF
    pdf = next(folder.glob("*.pdf"), None)
    if pdf:
        return "pdf", pdf

    # 3) VIDEO
    mp4 = next(folder.glob("*.mp4"), None)
    if mp4:
        return "video", mp4

    return None, None


def make_thumbnail_for_folder(
    folder: Path, max_width: int = 640
) -> tuple[bool, str | None]:
    """
    폴더 하나에 대해 썸네일을 한 번 생성/갱신한다.
    - 캡처 대상이 없으면 아무 작업도 하지 않고 (False, None) 반환
    - 성공 시 (True, "image"|"pdf"|"video") 반환

    ⚠️ 기존 썸네일 삭제는 여기서 하지 않는다.
       - sync 전체 스캔: scan_and_make_thumbs()
       - 개별 강제 갱신: MasterApi.refresh_thumb()
       쪽에서 정책에 따라 삭제 처리.
    """
    kind, src = _find_capture_candidate(folder)
    if not src:
        print(f"[thumb] SKIP (no source): {folder.name}")
        return False, None

    out = folder / "thumbs" / f"{_safe_name(folder.name)}.jpg"

    if kind == "image":
        try:
            from PIL import Image

            out.parent.mkdir(exist_ok=True)

            with Image.open(src) as im:
                w, h = im.size
                if w > max_width:
                    im = im.resize((max_width, int(h * (max_width / w))), Image.LANCZOS)
                buf = BytesIO()
                im.convert("RGB").save(buf, "JPEG", quality=88, optimize=True)
                atomic_write_bytes(str(out), buf.getvalue())

            print(f"[thumb] OK (image): {out}")
            return True, "image"
        except Exception as e:
            print(f"[thumb] image resize FAIL: {e}", file=sys.stderr)
            return False, "image"

    if kind == "pdf":
        if make_pdf_thumb(src, out):
            return True, "pdf"
        return False, "pdf"

    if kind == "video":
        if make_video_thumb(src, out, width=max_width):
            return True, "video"
        return False, "video"

    # 이론상 도달하지 않음
    print(f"[thumb] FAIL (unknown kind={kind}): {folder.name}", file=sys.stderr)
    return False, kind


def _iter_content_folders(resource_dir: Path):
    """
    리소스 전체 썸네일 스캔/생성 (HTML 생성 없음)
    """
    for p in sorted(Path(resource_dir).iterdir(), key=lambda x: x.name):
        if not p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        if p.name.lower() == "thumbs":
            continue
        yield p


def scan_and_make_thumbs(
    resource_dir: Path, refresh: bool = True, width: int = 640
) -> bool:
    """
    resource/<폴더>들을 훑어 썸네일만 생성/갱신한다.
    - refresh=False 이면:
        * 캡처 후보가 없고, 기존 썸네일이 있으면 → 썸네일 삭제
        * 캡처 후보는 있는데 썸네일이 이미 있으면 → 그대로 유지(성능 세이브)
        * 썸네일이 없고 캡처 후보가 있으면 → 1회 생성
    - refresh=True 이면:
        * 캡처 후보가 있으면 항상 새로 캡처(기존 썸네일 덮어쓰기)
        * 캡처 후보가 없으면 기존 썸네일만 삭제
    """
    resource_dir = Path(resource_dir)
    any_error = False

    for folder in _iter_content_folders(resource_dir):
        try:
            kind, src = _find_capture_candidate(folder)
            safe_name = _safe_name(folder.name)
            thumb_file = folder / "thumbs" / f"{safe_name}.jpg"

            # 1) 캡처 후보 없음 → 기존 썸네일이 있다면 삭제
            if not src:
                if thumb_file.exists():
                    try:
                        thumb_file.unlink()
                        print(f"[thumb] removed orphan thumb (no source): {thumb_file}")
                    except Exception as e:
                        print(
                            f"[thumb] WARN: failed to remove orphan thumb {thumb_file}: {e}",
                            file=sys.stderr,
                        )
                        any_error = True
                continue

            # 2) 후보는 있는데, refresh=False 이고 썸네일이 이미 있으면 → 그대로 유지
            if not refresh and thumb_file.exists():
                continue

            # 3) 이외의 경우에만 실제 썸네일 생성/갱신
            ok, _src = make_thumbnail_for_folder(folder, max_width=width)
            # ok=False(변환 실패 등)는 전체 스캔 실패로 보지 않고 넘어감
        except Exception as e:
            print(f"[thumb] ERROR in {folder.name}: {e}", file=sys.stderr)
            any_error = True

    return not any_error
