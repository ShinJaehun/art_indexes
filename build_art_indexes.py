#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
미술 수업 자료 인덱서 (build_art_indexes.py)

📌 기능
- 각 하위 폴더에 index.html 생성/갱신
- master_index.html 재생성
- 썸네일 자동 생성 (우선순위: PDF → VIDEO → IMAGE)
  * PDF: 여러 페이지면 가운데(중간) 페이지 캡처
  * VIDEO: 10초 지점 프레임 캡처
  * IMAGE: 첫 번째 이미지 파일 리사이즈
- div.folder 내부의 커스텀 마크업(작은 div, 목록 등) 보존
- 폴더 index에는 “⬅ 전체 목록으로” 링크를 넣되, master에는 자동 제거
  (이미지를 감싸고 있던 앵커는 unwrap 처리하여 이미지 보존)

📌 의존성
- Python 3.9+ 권장
- 필수: 없음 (HTML 인덱스 생성만 원하면 라이브러리 없이 실행 가능)
- 썸네일 생성을 위해 권장 설치:
    pip install pillow pymupdf beautifulsoup4
  시스템 도구:
    ffmpeg  (동영상 프레임 추출)
      - Ubuntu/Debian: sudo apt-get update && sudo apt-get install -y ffmpeg
      - macOS(Homebrew): brew install ffmpeg
      - Windows: https://ffmpeg.org/download.html 에서 설치 후 PATH 등록
    (선택) ImageMagick (convert/magick) — 본 스크립트는 기본적으로 사용하지 않지만,
           설치되어 있으면 다른 워크플로에 유용

📌 실행 예시
  python3 build_art_indexes.py
  python3 build_art_indexes.py --refresh-thumbs
  python3 build_art_indexes.py --thumb-width 800

📌 옵션
  --refresh-thumbs   : 이미 썸네일이 있어도 새로 생성
  --thumb-width N    : 썸네일 최대 가로폭(px), 기본 640
"""

import re
import argparse
import subprocess
from pathlib import Path
import shutil

# -------- 선택적 의존성 --------
try:
    from PIL import Image
except Exception:
    Image = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

def which_bin(*candidates: str) -> str | None:
    for c in candidates:
        p = shutil.which(c)
        if p:
            return c
    return None

FFMPEG_BIN = which_bin("ffmpeg")

# -------- 설정 --------
ROOT_MASTER = "master_index.html"
FOLDER_INDEX = "index.html"
THUMBS_DIR = "thumbs"

# -------- 유틸 --------
def safe_name(name: str) -> str:
    return name.replace(" ", "_")

def list_folders_sorted(base: Path) -> list[Path]:
    return sorted([p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")])

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

# -------- 썸네일 생성 --------
def find_first(base: Path, patterns: list[str]) -> Path | None:
    for pat in patterns:
        for p in base.glob(pat):
            if p.is_file():
                return p
    return None

def make_thumb_from_pdf(pdf_path: Path, out_path: Path, width: int) -> bool:
    """PyMuPDF + Pillow 경로: PDF 가운데 페이지 캡처"""
    if fitz is None or Image is None:
        return False
    try:
        doc = fitz.open(pdf_path)
        n = doc.page_count
        if n == 0:
            return False
        mid = n // 2  # 0-based 중앙
        page = doc.load_page(mid)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        w, h = img.size
        if w > width:
            nh = int(h * (width / w))
            img = img.resize((width, nh), Image.LANCZOS)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, format="JPEG", quality=70)
        return True
    except Exception:
        return False

def make_thumb_from_video(video_path: Path, out_path: Path, width: int) -> bool:
    """ffmpeg + Pillow 경로: 10초 지점 프레임"""
    if not FFMPEG_BIN or Image is None:
        return False
    tmp_png = out_path.with_name(out_path.stem + "_tmp.png")
    try:
        subprocess.run(
            [FFMPEG_BIN, "-ss", "00:00:10", "-i", str(video_path),
             "-vframes", "1", str(tmp_png), "-y"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=True
        )
        if not tmp_png.exists():
            return False
        img = Image.open(tmp_png)
        w, h = img.size
        if w > width:
            nh = int(h * (width / w))
            img = img.resize((width, nh), Image.LANCZOS)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, format="JPEG", quality=70)
        tmp_png.unlink(missing_ok=True)
        return True
    except Exception:
        tmp_png.unlink(missing_ok=True)
        return False

# def make_thumb_from_image(img_path: Path, out_path: Path, width: int) -> bool:
#     if Image is None:
#         return False
#     try:
#         img = Image.open(img_path)
#         w, h = img.size
#         if w > width:
#             nh = int(h * (width / w))
#             img = img.resize((width, nh), Image.LANCZOS)
#         out_path.parent.mkdir(parents=True, exist_ok=True)
#         img.save(out_path, format="JPEG", quality=70)
#         return True
#     except Exception:
#         return False

def make_thumb_from_image(img_path: Path, out_path: Path, width: int) -> bool:
    if Image is None:
        return False
    try:
        from PIL import ImageOps, ImageFile
        ImageFile.LOAD_TRUNCATED_IMAGES = True  # 손상/부분 저장된 파일도 최대한 로드

        img = Image.open(img_path)
        # EXIF 회전 보정 (스마트폰 촬영 이미지 대비)
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # JPEG 호환 모드로 변환 (RGBA/LA/P/CMYK → RGB)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            # 흑백 이미지는 그대로 저장해도 되지만 일관성을 위해 RGB로
            img = img.convert("RGB")

        # 리사이즈
        w, h = img.size
        if w > width:
            nh = int(h * (width / w))
            img = img.resize((width, nh), Image.LANCZOS)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, format="JPEG", quality=70, optimize=True)
        return True
    except Exception as e:
        # 필요하면 임시 디버깅 출력:
        # print(f"[thumb][image] FAIL {img_path}: {e}")
        return False
    
# def ensure_thumbnail(folder: Path, refresh: bool, width: int) -> Path | None:
#     out = folder / THUMBS_DIR / f"{safe_name(folder.name)}.jpg"
#     if out.exists() and not refresh:
#         return out

#     # 1) IMAGE 먼저
#     img = find_first(folder, ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"])
#     if img and make_thumb_from_image(img, out, width):
#         return out

#     # 2) PDF 그 다음
#     pdf = find_first(folder, ["*.pdf", "*.PDF"])
#     if pdf and make_thumb_from_pdf(pdf, out, width):
#         return out

#     # 3) VIDEO 마지막
#     video = find_first(folder, ["*.mp4", "*.mov", "*.m4v", "*.avi", "*.MP4", "*.MOV", "*.M4V", "*.AVI"])
#     if video and make_thumb_from_video(video, out, width):
#         return out

#     return None

def ensure_thumbnail(folder: Path, refresh: bool, width: int) -> Path | None:
    out = folder / THUMBS_DIR / f"{safe_name(folder.name)}.jpg"
    if out.exists() and not refresh:
        print(f"[thumb] reuse: {out}")
        return out

    img = find_first(folder, ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"])
    print(f"[thumb] {folder.name} -> img={img}")  # ← 추가
    if img and make_thumb_from_image(img, out, width):
        print(f"[thumb] OK (image): {out}")        # ← 추가
        return out

    pdf = find_first(folder, ["*.pdf", "*.PDF"])
    print(f"[thumb] {folder.name} -> pdf={pdf}")  # ← 추가
    if pdf and make_thumb_from_pdf(pdf, out, width):
        print(f"[thumb] OK (pdf): {out}")          # ← 추가
        return out

    video = find_first(folder, ["*.mp4", "*.mov", "*.m4v", "*.avi", "*.MP4", "*.MOV", "*.M4V", "*.AVI"])
    print(f"[thumb] {folder.name} -> video={video}")  # ← 추가
    if video and make_thumb_from_video(video, out, width):
        print(f"[thumb] OK (video): {out}")            # ← 추가
        return out

    print(f"[thumb] SKIP (no source): {folder.name}")  # ← 추가
    return None

# -------- 경로 보정 --------
def adjust_paths_for_folder(inner_html: str, folder_name: str) -> str:
    """master에서 가져온 div.folder 내부 HTML을 '폴더/index.html' 관점으로 보정"""
    if BeautifulSoup:
        soup = BeautifulSoup(inner_html, "html.parser")
        for tag in soup.find_all(["img", "a"]):
            if tag.name == "img" and tag.has_attr("src"):
                src = tag["src"]
                if src.startswith(f"{folder_name}/"):
                    tag["src"] = src[len(folder_name)+1:]
            if tag.name == "a" and tag.has_attr("href"):
                href = tag["href"]
                if href == f"{folder_name}/index.html":
                    tag["href"] = "index.html"
                elif href.startswith(f"{folder_name}/"):
                    tag["href"] = href[len(folder_name)+1:]
        return str(soup)
    # 폴백: 정규식
    html = re.sub(rf'(<img[^>]+src="){re.escape(folder_name)}/', r'\1', inner_html)
    html = re.sub(rf'(<a[^>]+href="){re.escape(folder_name)}/index\.html"', r'\1index.html"', html)
    html = re.sub(rf'(<a[^>]+href="){re.escape(folder_name)}/', r'\1', html)
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

    root = Path.cwd()

    # 1) 과거 master 읽어와 폴더별 블록 맵 구성
    old_master_html = read_text(root / ROOT_MASTER)
    folder_blocks = {}
    if old_master_html and BeautifulSoup:
        soup = BeautifulSoup(old_master_html, "html.parser")
        for div in soup.find_all("div", class_="folder"):
            h2 = div.find("h2")
            if h2:
                folder_blocks[h2.get_text(strip=True)] = str(div)
    elif old_master_html:
        for m in re.finditer(r'(<div class="folder">.*?</div>)',
                             old_master_html, flags=re.DOTALL | re.IGNORECASE):
            block = m.group(1)
            mh2 = re.search(r"<h2>\s*(.*?)\s*</h2>", block,
                            flags=re.DOTALL | re.IGNORECASE)
            if mh2:
                folder_blocks[mh2.group(1)] = block

    # 2) 폴더별 index.html 생성/갱신
    folders = list_folders_sorted(root)
    for folder in folders:
        if folder.name == ".git":
            continue

        thumb = ensure_thumbnail(folder, args.refresh_thumbs, args.thumb_width)

        # master 블록에서 내부 HTML 추출
        old_block = folder_blocks.get(folder.name, "")
        inner_html = ""
        if BeautifulSoup and old_block:
            soup = BeautifulSoup(old_block, "html.parser")
            div = soup.find("div", class_="folder")
            if div:
                # h2 제외한 내부 내용만
                for child in list(div.children):
                    if getattr(child, "name", None) == "h2":
                        child.extract()
                inner_html = "".join(str(x) for x in div.contents).strip()
        elif old_block:
            m = re.search(r'<h2>.*?</h2>(.*)</div>', old_block,
                          flags=re.DOTALL | re.IGNORECASE)
            if m:
                inner_html = m.group(1).strip()

        if inner_html:
            inner_html = adjust_paths_for_folder(inner_html, folder.name)

        # 썸네일 자동 보강: 폴더 index에는 반드시 이미지가 들어가게
        if thumb and '<img' not in inner_html:
            inner_html = f'<img src="{THUMBS_DIR}/{safe_name(folder.name)}.jpg" alt="썸네일"><br>\n' + (inner_html or '')

        html = FOLDER_TEMPLATE.format(
            title=folder.name,
            inner=inner_html if inner_html else "<p>설명: </p>",
            master=ROOT_MASTER
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
                        a.unwrap()   # 링크만 제거, 이미지 보존
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
            m = re.search(r'(<div class="folder">.*?</div>)',
                          html, flags=re.DOTALL | re.IGNORECASE)
            if not m:
                continue
            div_html = m.group(1)

            # 1) 앵커 안에 이미지가 있으면 unwrap
            div_html = re.sub(
                rf'<a[^>]+href="\.\./{re.escape(ROOT_MASTER)}"[^>]*>\s*(<img[^>]*>)\s*</a>',
                r'\1',
                div_html,
                flags=re.IGNORECASE | re.DOTALL
            )
            # 2) 뒤로가기 앵커 제거
            div_html = re.sub(
                rf'<a[^>]+href="\.\./{re.escape(ROOT_MASTER)}"[^>]*>.*?</a>',
                '',
                div_html,
                flags=re.IGNORECASE | re.DOTALL
            )

            # master 기준 경로 보정
            div_html = re.sub(
                r'(<img[^>]+src=")(?!https?://|/|\.\./|#)([^"]+)"',
                rf'\1{folder.name}/\2"', div_html)
            div_html = re.sub(
                r'(<a[^>]+href=")index\.html"',
                rf'\1{folder.name}/index.html"', div_html)
            div_html = re.sub(
                r'(<a[^>]+href=")(?!https?://|/|\.\./|#)([^"]+)"',
                rf'\1{folder.name}/\2"', div_html)

            blocks.append(div_html)

    master_html = MASTER_HEAD + "\n\n".join(blocks) + MASTER_TAIL
    write_text(root / ROOT_MASTER, master_html)
    print(f"🎉 {ROOT_MASTER} 갱신 완료")

if __name__ == "__main__":
    main()
