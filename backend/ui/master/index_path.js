// ---- P5-1: 현재 인덱스 파일 경로 상태바 ---------------------------------

window.detectCurrentIndexPath = function detectCurrentIndexPath() {
  // 1) body data-index-path 우선
  const fromBody = document.body && document.body.dataset && document.body.dataset.indexPath;
  if (fromBody) return fromBody;

  // 2) 전역 변수로 제공되는 경우
  if (typeof window.__CURRENT_INDEX_PATH === "string" && window.__CURRENT_INDEX_PATH) {
    return window.__CURRENT_INDEX_PATH;
  }

  // 3) 브리지가 있으면 master_index 기준 기본값
  if (window.hasBridge) return "resource/master_index.html";

  // 4) 브라우저 미리보기 모드
  return "(미리보기 모드)";
};

window.ensureIndexPathBar = function ensureIndexPathBar() {
  let bar = window.$("#indexPathBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "indexPathBar";
    bar.className = "index-status"; // CSS는 ui.css / publish.css 등에서 정의

    const statusBar = window.$("#statusBar");
    const content = window.$("#content");

    // P5: 상태 메시지 바로 아래에 붙여서 "보조 정보" 느낌으로
    if (statusBar) {
      statusBar.insertAdjacentElement("afterend", bar);
    } else if (content) {
      content.insertAdjacentElement("beforebegin", bar);
    } else {
      document.body.insertAdjacentElement("afterbegin", bar);
    }
  }

  // 내부 구조는 한 번만 세팅
  if (!bar.__wired) {
    bar.__wired = true;
    bar.innerHTML = `
      <span id="indexPathText"></span>
      <span class="index-actions">
        <button id="btnOpenIndexFolder" class="btn btn-small" type="button">📂 폴더 열기</button>
      </span>
    `;

    const btnOpen = window.$("#btnOpenIndexFolder", bar);

    // 📂 인덱스 폴더 열기
    if (btnOpen) {
      btnOpen.addEventListener("click", async () => {
        if (!window.hasBridge) {
          window.showStatus({
            level: "warn",
            title: "데스크톱 앱에서만 폴더 열기 기능을 사용할 수 있습니다.",
          });
          return;
        }
        try {
          const info = await window.call("open_index_folder");
          if (info?.ok && info.path) {
            window.showStatus({
              level: "ok",
              title: "폴더 열림",
              lines: [info.path],
              autoHideMs: 2500,
            });
          } else {
            const msg =
              (info && (info.error || (info.errors && info.errors[0]))) ||
              "폴더를 열 수 없습니다.";
            window.showStatus({
              level: "error",
              title: "폴더 열기 실패",
              lines: [msg],
            });
          }
        } catch (e) {
          window.showStatus({
            level: "error",
            title: "폴더 열기 예외",
            lines: [String(e?.message || e)],
          });
        }
      });
    }
  }

  return bar;
};

window.updateIndexPathBar = function updateIndexPathBar(extraText) {
  const bar = window.ensureIndexPathBar();
  const path = window.detectCurrentIndexPath();
  const labelEl = window.$("#indexPathText", bar);
  const text = extraText
    ? `현재 파일: ${path} ${extraText}`
    : `현재 파일: ${path}`;

  if (labelEl) {
    labelEl.textContent = text;
  } else {
    bar.textContent = text;
  }
};