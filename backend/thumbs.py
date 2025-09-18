from __future__ import annotations
from pathlib import Path
import subprocess, sys, shlex
import tempfile, os, shutil

# ANNO: Windows 배포를 전제로 exe 동봉 경로를 우선 탐색하되, PATH에도 의존 가능.
BASE_DIR = Path(__file__).parent
BIN_DIR = BASE_DIR / "bin"
FFMPEG_EXE = BIN_DIR / "ffmpeg.exe"
PDFTOPPM_EXE = (
    BIN_DIR / "poppler" / "pdftoppm.exe"
)  # ← poppler/bin 통째로 복사한 폴더 안
PDFINFO_EXE = BIN_DIR / "poppler" / "pdfinfo.exe"  # ← 페이지 수 조회용(있으면 사용)


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, shell=False)
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError as e:
        return 127, "", f"FileNotFoundError: {e}"
    except Exception as e:
        return 1, "", f"Exception: {e}"


def _safe_name(name: str) -> str:
    # 폴더 → 썸네일 파일명 규칙: 공백은 _ 로, 금지문자는 _ 로
    # HAZARD: build_art_indexes.safe_name과 규칙 차이 주의(일관화 필요). 지금은 변경하지 않음.
    out = []
    for c in name:
        if c in r'\\/:*?"<>|':
            out.append("_")
        elif c.isspace():
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
    예) C:\\Users\\<me>\\AppData\\Local\\Temp\\pdfthumb_tmp\\out_temp_pdfthumb
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
        # ✅ 강제 UTF-8 + 에러 무시 (Windows cp949 문제 회피)
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


# --- thumbs.py 내 기존 make_pdf_thumb(...) 함수만 아래 코드로 교체 ---
# ANNO: 실제로는 교체가 이루어진 상태로 보임. 여기서는 주석만.


def make_pdf_thumb(pdf_path: Path, out_jpg: Path, dpi: int = 144) -> bool:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)

    pdftoppm = _which(PDFTOPPM_EXE, "pdftoppm")

    # 중앙 페이지 계산(1-based)
    n_pages = _pdf_num_pages(pdf_path)
    mid_page = 1 if not n_pages or n_pages <= 0 else max(1, (n_pages + 1) // 2)

    # ✅ ASCII-only 임시 폴더 사용
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
        # 안전망
        alts = list(tmp_dir.glob(tmp_prefix.name + "*.jpg"))
        made = alts[0] if alts else None
        if not made:
            print(f"[thumb] PDF->JPG MISSING (tmp in {tmp_dir})", file=sys.stderr)
            _cleanup_tmp_dir(tmp_dir)
            return False

    try:
        Path(made).replace(out_jpg)
        print(f"[thumb] PDF->JPG OK (mid={mid_page}): {out_jpg}")
        return True
    finally:
        _cleanup_tmp_dir(tmp_dir)


def make_video_thumb(video_path: Path, out_jpg: Path, width: int = 640) -> bool:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    exe = FFMPEG_EXE if FFMPEG_EXE.exists() else Path("ffmpeg")
    vf = f"thumbnail,scale={width}:-1"
    cmd = [
        str(exe),
        "-y",
        "-ss",
        "00:00:01",  # 초반 검은 화면 회피
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-vf",
        vf,
        str(out_jpg),
    ]
    rc, out, err = _run(cmd)
    if rc != 0:
        print(
            f"[thumb] VIDEO->JPG FAIL rc={rc}\nCMD: {shlex.join(cmd)}\nSTDERR:\n{err}",
            file=sys.stderr,
        )
        return False

    ok = out_jpg.exists()
    print(
        f"[thumb] VIDEO->JPG OK: {out_jpg}"
        if ok
        else f"[thumb] VIDEO->JPG MISSING: {out_jpg}"
    )
    return ok


def make_thumbnail_for_folder(folder: Path, max_width: int = 640) -> bool:
    # 1) 대표 이미지
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        img = next(folder.glob(f"*{ext}"), None)
        if img:
            try:
                from PIL import Image

                out = folder / "thumbs" / f"{_safe_name(folder.name)}.jpg"
                out.parent.mkdir(exist_ok=True)
                with Image.open(img) as im:
                    w, h = im.size
                    if w > max_width:
                        im = im.resize((max_width, int(h * (max_width / w))))
                    im.convert("RGB").save(out, "JPEG", quality=88)
                print(f"[thumb] OK (image): {out}")
                return True
            except Exception as e:
                print(f"[thumb] image resize FAIL: {e}", file=sys.stderr)
            break

    # 2) PDF
    pdf = next(folder.glob("*.pdf"), None)
    if pdf:
        out = folder / "thumbs" / f"{_safe_name(folder.name)}.jpg"
        if make_pdf_thumb(pdf, out):
            return True

    # 3) VIDEO
    mp4 = next(folder.glob("*.mp4"), None)
    if mp4:
        out = folder / "thumbs" / f"{_safe_name(folder.name)}.jpg"
        if make_video_thumb(mp4, out, width=max_width):
            return True

    print(f"[thumb] SKIP (no source): {folder.name}")
    return False
