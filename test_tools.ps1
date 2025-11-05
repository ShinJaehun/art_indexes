<#
.SYNOPSIS
  SukSuk Index(미술 자료 인덱서) 로컬 개발 환경에서 백엔드 파이프라인을
  파워셸로 빠르게 점검/연습하기 위한 스모크 테스트 스크립트.

.DESCRIPTION
  이 스크립트는 프로젝트 루트(backend/, resource/ 포함)에서 다음을 검증합니다.
    1) 썸네일 스캔/생성(SSOT = resource/ 폴더 기준)
    2) master_content.html → resource/master_index.html 및 각 child index.html 푸시
    3) Pruner 드라이런/적용(고아/누락 정리)
    4) 파일 잠금(SyncLock) 동작: 동시 실행 시 하나는 성공, 다른 하나는 'locked'
    5) 환경 변수에 의한 실패 주입/로깅/TTL 동작

  개발자가 파워셸 콘솔에서 한 줄로 "지금 상태가 정상인지"를 재빨리 확인하는 용도입니다.
  Bash 의존 없이 Windows/PowerShell 환경에서 바로 사용 가능하도록 작성되었습니다.

.PREREQUISITES
  - Windows PowerShell 5+ 또는 PowerShell 7+
  - (선택) 가상환경: .venv\Scripts\Activate.ps1
  - PYTHONPATH: 프로젝트 루트(backend 상위)를 가리키도록 설정
  - 프로젝트 구조:
        <project-root>\
          backend\
            api.py, builder.py, pruner.py, thumbs.py, thumbops.py, htmlops.py, ...
            bin\ffmpeg.exe, bin\poppler\pdftoppm.exe, bin\poppler\pdfinfo.exe (권장)
          resource\ <각 자료 폴더>
          master_content.html (없어도 됨: 최초 실행 시 bootstrap 가능)

.USAGE
  # 1) 현재 세션에 로드(도트 소싱)
  PS> . .\test_tools.ps1

  # 2) 개별 테스트 실행
  PS> Warmup              # master_content/미리보기 일부 출력
  PS> Run-ScanOnly        # 썸네일/SSOT 스캔 결과(JSON 유사) 출력
  PS> Run-Sync            # 전체 동기화(스캔→푸시) 실행
  PS> Run-PrunerPrint     # 드라이런 리포트
  PS> Run-PrunerApply     # 정리 적용 (기본: thumbs 미삭제)
  PS> Run-PrunerApply -DeleteThumbs  # 고아 썸네일까지 삭제
  PS> Test-Lock           # 동시 실행 시 락 동작 검증(1개 성공 / 1개 locked)
  PS> Test-StaleLock      # 락 TTL(기본 3600s) 단축해 자동 해제 확인
  PS> Test-FailScan       # 스캔 실패 주입 → 에러 경로/로그 확인
  PS> Test-FailPush       # 푸시 실패 주입 → 에러 경로/로그 확인
  PS> Test-SanVerbose     # sanitizer 상세 로그 출력
  PS> Smoke-All           # 0→4 단계까지 빠른 E2E 스모크 실행

.FUNCTIONS
  Set-ProjectEnv     : 현재 세션의 PYTHONPATH 등 실행 환경 준비
  Invoke-Py          : UTF-8 코드 조각을 python stdin으로 안전하게 전달해 실행
  Warmup             : MasterApi.get_master() 결과 프리뷰(앞 120자)
  Run-ScanOnly       : builder.run_sync_all(scan_only=True) 결과(SSOT 스캔) 출력
  Run-Sync           : MasterApi.sync() 전체 동기화 수행 및 메트릭 출력
  Run-PrunerPrint    : backend/pruner.py --print (드라이런)
  Run-PrunerApply    : backend/pruner.py --apply (옵션: --delete-thumbs)
  Test-Lock          : 두 개의 동시 sync를 별도 프로세스로 실행해 락 처리 검증
  Test-StaleLock     : SUKSUKIDX_LOCK_STALE_AFTER=3으로 락 자동 해제 확인
  Test-FailScan      : SUKSUKIDX_FAIL_SCAN=1 로 실패 경로 검증
  Test-FailPush      : SUKSUKIDX_FAIL_PUSH=1 로 실패 경로 검증
  Test-SanVerbose    : SUKSUKIDX_SAN_VERBOSE=1 로 카드별 sanitizer 메트릭 노출
  Smoke-All          : Warmup → ScanOnly → PrunerPrint → PrunerApply → Sync 순차 실행

.ENVIRONMENT VARIABLES (optional)
  PYTHONPATH                      : 프로젝트 루트 경로(스크립트에서 자동 설정)
  SUKSUKIDX_LOCK_STALE_AFTER=N    : 락 만료 시간(초), 기본 3600
  SUKSUKIDX_FAIL_SCAN=1           : 스캔 실패 강제 주입(개발/테스트 전용)
  SUKSUKIDX_FAIL_PUSH=1           : 푸시 실패 강제 주입(개발/테스트 전용)
  SUKSUKIDX_SAN_VERBOSE=1         : sanitizer 카드별 상세 메트릭 로그

.RETURNS & LOGS
  - 각 함수는 python 모듈의 표준 출력/에러를 그대로 표시합니다.
  - MasterApi.sync() 결과는 dict(JSON 유사) 형태로 ok/metrics/locked 등을 출력합니다.
  - 암호 PDF의 경우 thumbs 생성 단계에서 "PDF is password-protected, skip" 로그가 stderr에 남는 것은 정상입니다.

.COMMON ISSUES & TIPS
  - 실행 정책: 도트 소싱이 막힐 경우
      PS> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
    (조직 정책으로 무시될 수 있으며, 이 스크립트 로드는 보통 Bypass 또는 RemoteSigned에서 동작)
  - 인코딩: 이 파일은 **UTF-8 (BOM 불필요)** 로 저장하세요.
  - venv: 가상환경을 자동 활성화하고 싶으면 Set-ProjectEnv 내부의
          Activate.ps1 라인을 주석 해제하고 경로를 맞춰주세요.
  - 도트 소싱 후 내용 수정 시, 다시 `. .\test_tools.ps1` 로 재로드해야 함수 갱신됩니다.

.MAINTAINERS’ NOTES
  - 이 스크립트는 “테스트 러너”이지, 배포 도구가 아닙니다.
  - 백엔드 내부 API 시그니처가 바뀌면 여기 함수의 import/호출부를 함께 업데이트하세요.
  - ffmpeg/poppler 바이너리가 없다면 시스템 PATH 의 전역 설치본을 사용하도록 thumbs.py 가 설계되어 있습니다.

#>


# Resolve project root (folder that contains backend/)
$Script:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:BackendDir  = Join-Path $Script:ProjectRoot "backend"
$Script:ResourceDir = Join-Path $Script:ProjectRoot "resource"

# Ensure PYTHONPATH and venv are in this session
function Set-ProjectEnv {
  $env:PYTHONPATH = $Script:ProjectRoot
  # Optional: if you have a venv, activate by path (uncomment and set correct path)
  # & "$Script:ProjectRoot\.venv\Scripts\Activate.ps1" | Out-Null
}

# Helper: run inline python with env prepared (PowerShell-safe)
function Invoke-Py([string]$code) {
  Set-ProjectEnv
  $tmp = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "ps_py_{0}.py" -f ([guid]::NewGuid()))
  [System.IO.File]::WriteAllText($tmp, $code, [System.Text.Encoding]::UTF8)
  try {
    & python $tmp
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

# 0) Warm-up: print first 120 chars of get_master()["html"]
function Warmup {
  Set-ProjectEnv
  Invoke-Py @"
from backend.api import MasterApi
from pathlib import Path
api = MasterApi(Path(r'$Script:ProjectRoot'))
html = api.get_master().get('html','')
print((html[:120] + '...') if html else '(empty)') 
"@
}

# 1) Scan thumbnails only
function Run-ScanOnly {
  Set-ProjectEnv
  Invoke-Py @"
from backend.builder import run_sync_all
from pathlib import Path
print(run_sync_all(Path(r'$Script:ResourceDir'), scan_only=True))
"@
}

# 2) Full sync
function Run-Sync {
  Set-ProjectEnv
  Invoke-Py @"
from backend.api import MasterApi
from pathlib import Path
api = MasterApi(Path(r'$Script:ProjectRoot'))
print(api.sync())
"@
}

# 3) Pruner dry-run
function Run-PrunerPrint {
  Set-ProjectEnv
  & python "$Script:BackendDir\pruner.py" --print
}

# 3b) Pruner apply (optionally delete orphan thumbs)
function Run-PrunerApply {
  param([switch]$DeleteThumbs)
  Set-ProjectEnv
  $args = @("--apply")
  if ($DeleteThumbs) { $args += "--delete-thumbs" }
  & python "$Script:BackendDir\pruner.py" @args
}

# 4) Lock test: start two syncs nearly at the same time (PowerShell-safe)
function Test-Lock {
  Set-ProjectEnv
  Write-Host "Start two syncs concurrently (expect one 'locked')."

  # Python 코드 (출력 보장용 프린트 추가)
  $root = $Script:ProjectRoot -replace '\\','\\'
$pyCode = @"
from backend.api import MasterApi
from pathlib import Path
api = MasterApi(Path(r'$root'))
print('[py] starting sync...')
print(api.sync())
print('[py] done.')
"@

  # 1) 임시 .py 파일 생성
  $tmpPy = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), ([guid]::NewGuid().ToString() + ".py"))
  [System.IO.File]::WriteAllText($tmpPy, $pyCode, [System.Text.Encoding]::UTF8)

  # 2) stdout/stderr 캡처 파일
  $out1 = [System.IO.Path]::GetTempFileName(); $err1 = [System.IO.Path]::GetTempFileName()
  $out2 = [System.IO.Path]::GetTempFileName(); $err2 = [System.IO.Path]::GetTempFileName()

  # 3) 두 프로세스 동시 실행
  $p1 = Start-Process -FilePath "python" -ArgumentList @("$tmpPy") `
        -WorkingDirectory $Script:ProjectRoot -NoNewWindow -PassThru `
        -RedirectStandardOutput $out1 -RedirectStandardError $err1
  Start-Sleep -Milliseconds 150
  $p2 = Start-Process -FilePath "python" -ArgumentList @("$tmpPy") `
        -WorkingDirectory $Script:ProjectRoot -NoNewWindow -PassThru `
        -RedirectStandardOutput $out2 -RedirectStandardError $err2

  # 4) 완료 대기 (정확한 종료 확인)
  Wait-Process -Id $p1.Id, $p2.Id

  # 5) 종료코드/파일크기/내용 출력
  $s1 = (Get-Item $out1).Length; $e1 = (Get-Item $err1).Length
  $s2 = (Get-Item $out2).Length; $e2 = (Get-Item $err2).Length
  Write-Host "`nJob#1 ExitCode=$($p1.ExitCode)  stdout=${s1}B  stderr=${e1}B"
  if (Test-Path $out1) { Write-Host "--- Job#1 stdout ---"; Get-Content -Raw $out1 }
  if (Test-Path $err1) { Write-Host "--- Job#1 stderr ---"; Get-Content -Raw $err1 }

  Write-Host "`nJob#2 ExitCode=$($p2.ExitCode)  stdout=${s2}B  stderr=${e2}B"
  if (Test-Path $out2) { Write-Host "--- Job#2 stdout ---"; Get-Content -Raw $out2 }
  if (Test-Path $err2) { Write-Host "--- Job#2 stderr ---"; Get-Content -Raw $err2 }

  # 6) 정리
  Remove-Item $tmpPy, $out1, $err1, $out2, $err2 -ErrorAction SilentlyContinue
}

# 4b) Stale lock auto release (set low TTL)
function Test-StaleLock {
  Set-ProjectEnv
  $env:SUKSUKIDX_LOCK_STALE_AFTER = "3"
  Run-Sync
  Start-Sleep 4
  Run-Sync
  Remove-Item Env:\SUKSUKIDX_LOCK_STALE_AFTER -ErrorAction SilentlyContinue
}

# 5) Force fail: scan
function Test-FailScan {
  Set-ProjectEnv
  $env:SUKSUKIDX_FAIL_SCAN = "1"
  Run-Sync
  Remove-Item Env:\SUKSUKIDX_FAIL_SCAN -ErrorAction SilentlyContinue
}

# 6) Force fail: push
function Test-FailPush {
  Set-ProjectEnv
  $env:SUKSUKIDX_FAIL_PUSH = "1"
  Run-Sync
  Remove-Item Env:\SUKSUKIDX_FAIL_PUSH -ErrorAction SilentlyContinue
}

# 7) Sanitizer verbose
function Test-SanVerbose {
  Set-ProjectEnv
  $env:SUKSUKIDX_SAN_VERBOSE = "1"
  Run-Sync
  Remove-Item Env:\SUKSUKIDX_SAN_VERBOSE -ErrorAction SilentlyContinue
}

# 8) Smoke-all: quick manual E2E
function Smoke-All {
  Write-Host "`n[0] Warmup (get_master preview)"
  Warmup

  Write-Host "`n[1] Thumbnail scan (scan_only)"
  Run-ScanOnly

  Write-Host "`n[2] Pruner dry-run"
  Run-PrunerPrint

  Write-Host "`n[3] Pruner apply (with orphan thumbs delete)"
  Run-PrunerApply -DeleteThumbs

  Write-Host "`n[4] Full sync"
  Run-Sync

  Write-Host "`nDone."
}

Write-Host "Loaded. Commands:"
" - Warmup"
" - Run-ScanOnly"
" - Run-Sync"
" - Run-PrunerPrint"
" - Run-PrunerApply [-DeleteThumbs]"
" - Test-Lock"
" - Test-StaleLock"
" - Test-FailScan"
" - Test-FailPush"
" - Test-SanVerbose"
" - Smoke-All"
