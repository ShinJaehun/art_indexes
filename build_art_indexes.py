#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
미술 수업 자료 인덱서 (build_art_indexes.py)

기능
- 각 하위 폴더에 index.html 생성/갱신
- master_index.html 재생성
- 썸네일 자동 생성 (우선순위: IMAGE → PDF → VIDEO)
  * PDF: 가운데(중간) 페이지 캡처 (PyMuPDF 우선, 없으면 pdftoppm 폴백)
  * VIDEO: 10초 지점 프레임 캡처 (ffmpeg)
  * IMAGE: 첫 이미지 리사이즈 + EXIF 회전/색공간 보정

의존성(선택)
- pillow, bs4, pymupdf(선택)
- ffmpeg (동영상), pdftoppm(poppler, PDF 폴백)

ANNO: 이 스크립트는 "예전 정상 동작" 버전으로 보이며, 현재 구조상
- 기존 master_index.html을 읽어 .folder 블록을 다시 소스로 삼는다.
- 따라서 master에 UI/버튼이 포함되어 있으면, 그 상태를 다시 하위 index.html로 흘려보낼 위험이 있다.

HAZARD(yesterday): master ↔ folder 간 양방향 의존(재귀 재생성) + 정규식 폴백은 아이템포턴시 붕괴를 초래할 수 있다.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List
import tempfile, os, shutil

# ANNO: 선택 의존성. 미설치 시 기능 축소(이미지/PDF 처리/DOM 파싱 등)로 폴백.
try:
    from PIL import Image, ImageOps, ImageFile

    ImageFile.LOAD_TRUNCATED_IMAGES = True
except Exception:
    Image = None
    ImageOps = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None


# -------- 상수/설정 --------
ROOT_MASTER = "master_index.html"
FOLDER_INDEX = "index.html"
THUMBS_DIR = "thumbs"

IMG_PATS = ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"]
PDF_PATS = ["*.pdf", "*.PDF"]
VID_PATS = ["*.mp4", "*.mov", "*.m4v", "*.avi", "*.MP4", "*.MOV", "*.M4V", "*.AVI"]


# -------- 유틸 --------
def safe_name(name: str) -> str:
    """파일명 안전용: 공백 등 최소 치환"""
    # HAZARD: thumbs._safe_name과 규칙이 다를 수 있음(금지문자 치환 범위 차이).
    #         썸네일 파일명/링크 불일치 가능성 → 규칙 통일 필요(지금은 주석만).
    return name.replace(" ", "_")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def list_folders_sorted(base: Path) -> List[Path]:
    items = []
    for p in base.iterdir():
        if not p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        if p.name == THUMBS_DIR:
            continue
        items.append(p)
    return sorted(items, key=lambda x: x.name)


def find_first(base: Path, patterns: List[str]) -> Optional[Path]:
    for pat in patterns:
        for p in base.glob(pat):
            if p.is_file():
                return p
    return None


def which_bin(*candidates: str) -> Optional[str]:
    for c in candidates:
        p = shutil.which(c)
        if p:
            return p
    return None


def find_ffmpeg() -> Optional[str]:
    # ANNO: 1) PATH → 2) 프로젝트 내 추정 경로.
    p = which_bin("ffmpeg")
    if p:
        return p
    # HAZARD: Windows 배포 경로가 바뀌면 아래 후보 경로들이 빗나갈 수 있음.
    here = Path.cwd()
    candidates = [
        here / "backend" / "bin" / "ffmpeg.exe",
        here.parent / "backend" / "bin" / "ffmpeg.exe",
        Path(__file__).resolve().parent / "backend" / "bin" / "ffmpeg.exe",
        Path(__file__).resolve().parent.parent / "backend" / "bin" / "ffmpeg.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def find_pdfinfo() -> Optional[str]:
    p = which_bin("pdfinfo")
    if p:
        return p
    here = Path.cwd()
    candidates = [
        here / "backend" / "bin" / "poppler" / "pdfinfo.exe",
        here.parent / "backend" / "bin" / "poppler" / "pdfinfo.exe",
        Path(__file__).resolve().parent / "backend" / "bin" / "poppler" / "pdfinfo.exe",
        Path(__file__).resolve().parent.parent
        / "backend"
        / "bin"
        / "poppler"
        / "pdfinfo.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def find_pdftoppm() -> Optional[str]:
    p = which_bin("pdftoppm")
    if p:
        return p
    here = Path.cwd()
    candidates = [
        here / "backend" / "bin" / "poppler" / "pdftoppm.exe",
        here.parent / "backend" / "bin" / "poppler" / "pdftoppm.exe",
        Path(__file__).resolve().parent
        / "backend"
        / "bin"
        / "poppler"
        / "pdftoppm.exe",
        Path(__file__).resolve().parent.parent
        / "backend"
        / "bin"
        / "poppler"
        / "pdftoppm.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


FFMPEG_BIN = find_ffmpeg()
PDFTOPPM_BIN = find_pdftoppm()
PDFINFO_BIN = find_pdfinfo()


# -------- 썸네일 생성 --------
def make_thumb_from_image(img_path: Path, out_path: Path, width: int) -> bool:
    if Image is None:
        return False
    try:
        img = Image.open(img_path)
        # EXIF 회전 보정
        if ImageOps is not None:
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
        # 색공간 보정
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")

        w, h = img.size
        if w > width:
            nh = int(h * (width / w))
            img = img.resize((width, nh), Image.LANCZOS)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, format="JPEG", quality=70, optimize=True)
        return True
    except Exception:
        # HAZARD: 실패 원인을 묵살 → 로깅 강화 여지. (지금은 주석만)
        return False


def make_thumb_from_video(video_path: Path, out_path: Path, width: int) -> bool:
    if FFMPEG_BIN is None:
        return False
    # ANNO: 임시 PNG 추출 후 Pillow 경로로 리사이즈/저장.
    tmp_png = out_path.with_name(out_path.stem + "_vtmp.png")
    try:
        subprocess.run(
            [
                FFMPEG_BIN,
                "-ss",
                "00:00:10",
                "-i",
                str(video_path),
                "-vframes",
                "1",
                str(tmp_png),
                "-y",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        if not tmp_png.exists():
            return False
        ok = make_thumb_from_image(tmp_png, out_path, width)
        try:
            tmp_png.unlink(missing_ok=True)
        except Exception:
            pass
        return ok
    except Exception:
        try:
            tmp_png.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _ascii_tmp_prefix(out_jpg: Path) -> tuple[Path, Path]:
    r"""
    ASCII 전용 임시 디렉터리에 파일 prefix를 만든다.
    반환: (tmp_dir, tmp_prefix)  ex) C:\\Users\\<me>\\AppData\\Local\\Temp\\pdfthumb_tmp\\out_temp_pdfthumb
    """
    base_tmp = Path(tempfile.gettempdir()) / "pdfthumb_tmp"
    base_tmp.mkdir(parents=True, exist_ok=True)
    # 파일명은 항상 ASCII
    tmp_prefix = base_tmp / "out_temp_pdfthumb"
    return base_tmp, tmp_prefix


def _cleanup_tmp_dir(tmp_dir: Path):
    try:
        # 너무 자주 지우면 경쟁조건 날 수 있으니, 파일만 지우고 폴더는 남겨도 OK
        for p in tmp_dir.glob("out_temp_pdfthumb*"):
            p.unlink(missing_ok=True)
    except Exception:
        pass


def _pdf_num_pages(pdf_path: Path) -> Optional[int]:
    if not PDFINFO_BIN:
        return None
    try:
        p = subprocess.run(
            [PDFINFO_BIN, str(pdf_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            shell=False,
            check=False,
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


def make_thumb_from_pdf(pdf_path: Path, out_path: Path, width: int) -> bool:
    # ANNO: 1) PyMuPDF 경로 (중앙 페이지) → 2) pdftoppm 폴백.
    if fitz is not None and Image is not None:
        try:
            doc = fitz.open(pdf_path)
            n = doc.page_count
            if n <= 0:
                return False
            mid0 = n // 2
            page = doc.load_page(mid0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            w, h = img.size
            if w > width:
                nh = int(h * (width / w))
                img = img.resize((width, nh), Image.LANCZOS)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(out_path, format="JPEG", quality=70, optimize=True)
            return True
        except Exception:
            pass  # 폴백

    if PDFTOPPM_BIN is None:
        return False

    # pdfinfo → 중앙(1-based)
    n = _pdf_num_pages(pdf_path) or 1
    mid = max(1, (n + 1) // 2)

    tmp_dir, tmp_prefix = _ascii_tmp_prefix(out_path)
    try:
        subprocess.run(
            [
                PDFTOPPM_BIN,
                "-jpeg",
                "-singlefile",
                "-f",
                str(mid),
                "-l",
                str(mid),
                "-r",
                "144",
                str(pdf_path),
                str(tmp_prefix),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            shell=False,
        )
    except Exception as e:
        _cleanup_tmp_dir(tmp_dir)
        return False

    cand1 = tmp_prefix.with_suffix(".jpg")
    cand2 = tmp_prefix.with_name(tmp_prefix.name + f"-{mid}").with_suffix(".jpg")
    made = cand1 if cand1.exists() else (cand2 if cand2.exists() else None)
    if not made:
        alts = list(tmp_dir.glob(tmp_prefix.name + "*.jpg"))
        made = alts[0] if alts else None
        if not made:
            _cleanup_tmp_dir(tmp_dir)
            return False

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        Path(made).replace(out_path)
        return True
    finally:
        _cleanup_tmp_dir(tmp_dir)


def ensure_thumbnail(folder: Path, refresh: bool, width: int) -> Optional[Path]:
    out = folder / THUMBS_DIR / f"{safe_name(folder.name)}.jpg"
    if out.exists() and not refresh:
        print(f"[thumb] reuse: {out}")
        return out

    img = find_first(folder, IMG_PATS)
    print(f"[thumb] {folder.name} -> img={img}")
    if img and make_thumb_from_image(img, out, width):
        print(f"[thumb] OK (image): {out}")
        return out

    pdf = find_first(folder, PDF_PATS)
    print(f"[thumb] {folder.name} -> pdf={pdf}")
    if pdf and make_thumb_from_pdf(pdf, out, width):
        print(f"[thumb] OK (pdf): {out}")
        return out

    vid = find_first(folder, VID_PATS)
    print(f"[thumb] {folder.name} -> video={vid}")
    if vid and make_thumb_from_video(vid, out, width):
        print(f"[thumb] OK (video): {out}")
        return out

    print(f"[thumb] SKIP (no source): {folder.name}")
    return None


# -------- 경로 보정 --------
def adjust_paths_for_folder(inner_html: str, folder_name: str) -> str:
    """master에서 가져온 div.folder 내부 HTML을 '폴더/index.html' 관점으로 보정"""
    # HAZARD(yesterday): 여기서는 경로만 보정하고, 버튼/편집 속성 제거는 하지 않는다 → 중복 주입 가능.
    if BeautifulSoup:
        soup = BeautifulSoup(inner_html, "html.parser")
        for tag in soup.find_all(["img", "a"]):
            if tag.name == "img" and tag.has_attr("src"):
                src = tag["src"]
                if src.startswith(f"{folder_name}/"):
                    tag["src"] = src[len(folder_name) + 1 :]
            if tag.name == "a" and tag.has_attr("href"):
                href = tag["href"]
                if href == f"{folder_name}/index.html":
                    tag["href"] = "index.html"
                elif href.startswith(f"{folder_name}/"):
                    tag["href"] = href[len(folder_name) + 1 :]
        return str(soup)

    # 폴백: 정규식
    html = re.sub(rf'(<img[^>]+src="){re.escape(folder_name)}/', r"\1", inner_html)
    html = re.sub(
        rf'(<a[^>]+href="){re.escape(folder_name)}/index\.html"', r'\1index.html"', html
    )
    html = re.sub(rf'(<a[^>]+href="){re.escape(folder_name)}/', r"\1", html)
    return html


# -------- 템플릿 --------
FOLDER_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    body {{ font-family: sans-serif; line-height: 1.6; padding: 2em; }}
    img {{ max-width: 300px; display: block; margin: 1em 0; }}
    .folder {{ margin-bottom: 3em; }}
  </style>
</head>
<body>
<div class="folder">
  <h2>{title}</h2>
  {inner}
  <a href="../{master}">⬅ 전체 목록으로</a>
</div>
</body>
</html>
"""

MASTER_HEAD = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>미술 수업 자료 Index</title>
  <style>
    body { font-family: sans-serif; line-height: 1.6; padding: 2em; }
    img { max-width: 300px; display: block; margin: 1em 0; }
    .folder { margin-bottom: 3em; }
  </style>
</head>
<body>
  <h1>미술 수업 자료 Index</h1>
"""

MASTER_TAIL = """
</body>
</html>
"""


# -------- 메인 --------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-thumbs", action="store_true")
    ap.add_argument("--thumb-width", type=int, default=640)
    args = ap.parse_args()

    cwd = Path.cwd()
    # ANNO: 실행 위치에 따라 resource 루트를 자동 인식.
    if (cwd / "resource").is_dir():
        content_root = cwd / "resource"
    else:
        if cwd.name == "resource":
            content_root = cwd
        else:
            content_root = cwd

    master_out = content_root / ROOT_MASTER

    # 1) 기존 master에서 폴더별 블록 맵 만들기
    # HAZARD(yesterday): master에 남은 버튼/편집 속성이 그대로 재사용될 수 있음.
    old_master_html = read_text(master_out)
    folder_blocks = {}
    if old_master_html and BeautifulSoup:
        soup = BeautifulSoup(old_master_html, "html.parser")
        for div in soup.find_all("div", class_="folder"):
            h2 = div.find("h2")
            if h2:
                folder_blocks[h2.get_text(strip=True)] = str(div)
    elif old_master_html:
        for m in re.finditer(
            r'(<div class="folder">.*?</div>)',
            old_master_html,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            block = m.group(1)
            mh2 = re.search(
                r"<h2>\s*(.*?)\s*</h2>", block, flags=re.DOTALL | re.IGNORECASE
            )
            if mh2:
                folder_blocks[mh2.group(1)] = block

    # 2) 폴더별 index.html 생성/갱신
    folders = list_folders_sorted(content_root)
    for folder in folders:
        # 썸네일 생성/재생성
        thumb = ensure_thumbnail(folder, args.refresh_thumbs, args.thumb_width)

        # 과거 master 블록에서 내부 HTML 추출
        old_block = folder_blocks.get(folder.name, "")
        inner_html = ""
        if BeautifulSoup and old_block:
            soup = BeautifulSoup(old_block, "html.parser")
            div = soup.find("div", class_="folder")
            if div:
                for child in list(div.children):
                    if getattr(child, "name", None) == "h2":
                        child.extract()
                inner_html = "".join(str(x) for x in div.contents).strip()
        elif old_block:
            m = re.search(
                r"<h2>.*?</h2>(.*)</div>", old_block, flags=re.DOTALL | re.IGNORECASE
            )
            if m:
                inner_html = m.group(1).strip()

        if inner_html:
            inner_html = adjust_paths_for_folder(inner_html, folder.name)

        # 썸네일 자동 보강: 폴더 index에는 반드시 이미지 하나 들어가게
        if thumb and "<img" not in inner_html:
            inner_html = (
                f'<img src="{THUMBS_DIR}/{safe_name(folder.name)}.jpg" alt="썸네일"><br>\n'
                + (inner_html or "")
            )

        html = FOLDER_TEMPLATE.format(
            title=folder.name,
            inner=inner_html if inner_html else "<p>설명: </p>",
            master=ROOT_MASTER,
        )
        write_text(folder / FOLDER_INDEX, html)
        print(f"{folder / FOLDER_INDEX} 생성")

    # 3) master_index.html 재생성
    blocks = []
    for folder in folders:
        idx = folder / FOLDER_INDEX
        if not idx.exists():
            continue
        html = read_text(idx)
        if BeautifulSoup:
            soup = BeautifulSoup(html, "html.parser")
            div = soup.find("div", class_="folder")
            if not div:
                continue

            # "전체 목록으로" 링크 제거 (img 있으면 unwrap, 아니면 제거)
            for a in list(div.find_all("a", href=True)):
                if a["href"] == f"../{ROOT_MASTER}":
                    if a.find("img"):
                        a.unwrap()
                    else:
                        a.decompose()

            # master 기준 경로 보정
            for tag in div.find_all(["img", "a"]):
                if tag.name == "img" and tag.has_attr("src"):
                    src = tag["src"]
                    if not src.startswith(("http://", "https://", "/", "../", "#")):
                        tag["src"] = f"{folder.name}/{src}"
                if tag.name == "a" and tag.has_attr("href"):
                    href = tag["href"]
                    if href == "index.html":
                        tag["href"] = f"{folder.name}/index.html"
                    elif not href.startswith(("http://", "https://", "/", "../", "#")):
                        tag["href"] = f"{folder.name}/{href}"

            blocks.append(str(div))
        else:
            m = re.search(
                r'(<div class="folder">.*?</div>)',
                html,
                flags=re.DOTALL | re.IGNORECASE,
            )
            if not m:
                continue
            div_html = m.group(1)

            # 1) 앵커 안에 이미지가 있으면 unwrap
            div_html = re.sub(
                rf'<a[^>]+href="\.\./{re.escape(ROOT_MASTER)}"[^>]*>\s*(<img[^>]*>)\s*</a>',
                r"\1",
                div_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            # 2) 뒤로가기 앵커 제거
            div_html = re.sub(
                rf'<a[^>]+href="\.\./{re.escape(ROOT_MASTER)}"[^>]*>.*?</a>',
                "",
                div_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            # master 기준 경로 보정
            div_html = re.sub(
                r'(<img[^>]+src=")(?!https?://|/|\.\./|#)([^"]+)"',
                lambda m: f'{m.group(1)}{folder.name}/{m.group(2)}"',
                div_html,
            )
            div_html = re.sub(
                r'(<a[^>]+href=")index\.html"',
                lambda m: f'{m.group(1)}{folder.name}/index.html"',
                div_html,
            )
            div_html = re.sub(
                r'(<a[^>]+href=")(?!https?://|/|\.\./|#)([^"]+)"',
                lambda m: f'{m.group(1)}{folder.name}/{m.group(2)}"',
                div_html,
            )

            blocks.append(div_html)

    master_html = MASTER_HEAD + "\n\n".join(blocks) + MASTER_TAIL
    write_text(master_out, master_html)
    print(f"🎉 {master_out.name} 갱신 완료")


if __name__ == "__main__":
    main()
