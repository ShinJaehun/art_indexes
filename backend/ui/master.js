// master.js
window._loadingMaster = false; // master_load.js

let _bridgeReadyOnce = false;

window.hasBridge = false; // bridge.js
let hasBridge = window.hasBridge; // (하위호환) 기존 참조를 최대한 유지

window._statusTimer = null; // status.js 
window._metaSaveTimer = null; // enhance_blocks.js

let _syncInProgress = false; // P5: Sync 중복 클릭 방지 플래그

// --- P6: 첫 실행(패키징 exe)에서 백엔드 자동 sync 타이밍 때문에
//         "썸네일 없는 HTML"이 먼저 렌더링되는 문제를 완화하기 위한
//         짧은 재로드 리트라이(카드 존재 + thumb 0일 때만)
window._BOOT_RELOAD_MAX = 3;
window._BOOT_RELOAD_DELAY_MS = 450;

async function onBridgeReady() {
  if (_bridgeReadyOnce) return;
  _bridgeReadyOnce = true;
  window.detectBridge();
  hasBridge = window.hasBridge;
  try {
    // get_master/save_master/refresh_thumb/sync/get_current_index_path 가 준비될 때까지 대기
    await window.waitForApi([
      "get_master",
      "save_master",
      "refresh_thumb",
      "sync",
      "get_current_index_path",
    ]);
  } catch (e) {
    console.error(e);
    window.showStatus({
      level: "error",
      title: "브리지 준비 실패",
      lines: [String(e?.message || e)],
    });
    return;
  }

  // P5-1: 백엔드에서 현재 인덱스 파일의 실제 경로를 받아와 전역에 보관
  try {
    const res = await window.call("get_current_index_path");
    if (res && res.path) {
      // detectCurrentIndexPath()에서 두 번째 우선순위로 사용하는 값
      window.__CURRENT_INDEX_PATH = res.path;
    }
  } catch (e) {
    console.warn("get_current_index_path failed:", e);
  }

  await window.loadMaster({ retryThumbs: true, attempt: 0 });
}

document.addEventListener("DOMContentLoaded", async () => {
  window.detectBridge();
  hasBridge = window.hasBridge;
  if (!hasBridge) {

    const blocks = window.$$(".card", document);
    window.$("#content").innerHTML = "";

    if (blocks.length) {
      for (const block of blocks) window.$("#content").appendChild(block.cloneNode(true));
    } else {
      window.$("#content").innerHTML = `<p class="hint">브라우저 미리보기: <code>.card</code> 블록이 없습니다.</p>`;

    }
    window.enhanceBlocks();
    wireGlobalToolbar();

    // 브라우저 미리보기 모드에서도 보조 툴바가 있다면 연결
    if (typeof window.wireExtraToolbar === "function") {
      window.wireExtraToolbar();
    }

    // P5-1: 미리보기 모드에서도 경로 상태바 갱신
    window.updateIndexPathBar();

  } else {
    await window.loadMaster({ retryThumbs: true, attempt: 0 });
  }
});

window.addEventListener("pywebviewready", onBridgeReady);

(function pollBridge(maxMs = 3000, interval = 100) {
  const start = Date.now();
  const timer = setInterval(() => {
    if (window.pywebview && window.pywebview.api) {
      clearInterval(timer);
      onBridgeReady();
    } else if (Date.now() - start > maxMs) {
      clearInterval(timer);
    }
  }, interval);
})();


// 글로벌 툴바: Sync 전 선저장
function wireGlobalToolbar() {
  const btnSync = document.querySelector("#btnSync");
  if (!btnSync || btnSync.__wired) return;
  btnSync.__wired = true;

  // 초기 상태 정리
  btnSync.disabled = false;
  btnSync.setAttribute("aria-busy", "false");

  btnSync.addEventListener("click", async () => {
    if (!hasBridge) {
      return window.showStatus({ level: "warn", title: "데스크톱 앱에서만 동기화 가능합니다." });
    }

    // P5: 이미 동기화 중이면 클릭 무시
    if (_syncInProgress) {
      return;
    }

    _syncInProgress = true;
    btnSync.disabled = true;
    btnSync.setAttribute("aria-busy", "true");

    const hasCards = !!document.querySelector(".card");

    try {

      // 1) 현재 화면 상태 저장
      //    ✅ 카드가 하나도 없을 때는 "내용 없음" 플레이스홀더가 저장되지 않도록 선저장 생략
      if (hasCards) {
        await window.call("save_master", window.serializeMaster());
      }

      // 2) 백엔드 동기화
      window.showStatus({ level: "warn", title: "동기화 중…" });
      const r = await window.call("sync");
      window.renderSyncResult(r);
      // 3) 최신 상태 재로드
      await window.loadMaster({ retryThumbs: false, attempt: 0 });
    } catch (e) {
      console.error(e);
      window.showStatus({ level: "error", title: "동기화 실패", lines: [String(e?.message || e)] });
    } finally {
      _syncInProgress = false;
      btnSync.disabled = false;
      btnSync.setAttribute("aria-busy", "false");
    }
  });

}

// master_load.js에서 호출하므로 전역으로 노출
window.wireGlobalToolbar = wireGlobalToolbar;