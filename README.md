# 쑥쑥인덱스 (Suksuk Index)

쑥쑥인덱스는 미술·수업 자료를 **폴더 기반으로 정리**하고, 자동으로 **썸네일과 카드형 인덱스 페이지**를 생성·관리할 수 있는 Python + PyWebView 기반 데스크톱 도구입니다.

교사가 직접 자료를 관리하면서 HTML/CSS/JavaScript 지식 없이도 파일 정리 → Sync → 바로 활용 가능한 인덱스를 만드는 것을 목표로 합니다.

---

## 주요 특징

- 📁 **파일 시스템 기반 자료 관리**
  - `resource/` 폴더를 기준으로 자료 구성
  - 폴더 하나 = 하나의 카드(자료 묶음)

- 🖼️ **자동 썸네일 생성 (선택 기능)**
  - 이미지 / PDF / 비디오 지원
  - 외부 도구가 설치된 경우에만 자동 생성

- 🧾 **카드형 인덱스 UI**
  - 제목, 설명, 메모, 링크 편집 가능
  - 브라우저 UI + PyWebView 데스크톱 실행

- 🔄 **Sync 기반 반영**
  - 자료 추가/삭제 후 Sync 버튼으로 인덱스 갱신
  - 결과물은 HTML 파일로 생성됨

- 🖥️ **Windows Portable 지원**
  - Python 미설치 환경에서도 실행 가능
  - PyInstaller 기반 단일 exe

---

## 디렉토리 구조

```text
project_root/
├─ suksukidx.exe          # 실행 파일 (portable)
├─ resource/              # 실제 자료 폴더
│  ├─ 자료A/
│  └─ 자료B/
├─ backend/
│  ├─ app.py
│  ├─ api.py
│  ├─ master_content.html
│  └─ ui/
│     └─ index.html
└─ logs/                  # 실행 로그
```

ℹ️ 인덱스 생성 방식  
Sync 실행 시, **전체 자료를 모은 `master_index.html`이 먼저 생성**되며 이후 각 자료 폴더 안에 **해당 폴더 전용 `index.html`**이 자동으로 생성됩니다.

---

## 기본 사용 방법

1. `resource/` 폴더에 자료 정리
2. `suksukidx.exe` 실행
3. UI에서 **Sync** 클릭
4. (선택) 썸네일 자동 생성
5. 필요 시 카드 설명/메모 편집

---

## 썸네일 생성 도구 설치 안내 (선택)

쑥쑥인덱스의 **썸네일 생성 기능은 선택 사항**입니다. 아래 도구가 설치되어 있는 경우에만 자동으로 썸네일을 생성합니다. 설치되어 있지 않아도 **Sync, 편집, 인덱싱 등 핵심 기능은 정상 동작**합니다.

---

### 1️⃣ ffmpeg (이미지 / 비디오 썸네일)

동영상 썸네일 생성에는 `ffmpeg` 도구가 필요합니다.

#### Windows 설치 방법
1. https://ffmpeg.org/download.html 접속
2. Windows → static build 다운로드
3. 압축 해제 후 ffmpeg.exe 파일 확인
4. 아래 경로에 ffmpeg.exe 파일을 복사

```
suksukidx/_internal/backend/bin/ffmpeg.exe
```

---

### 2️⃣ poppler (PDF 썸네일)

PDF 썸네일 생성에는 `pdftoppm` 도구가 필요합니다.

#### Windows 설치 방법
1. https://github.com/oschwartz10612/poppler-windows/releases 접속
2. 최신 zip 파일 다운로드
3. 압축 해제
4. 압축 해제된 폴더 전체를 아래 경로에 그대로 복사

```
suksukidx/_internal/backend/bin/poppler/
```

---

### ffmpeg / poppler 복사 후 디렉토리 구조

두 도구를 복사한 뒤, _internal/backend/bin 디렉토리는 다음과 같은 구조가 됩니다.

```text
suksukidx/
└─ _internal/
   └─ backend/
      ├─ ui/
      └─ bin/
         ├─ ffmpeg.exe
         └─ poppler/
            ├─ pdftoppm.exe
            ├─ pdftocairo.exe
            ├─ pdfinfo.exe
            ├─ poppler.dll
            ├─ poppler-cpp.dll
            ├─ cairo.dll
            └─ (기타 poppler 관련 dll 및 exe 파일)
```

- ffmpeg.exe : 이미지 / 비디오 썸네일 생성에 사용
- pdftoppm.exe : PDF 첫 페이지를 이미지로 변환하는 핵심 도구
- pdftocairo.exe : PDF 렌더링 보조 도구 (환경에 따라 함께 사용)
- pdfinfo.exe : PDF 메타 정보 확인용 보조 도구
- poppler 폴더에는 위 파일 외에도 여러 DLL 및 보조 실행 파일이 함께 포함되어야 합니다. 개별 파일만 복사하지 말고, poppler 폴더 전체를 그대로 복사해야 합니다.

---

### 주의 사항

- ffmpeg / poppler는 **외부 도구**이며 쑥쑥인덱스에 포함되어 있지 않습니다.
- 설치되어 있지 않거나 실행에 실패하는 경우해당 자료의 썸네일 생성만 건너뛰며 프로그램은 중단되지 않습니다.

---

## 기술 스택

- Backend: Python, PyWebView
- Frontend: Vanilla JavaScript, HTML, CSS
- Thumbnail (선택): ffmpeg, poppler
- Build: PyInstaller (Windows portable)

---

## 현재 상태

- v1.0 (안정화 완료)
- Sync / 썸네일 / 편집 / 전체 초기화 동작 검증 완료
- 구조 정리(P6-pre)까지 완료
- Registry 기반 SSOT 구조(P6)는 보류 상태

---

## 저작권

쑥쑥인덱스는 신재훈이 만들었습니다.  
쑥쑥인덱스는 GNU/GPL을 따릅니다.  
쑥쑥인덱스는 사용 과정에서 발생하는 문제에 대해 보증하지 않습니다.

