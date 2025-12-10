// master.js
const $ = (selector, el = document) => el.querySelector(selector);
const $$ = (selector, el = document) => Array.from(el.querySelectorAll(selector));

let _loadingMaster = false;
let _bridgeReadyOnce = false;
let hasBridge = false;
let _statusTimer = null;
let _metaSaveTimer = null;
let _syncInProgress = false; // P5: Sync 중복 클릭 방지 플래그


// --- paste modifier 키 상태 추적 (Shift/Alt 감지) ---
const __pasteMods = { shift: false, alt: false };
window.addEventListener("keydown", (evt) => {
  if (evt.key === "Shift") __pasteMods.shift = true;
  if (evt.key === "Alt") __pasteMods.alt = true;
});
window.addEventListener("keyup", (evt) => {
  if (evt.key === "Shift") __pasteMods.shift = false;
  if (evt.key === "Alt") __pasteMods.alt = false;
});
window.addEventListener("blur", () => { __pasteMods.shift = __pasteMods.alt = false; });

// --- escape 유틸 ---
function escapeHTML(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

// --- 외부 링크 버튼화 & 보안 속성 보강 ---
function decorateExternalLinks(scopeEl) {
  const links = scopeEl.querySelectorAll('a[href]');
  links.forEach(anchor => {

    let href = (anchor.getAttribute('href') || '').trim();
    // 스킴이 없고, www. 또는 도메인 형태라면 https:// 보강
    if (!/^(?:https?:\/\/|mailto:|tel:|#|\/|\.\.\/)/i.test(href)) {
      if (/^(?:www\.|(?:[a-z0-9-]+\.)+[a-z]{2,})/i.test(href)) {
        href = `https://${href}`;
        anchor.setAttribute('href', href);
      }
    }
    if (!/^https?:\/\//i.test(href)) return; // 외부 http(s)만 버튼화 대상
    anchor.setAttribute('target', '_blank');

    // 기존 rel 유지 + 보안 속성 보장
    const relSet = new Set(((anchor.getAttribute('rel') || '')).split(/\s+/).filter(Boolean));
    relSet.add('noopener'); relSet.add('noreferrer');
    anchor.setAttribute('rel', Array.from(relSet).join(' '));
    // 버튼 스타일(있으면 유지)
    anchor.classList.add('btn', 'btnExternal');
    // 라벨이 비어있으면 도메인으로 기본 라벨
    if (!anchor.textContent.trim()) {
      try {
        const urlObj = new URL(href);
        anchor.textContent = `열기 (${urlObj.hostname})`;
      } catch { /* noop */ }
    }
  });
}

// --- 텍스트 속 URL을 자동으로 <a>로 감싸기 ---
function autoLinkify(scopeEl) {
  // 1) http(s)://...  2) www.example.com/...  3) example.com/...
  const urlRe = /\b(?:https?:\/\/[^\s<>"']+|www\.[^\s<>"']+|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/[^\s<>"']*)?)/gi;

  const walker = document.createTreeWalker(
    scopeEl,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        const nodeText = node.nodeValue;
        if (!nodeText) return NodeFilter.FILTER_REJECT;

        // ✅ 1) HTML 엔티티/태그 기호가 섞인 텍스트는 건너뜀
        if (/[<>]/.test(nodeText) || /&lt;|&gt;/i.test(nodeText)) return NodeFilter.FILTER_REJECT;

        // URL 패턴이 없으면 스킵
        if (!urlRe.test(nodeText)) return NodeFilter.FILTER_REJECT;

        // a/pre/code/script/style 내부는 건너뜀
        const parentEl = node.parentElement;
        if (parentEl && parentEl.closest('a, pre, code, script, style')) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    }
  );

  const nodes = [];
  let node;
  while ((node = walker.nextNode())) nodes.push(node);

  nodes.forEach(textNode => {
    const rawText = textNode.nodeValue;

    // ✅ 2) 따옴표 안 구간 범위 미리 수집 → 그 안의 매치는 스킵
    const quoteRanges = [];
    const quoteRe = /"[^"]*"|'[^']*'/g;
    let quoteMatch;
    while ((quoteMatch = quoteRe.exec(rawText)) !== null) {
      quoteRanges.push([quoteMatch.index, quoteMatch.index + quoteMatch[0].length]); // [start, end)
    }
    const inQuoted = (idx) => quoteRanges.some(([startIdx, endIdx]) => idx >= startIdx && idx < endIdx);

    urlRe.lastIndex = 0;

    let match;
    let lastIdx = 0;
    const frag = document.createDocumentFragment();

    while ((match = urlRe.exec(rawText)) !== null) {
      const start = match.index;
      const end = start + match[0].length;

      // 따옴표 안이면 링크화하지 않고 건너뜀
      if (inQuoted(start)) continue;

      if (start > lastIdx) {
        frag.appendChild(document.createTextNode(rawText.slice(lastIdx, start)));
      }

      const raw = match[0];

      // href 정규화: 스킴이 없으면 https:// 보강
      let href = raw;
      if (!/^(?:https?:\/\/|mailto:|tel:)/i.test(raw)) {
        href = /^\/\//.test(raw) ? `https:${raw}` : `https://${raw}`;
      }

      const anchor = document.createElement('a');
      anchor.href = href;                // 실제 링크는 정규화된 href
      anchor.textContent = raw;          // 화면에는 사용자가 쓴 원문 표시
      anchor.target = '_blank';
      anchor.rel = 'noopener noreferrer';
      anchor.classList.add('btn', 'btnExternal');
      frag.appendChild(anchor);

      lastIdx = end;
    }

    // 남은 꼬리 텍스트
    if (lastIdx < rawText.length) {
      frag.appendChild(document.createTextNode(rawText.slice(lastIdx)));
    }

    // 매치가 하나도 없고 변경도 없으면 교체 불필요
    if (frag.childNodes.length === 0) return;

    textNode.replaceWith(frag);
  });
}

// ---- Status UI helpers -------------------------------------------------
function ensureStatusUI() {
  let bar = $("#statusBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "statusBar";
    bar.className = "status hidden"; // CSS: .status{padding:.6rem;border-radius:.5rem;margin:.5rem 0}
    $("#content").insertAdjacentElement("beforebegin", bar);
  }

  let details = $("#statusDetails");
  if (!details) {
    details = document.createElement("div");
    details.id = "statusDetails";
    details.className = "status-details hidden";
    bar.insertAdjacentElement("afterend", details);
  }
  return { bar, details };
}

function clearStatus() {
  if (_statusTimer) { clearTimeout(_statusTimer); _statusTimer = null; }
  const { bar, details } = ensureStatusUI();
  bar.className = "status hidden";
  bar.textContent = "";
  details.className = "status-details hidden";
  details.innerHTML = "";
}

function showStatus({ level, title, lines = [], errors = [], metrics = null, autoHideMs = null }) {
  if (_statusTimer) { clearTimeout(_statusTimer); _statusTimer = null; }

  const { bar, details } = ensureStatusUI();

  bar.className = `status status--${level || "ok"}`;
  bar.innerHTML = `<strong>${title || ""}</strong>`;
  bar.classList.remove("hidden");

  const parts = [];
  if (metrics) {
    const mm = [];
    if (metrics.blocksUpdated != null) mm.push(`반영 ${metrics.blocksUpdated}건`);
    if (metrics.foldersAdded != null && metrics.foldersAdded > 0) mm.push(`신규 ${metrics.foldersAdded}건`);
    if (metrics.durationMs != null) mm.push(`${metrics.durationMs}ms`);
    if (mm.length) parts.push(mm.join(" · "));
  }
  if (Array.isArray(lines) && lines.length) parts.push(...lines);
  if (Array.isArray(errors) && errors.length) {
    parts.push(`<details open><summary>오류 ${errors.length}개</summary><ul>` +
      errors.map(err => `<li>${err}</li>`).join("") + `</ul></details>`);
  }

  if (parts.length) {
    details.innerHTML = parts.map(p => `<div>${p}</div>`).join("");
    details.classList.remove("hidden");
  } else {
    details.classList.add("hidden");
    details.innerHTML = "";
  }

  if (typeof autoHideMs === "number" && autoHideMs > 0) {
    _statusTimer = setTimeout(() => {
      _statusTimer = null;
      clearStatus();
    }, autoHideMs);
  }
}

function renderSyncResult(result) {
  const scanOk = !!result.scanOk;
  const pushOk = !!result.pushOk;

  const pureOk =
    !!result.ok &&
    scanOk &&
    pushOk &&
    (!result.errors || result.errors.length === 0);

  // 1) 완전 성공 + 변경 요약
  if (pureOk) {
    showStatus({
      level: "ok",
      title: "인덱스 동기화 완료",
      lines: ["자료 목록을 resource 폴더와 다시 맞췄어요."],
      errors: [],
      // metrics.blocksUpdated / foldersAdded / durationMs 는 기존 포맷으로 그대로 표시
      metrics: result.metrics || null,
      autoHideMs: 2500,
    });
    return;
  }

  // 2) 부분 성공 / 경고 케이스용 문장들 먼저 준비
  const lines = [];

  // 썸네일 스캔 측 문제
  if (result.scanOk === false) {
    lines.push("일부 폴더의 썸네일을 만들지 못했습니다.");
  }

  // 인덱스 파일 반영 측 문제
  if (result.pushOk === false) {
    lines.push("인덱스 파일을 저장하는 과정에서 오류가 있었습니다.");
  }

  // scanOk / pushOk 는 모두 true인데, errors만 있는 경우 등
  if (!lines.length) {
    lines.push("동기화 과정에서 추가 경고 또는 오류가 감지되었습니다.");
  }

  // 2-a) 부분 성공: ok 이지만 일부 단계 실패/경고
  if (result.ok) {
    showStatus({
      level: "warn",
      title: "동기화는 되었지만 일부 작업이 실패했습니다",
      lines,
      errors: result.errors || [],
      metrics: result.metrics || null,
    });
    return;
  }

  // 3) 전체 실패: 스캔/저장 쪽이 실제로 깨진 경우
  const errLines = [];
  if (!scanOk) {
    errLines.push("resource 폴더를 다시 스캔하는 중 문제가 생겼습니다.");
  }
  if (!pushOk) {
    errLines.push("인덱스 파일을 저장하는 중 문제가 생겼습니다.");
  }
  if (!errLines.length) {
    errLines.push("동기화 중 알 수 없는 오류가 발생했습니다.");
  }

  showStatus({
    level: "error",
    title: "동기화 중 오류가 발생했습니다",
    lines: errLines,
    errors: result.errors || [],
    metrics: result.metrics || null,
  });
}

// ---- P5-1: 현재 인덱스 파일 경로 상태바 ---------------------------------

function detectCurrentIndexPath() {
  // 1) body data-index-path 우선
  const fromBody = document.body && document.body.dataset && document.body.dataset.indexPath;
  if (fromBody) return fromBody;

  // 2) 전역 변수로 제공되는 경우
  if (typeof window.__CURRENT_INDEX_PATH === "string" && window.__CURRENT_INDEX_PATH) {
    return window.__CURRENT_INDEX_PATH;
  }

  // 3) 브리지가 있으면 master_index 기준 기본값
  if (hasBridge) return "resource/master_index.html";

  // 4) 브라우저 미리보기 모드
  return "(미리보기 모드)";
}

function ensureIndexPathBar() {
  let bar = $("#indexPathBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "indexPathBar";
    bar.className = "index-status"; // CSS는 ui.css / publish.css 등에서 정의

    const statusBar = $("#statusBar");
    const content = $("#content");

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

    const btnOpen = $("#btnOpenIndexFolder", bar);

    // 📂 인덱스 폴더 열기
    if (btnOpen) {
      btnOpen.addEventListener("click", async () => {
        if (!hasBridge) {
          showStatus({
            level: "warn",
            title: "데스크톱 앱에서만 폴더 열기 기능을 사용할 수 있습니다.",
          });
          return;
        }
        try {
          const info = await call("open_index_folder");
          if (info?.ok && info.path) {
            showStatus({
              level: "ok",
              title: "폴더 열림",
              lines: [info.path],
              autoHideMs: 2500,
            });
          } else {
            const msg =
              (info && (info.error || (info.errors && info.errors[0]))) ||
              "폴더를 열 수 없습니다.";
            showStatus({
              level: "error",
              title: "폴더 열기 실패",
              lines: [msg],
            });
          }
        } catch (e) {
          showStatus({
            level: "error",
            title: "폴더 열기 예외",
            lines: [String(e?.message || e)],
          });
        }
      });
    }
  }

  return bar;
}

function updateIndexPathBar(extraText) {
  const bar = ensureIndexPathBar();
  const path = detectCurrentIndexPath();
  const labelEl = $("#indexPathText", bar);
  const text = extraText
    ? `현재 파일: ${path} ${extraText}`
    : `현재 파일: ${path}`;

  if (labelEl) {
    labelEl.textContent = text;
  } else {
    bar.textContent = text;
  }
}

function detectBridge() {
  // API 객체가 있고, 키도 하나 이상 있어야 "실제 준비됨"으로 판단
  const api = (window.pywebview && window.pywebview.api) || null;
  hasBridge = !!api;

  $("#readonlyNote")?.classList.toggle("hidden", hasBridge);
  const toolbar = $("#globalToolbar");
  if (toolbar) toolbar.style.visibility = hasBridge ? "visible" : "hidden";
}

// API 준비를 보장하는 유틸: 특정 메서드들이 function이 될 때까지 대기
async function waitForApi(methods = [], timeoutMs = 3000, interval = 50) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    (function check() {
      const api = (window.pywebview && window.pywebview.api) || null;
      const ok =
        !!api &&
        (methods.length === 0 ||
          methods.every((m) => typeof api[m] === "function"));
      if (ok) return resolve(api);
      if (Date.now() - start > timeoutMs) {
        return reject(new Error("API not ready within timeout"));
      }
      setTimeout(check, interval);
    })();
  });
}


async function onBridgeReady() {
  if (_bridgeReadyOnce) return;
  _bridgeReadyOnce = true;
  detectBridge();
  try {
    // get_master/save_master/refresh_thumb/sync/get_current_index_path 가 준비될 때까지 대기
    await waitForApi([
      "get_master",
      "save_master",
      "refresh_thumb",
      "sync",
      "get_current_index_path",
    ]);
  } catch (e) {
    console.error(e);
    showStatus({
      level: "error",
      title: "브리지 준비 실패",
      lines: [String(e?.message || e)],
    });
    return;
  }

  // P5-1: 백엔드에서 현재 인덱스 파일의 실제 경로를 받아와 전역에 보관
  try {
    const res = await call("get_current_index_path");
    if (res && res.path) {
      // detectCurrentIndexPath()에서 두 번째 우선순위로 사용하는 값
      window.__CURRENT_INDEX_PATH = res.path;
    }
  } catch (e) {
    console.warn("get_current_index_path failed:", e);
  }

  await loadMaster();
}

document.addEventListener("DOMContentLoaded", async () => {
  detectBridge();
  if (!hasBridge) {
    const blocks = $$(".card", document);
    $("#content").innerHTML = "";
    if (blocks.length) {
      for (const block of blocks) $("#content").appendChild(block.cloneNode(true));
    } else {
      $("#content").innerHTML = `<p class="hint">브라우저 미리보기: <code>.card</code> 블록이 없습니다.</p>`;
    }
    enhanceBlocks();
    wireGlobalToolbar();

    // 브라우저 미리보기 모드에서도 보조 툴바가 있다면 연결
    if (typeof window.wireExtraToolbar === "function") {
      window.wireExtraToolbar();
    }

    // P5-1: 미리보기 모드에서도 경로 상태바 갱신
    updateIndexPathBar();

  } else {
    await loadMaster();
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

async function call(method, ...args) {
  // 1) 대상 메서드가 실제 function이 될 때까지 대기하고 api 핸들 확보
  let api;
  try {
    api = await waitForApi([method], 3000);
  } catch (e) {
    // 타임아웃/미준비 시 더 읽기 쉬운 에러 메시지
    const keys = Object.keys((window.pywebview && window.pywebview.api) || {});
    throw new Error(
      `pywebview bridge not available or '${method}' not ready: ${e?.message || e}. ` +
      `Available methods now: [${keys.join(", ")}]`
    );
  }

  // 2) 안전하게 메서드 호출
  const fn = api[method];
  if (typeof fn !== "function") {
    const keys = Object.keys(api || {});
    throw new Error(
      `window.pywebview.api["${method}"] is not a function. ` +
      `Available: ${keys.join(", ")}`
    );
  }

  try {
    return await fn(...args);
  } catch (err) {
    console.error(`[bridge:${method}]`, err);
    throw err;
  }
}

// ---- 메타 자동 저장(디바운스) --------------------------------------------
function queueMetaSave() {
  if (!hasBridge) return; // 브라우저 미리보기 모드에서는 생략
  if (_metaSaveTimer) clearTimeout(_metaSaveTimer);
  _metaSaveTimer = setTimeout(async () => {
    try {
      // 메타만 바뀐 경우에도 전체 직렬화로 저장(간단/일관)
      await call("save_master", serializeMaster());
      showStatus({ level: "ok", title: "변경사항 저장", autoHideMs: 1200 });
    } catch (e) {
      console.error(e);
      showStatus({ level: "error", title: "저장 실패", lines: [String(e?.message || e)] });
    } finally {
      _metaSaveTimer = null;
    }
  }, 500);
}

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
      return showStatus({ level: "warn", title: "데스크톱 앱에서만 동기화 가능합니다." });
    }

    // P5: 이미 동기화 중이면 클릭 무시
    if (_syncInProgress) {
      return;
    }

    _syncInProgress = true;
    btnSync.disabled = true;
    btnSync.setAttribute("aria-busy", "true");

    try {
      // 1) 현재 화면 상태 저장
      await call("save_master", serializeMaster());
      // 2) 백엔드 동기화
      showStatus({ level: "warn", title: "동기화 중…" });
      const r = await call("sync");
      renderSyncResult(r);
      // 3) 최신 상태 재로드
      await loadMaster();
    } catch (e) {
      console.error(e);
      showStatus({ level: "error", title: "동기화 실패", lines: [String(e?.message || e)] });
    } finally {
      _syncInProgress = false;
      btnSync.disabled = false;
      btnSync.setAttribute("aria-busy", "false");
    }
  });

}

async function loadMaster() {
  if (_loadingMaster) return;
  _loadingMaster = true;
  try {
    if (hasBridge) {
      const { html } = await call("get_master");

      // 현재 인덱스 파일 절대 경로 업데이트
      try {
        const info = await call("get_current_index_path");
        if (info && info.path) {
          window.__CURRENT_INDEX_PATH = info.path;
        }
      } catch (e) {
        console.warn("get_current_index_path failed", e);
      }

      $("#content").innerHTML = html || "<p>내용 없음</p>";
    } else {
      const blocks = $$(".card", document);
      $("#content").innerHTML = "";
      if (blocks.length) {
        for (const block of blocks) $("#content").appendChild(block.cloneNode(true));
      } else {
        $("#content").innerHTML = `<p class="hint">브라우저 미리보기: <code>.card</code> 블록이 없습니다.</p>`;
      }
    }

    // P5-1: 매번 로드 후 현재 파일 경로 표시
    updateIndexPathBar();
    enhanceBlocks();
    wireGlobalToolbar();

    // toolbar.js가 제공하는 보조 툴바 바인딩(재빌드/프룬 등)
    if (typeof window.wireExtraToolbar === "function") {
      window.wireExtraToolbar();
    }

  } catch (exc) {
    console.error(exc);
    showStatus({ level: "error", title: "로드 실패", lines: [String(exc?.message || exc)] });
  } finally {
    _loadingMaster = false;
  }
}

function enhanceBlocks() {
  $$(".card").forEach(div => {
    if (div.__enhanced) return;

    function updateHiddenUI(div, btnToggleHidden) {
      const isHidden = ((div.getAttribute("data-hidden") || "").trim().toLowerCase() === "true");
      // 클래스(시각) 동기화
      div.classList.toggle("is-hidden", isHidden);
      // 버튼 라벨/상태 동기화
      if (btnToggleHidden) {
        btnToggleHidden.textContent = isHidden ? "숨김 해제" : "숨김";
        btnToggleHidden.setAttribute("aria-pressed", String(isHidden));
        btnToggleHidden.title = isHidden ? "숨김을 해제합니다" : "이 카드를 숨깁니다";

        // 옵션: 숨김 중 편집/저장 비활성
        const actions = div.querySelector(".card-actions");
        actions?.querySelector(".btnEditOne") && (actions.querySelector(".btnEditOne").disabled = isHidden);
        actions?.querySelector(".btnSaveOne") && (actions.querySelector(".btnSaveOne").disabled = isHidden);
      }
    }

    // --- 초기 메타 표시: data-* → 클래스 반영 (재로드/Sync 후에도 시각 상태 유지)
    (function applyMetaFromData(el) {
      const hidden = (el.getAttribute("data-hidden") || "").trim().toLowerCase() === "true";
      // hidden은 버튼이 만들어진 뒤에 라벨까지 맞춰줘야 하므로 여기서는 클래스만 예비 반영(옵션)
      el.classList.toggle("is-hidden", hidden);
    })(div);

    // head: h2 → actions → thumb-wrap 순서 보정
    function normalizeHead(headEl) {
      const h2 = $("h2", headEl);
      let actions = $(".card-actions", headEl);
      let thumbWrap = $(".thumb-wrap", headEl);

      if (!actions) {
        actions = document.createElement("div");
        actions.className = "card-actions" + (hasBridge ? "" : " hidden");
        actions.innerHTML = `
          <button class="btn btnEditOne">편집</button>
          <button class="btn btnSaveOne" disabled>저장</button>
          <button class="btn btnCancelOne" disabled>취소</button>
          <button class="btn btnThumb">썸네일 갱신</button>
          <button class="btn btnToggleHidden">숨김</button>
          <button class="btn btnOpenFolder">폴더 열기</button>
          <button class="btn btnToggleDelete">삭제</button>
        `;
      } else {
        // P5-2: 기존 마크업에 취소 버튼이 없다면 추가(하위호환)
        if (!actions.querySelector(".btnCancelOne")) {
          const cancelBtn = document.createElement("button");
          cancelBtn.className = "btn btnCancelOne";
          cancelBtn.textContent = "취소";
          cancelBtn.disabled = true;
          const saveBtn = actions.querySelector(".btnSaveOne");
          if (saveBtn && saveBtn.nextSibling) {
            saveBtn.insertAdjacentElement("afterend", cancelBtn);
          } else if (saveBtn) {
            actions.appendChild(cancelBtn);
          } else {
            // 이론상 없겠지만, 그래도 actions 안 첫 번째에 넣어둠
            actions.insertBefore(cancelBtn, actions.firstChild);
          }
        }

        // P5: 기존 마크업에 폴더 버튼이 없다면 추가
        if (!actions.querySelector(".btnOpenFolder")) {
          const folderBtn = document.createElement("button");
          folderBtn.className = "btn btnOpenFolder";
          folderBtn.textContent = "폴더 열기";
          actions.appendChild(folderBtn);
        }
      }

      if (h2) headEl.appendChild(h2);

      // 기존 메타 라벨 제거 후, data-created-at 기반 생성일 표시
      headEl.querySelectorAll(".card-meta").forEach(el => el.remove());
      const cardEl = headEl.closest(".card");
      const createdRaw = (cardEl?.getAttribute("data-created-at") || "").trim();
      if (createdRaw) {
        const metaSpan = document.createElement("span");
        metaSpan.className = "card-meta";
        // YYYY-MM-DD까지만 표시
        metaSpan.textContent = createdRaw.slice(0, 10);
        if (h2 && h2.parentNode === headEl) {
          h2.insertAdjacentElement("afterend", metaSpan);
        } else {
          headEl.appendChild(metaSpan);
        }
      }

      headEl.appendChild(actions);

      if (thumbWrap) headEl.appendChild(thumbWrap);
      return { actions, thumbWrap };
    }

    // .card-head 구성 없으면 생성
    const hasHead = !!div.querySelector(".card-head");
    if (!hasHead) {
      const h2 = $("h2", div);
      if (!h2) return;

      const head = document.createElement("div");
      head.className = "card-head";
      h2.replaceWith(head);
      head.appendChild(h2);
      let { thumbWrap } = normalizeHead(head);

      // head 다음 형제 중 썸네일 후보를 thumb-wrap으로 이동
      let sibling = head.nextSibling;
      while (sibling) {
        const nextSibling = sibling.nextSibling;
        if (
          sibling.nodeType === 1 && sibling.matches &&
          (sibling.matches("img.thumb, img[alt='썸네일']") ||
            (sibling.tagName === "IMG" && /\/thumbs\//.test(sibling.getAttribute("src") || "")))
        ) {
          if (!thumbWrap) {
            thumbWrap = document.createElement("div");
            thumbWrap.className = "thumb-wrap";
            head.appendChild(thumbWrap);
          }
          thumbWrap.appendChild(sibling);
        }
        sibling = nextSibling;
      }

      // .inner 생성 및 나머지 내용을 .inner로 이동
      let innerEl = $(".inner", div);
      if (!innerEl) {
        innerEl = document.createElement("div");
        innerEl.className = "inner";
        const leftovers = [];
        let moveNode = head.nextSibling;
        while (moveNode) { leftovers.push(moveNode); moveNode = moveNode.nextSibling; }
        leftovers.forEach(nd => innerEl.appendChild(nd));
        div.appendChild(innerEl);
      }

      // .inner 안으로 들어간 썸네일이 있다면 다시 head로
      const stray = $(".inner img.thumb, .inner img[alt='썸네일'], .inner img[src*='/thumbs/']", div);
      if (stray) {
        let tw = $(".thumb-wrap", head);
        if (!tw) {
          tw = document.createElement("div");
          tw.className = "thumb-wrap";
          head.appendChild(tw);
        }
        tw.appendChild(stray);
      }

    } else {
      const head = $(".card-head", div);
      normalizeHead(head);
    }

    // 제목/썸네일은 편집 제외
    const title = $(".card-head h2", div);
    let thumbWrap = $(".thumb-wrap", div);
    title?.setAttribute("contenteditable", "false");
    title?.setAttribute("draggable", "false");
    thumbWrap?.setAttribute("contenteditable", "false");
    thumbWrap?.setAttribute("draggable", "false");
    thumbWrap?.querySelectorAll("*").forEach(el => {
      el.setAttribute("contenteditable", "false");
      el.setAttribute("draggable", "false");
    });

    // --- 썸네일 img 경로 표준화 ---
    //   - 원본 HTML에 들어 있는 src를 최대한 그대로 신뢰한다.
    //   - data-thumb-src 에는 "자연속재료로 표현하기/thumbs/자연속재료로_표현하기.jpg" 같은
    //     상대 경로만 저장하고, 표시용 src는 "../../resource/..." 로만 바꾼다.
    if (thumbWrap) {
      const img = thumbWrap.querySelector("img");
      if (img) {
        let storedSrc = img.getAttribute("data-thumb-src");

        if (!storedSrc) {
          // 1) 현재 src에서 ../../resource/ 프리픽스, 쿼리스트링 제거
          let raw = img.getAttribute("src") || "";
          // 쿼리 파라미터 제거
          raw = raw.split("?")[0];

          // ../../resource/ 또는 ./resource/ 또는 resource/ 같은 앞부분 제거
          raw = raw
            .replace(/^(\.\.\/)+resource\//, "")
            .replace(/^\.\/?resource\//, "")
            .replace(/^resource\//, "");

          // "…/thumbs/…jpg" 꼴이면 그대로 사용
          if (/\/thumbs\/[^\/]+\.(jpe?g|png|webp)$/i.test(raw)) {
            storedSrc = raw;
          }
        }

        // 2) 그래도 못 찾았을 때만 최후의 수단으로 folderName 기반 추정
        if (!storedSrc) {
          const folderName = div.getAttribute("data-card") || (title?.textContent || "").trim();
          if (folderName) {
            // ★ 여기서는 예전 동작과의 하위호환용 "추정값"일 뿐,
            //    실제로는 대부분 위의 raw 경로에서 이미 구해질 것이다.
            storedSrc = `${folderName}/thumbs/${safeThumbName(folderName)}.jpg`;
          }
        }

        if (storedSrc) {
          img.setAttribute("data-thumb-src", storedSrc);
          // 브리지 여부와 관계없이 항상 resource 기준 경로로 교정
          img.src = `../../resource/${storedSrc}`;
        }
      }
    }

    // 버튼/inner 참조
    const actions = $(".card-head .card-actions", div);
    const inner = $(".inner", div);

    // URL 오토링크 + 버튼화(초기 표시 시 1회)
    autoLinkify(inner);
    decorateExternalLinks(inner);

    const folder = div.getAttribute("data-card") || (title?.textContent || "").trim();
    const btnEditOne = $(".btnEditOne", actions);
    const btnSaveOne = $(".btnSaveOne", actions);
    const btnCancelOne = $(".btnCancelOne", actions);
    const btnThumb = $(".btnThumb", actions);

    const btnToggleHidden = $(".btnToggleHidden", actions);
    const btnDelete = $(".btnToggleDelete", actions);
    const btnOpenFolder = $(".btnOpenFolder", actions);

    // --- 카드별 폴더 열기 ---
    if (btnOpenFolder) {
      btnOpenFolder.onclick = async () => {
        if (!folder) {
          alert("이 카드에 연결된 폴더 이름을 찾을 수 없습니다.");
          return;
        }
        if (!hasBridge) {
          alert("폴더 열기는 데스크톱 앱에서만 가능합니다.");
          return;
        }
        try {
          const res = await call("open_folder", folder);
          if (!res?.ok) {
            const msg = res?.error || "폴더를 열 수 없습니다.";
            showStatus({
              level: "error",
              title: "폴더 열기 실패",
              lines: [msg],
            });
          } else {
            // 성공 시에는 굳이 상태바에 안 띄워도 되고,
            // 필요하면 아래처럼 한 줄 정도만:
            showStatus({
              level: "ok",
              title: "폴더 열림",
              lines: [res.path || folder],
              autoHideMs: 2000,
            });
          }
        } catch (e) {
          showStatus({
            level: "error",
            title: "폴더 열기 예외",
            lines: [String(e?.message || e)],
          });
        }
      };
    }

    // --- P3-2: 숨김 토글 ---
    if (btnToggleHidden) {

      updateHiddenUI(div, btnToggleHidden);

      btnToggleHidden.onclick = () => {
        const curr = (div.getAttribute("data-hidden") || "").trim().toLowerCase() === "true";
        const next = !curr;
        div.setAttribute("data-hidden", String(next));
        updateHiddenUI(div, btnToggleHidden); // 라벨/클래스 같이 갱신
        queueMetaSave();                       // 저장(→ master_content에 반영됨)
      };
    }

    if (btnDelete) {
      btnDelete.textContent = "삭제";
      btnDelete.onclick = async () => {
        if (!hasBridge) return alert("삭제는 데스크톱 앱에서만 가능합니다.");

        const cardId = div.getAttribute("data-card-id");
        const cardTitle = (div.getAttribute("data-card") || title?.textContent || "").trim();

        if (!cardId) {
          return alert("card_id가 없어 삭제할 수 없습니다(동기화 후 다시 시도).");
        }

        const ok = confirm(
          `정말 삭제할까요?\n\n- 제목: ${cardTitle}\n- ID: ${cardId}\n\n폴더 및 자료가 영구 삭제됩니다.`
        );
        if (!ok) return;

        try {
          showStatus({ level: "warn", title: "삭제 중…", lines: [cardTitle] });

          const r = await call("delete_card_by_id", cardId);
          if (!r?.ok) {
            const errs = [];
            if (Array.isArray(r?.errors) && r.errors.length) {
              errs.push(...r.errors);
            } else if (r?.error) {
              errs.push(r.error);
            } else {
              errs.push(`삭제 실패(card_id=${cardId})`);
            }
            showStatus({
              level: "error",
              title: "삭제 실패",
              errors: errs,
            });
            return;
          }

          showStatus({
            level: "ok",
            title: "삭제 완료",
            lines: [cardTitle],
            autoHideMs: 4000,
          });

          await loadMaster();
        } catch (exc) {
          console.error(exc);
          showStatus({
            level: "error",
            title: "삭제 예외",
            errors: [String(exc?.message || exc)],
          });
        }
      };
    }

    // --- 붙여넣기 핸들러 (중복 제거, escape 유틸 사용) ---
    if (inner && !inner.__pasteWired) {
      inner.addEventListener("paste", (evt) => {
        try {
          if (!evt.clipboardData) return;

          // Shift/Alt 누르면 "문자 그대로 붙여넣기" 모드
          const forceLiteral = __pasteMods.shift || __pasteMods.alt;

          // 1) HTML 클립보드가 있고 literal이 아니면 → 그대로 삽입
          const html = evt.clipboardData.getData("text/html");
          if (html && !forceLiteral) {
            evt.preventDefault();
            document.execCommand("insertHTML", false, html);
            return;
          }

          // 2) 평문 처리
          const raw = evt.clipboardData.getData("text/plain");
          if (!raw) return;

          const hasLiteralTags = /<[^>]+>/.test(raw);      // <h2>...</h2>
          const hasEscapedTags = /&lt;[^&]+&gt;/.test(raw);// &lt;h2&gt;...&lt;/h2&gt;
          const hasCodeFence = /(^|\n)```/.test(raw);      // 코드펜스

          // 2-A) 문자 그대로 붙여넣기(코드펜스 or 강제 literal)
          if (forceLiteral || hasCodeFence) {
            evt.preventDefault();
            const stripped = raw.replace(/(^|\n)```([\s\S]*?)```/g, (_, pre, body) => pre + body);
            const literal = escapeHTML(stripped);
            document.execCommand("insertHTML", false, `<pre><code>${literal}</code></pre>`);
            return;
          }

          // 2-B) 태그형 텍스트를 실제 HTML로 삽입 (보안 필터 포함)
          if (hasLiteralTags || hasEscapedTags) {
            evt.preventDefault();

            // &lt;…&gt; → 언이스케이프
            let decoded = raw;
            if (hasEscapedTags) {
              const ta = document.createElement("textarea");
              ta.innerHTML = raw;
              decoded = ta.value;
            }

            // 브라우저 파서로 DOM 구성
            const divTmp = document.createElement("div");
            divTmp.innerHTML = decoded;

            // 간이 sanitizer: 허용/금지 + 속성 필터
            const allowed = new Set(["P", "BR", "IMG", "A", "UL", "OL", "LI", "H1", "H2", "H3", "H4", "STRONG", "EM", "SPAN", "DIV", "FIGURE", "FIGCAPTION"]);
            const danger = new Set(["SCRIPT", "STYLE", "IFRAME", "OBJECT", "EMBED", "LINK", "FORM", "INPUT", "BUTTON", "VIDEO", "AUDIO"]);

            divTmp.querySelectorAll(Array.from(danger).join(",")).forEach(n => n.remove());
            divTmp.querySelectorAll("*").forEach(el => {
              [...el.attributes].forEach(attr => {
                const key = attr.name.toLowerCase();
                const val = (attr.value || "").trim().toLowerCase();
                if (key.startsWith("on") || key === "style" || key === "contenteditable" || key === "draggable" || key.startsWith("data-")) {
                  el.removeAttribute(attr.name);
                }
                if ((key === "href" || key === "src") && (val.startsWith("javascript:") || val.startsWith("data:"))) {
                  el.removeAttribute(attr.name);
                }
              });
              if (!allowed.has(el.tagName)) {
                const parent = el.parentNode;
                while (el.firstChild) parent.insertBefore(el.firstChild, el);
                parent.removeChild(el);
              }
            });

            // === 구조 보정: 헤딩 강등 + 고아 li 래핑 + 빈 태그 정리 ===
            (function demoteHeadings(root) {
              root.querySelectorAll("h1,h2").forEach(h => {
                const h3 = document.createElement("h3");
                h3.innerHTML = h.innerHTML;
                [...h.attributes].forEach(a => h3.setAttribute(a.name, a.value));
                h.replaceWith(h3);
              });
            })(divTmp);

            (function normalizeOrphanLis(root) {
              const orphanLis = Array.from(root.querySelectorAll("li")).filter(li => {
                const p = li.parentElement;
                return !(p && (p.tagName === "UL" || p.tagName === "OL"));
              });
              if (!orphanLis.length) return;

              let run = [];
              const flush = () => {
                if (!run.length) return;
                const ul = document.createElement("ul");
                run[0].parentNode.insertBefore(ul, run[0]);
                run.forEach(li => ul.appendChild(li));
                run = [];
              };

              const tree = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
              let cursor;
              while ((cursor = tree.nextNode())) {
                if (cursor.tagName === "LI" && orphanLis.includes(cursor)) {
                  run.push(cursor);
                } else if (run.length) {
                  flush();
                }
              }
              flush();
            })(divTmp);

            (function pruneEmpty(root) {
              root.querySelectorAll("p,div,span,figure,figcaption").forEach(el => {
                const html = (el.innerHTML || "").trim();
                if (!html || html === "<br>") {
                  el.remove();
                }
              });
            })(divTmp);

            document.execCommand("insertHTML", false, divTmp.innerHTML);
            return;
          }
          // 2-C) 그 외 평문은 기본 동작
        } catch (pasteErr) {
          console.warn("paste handler error", pasteErr);
        }
      });
      inner.__pasteWired = true;
    }

    // 기본 상태
    inner.contentEditable = "false";
    inner.classList.remove("editable");
    btnEditOne.disabled = false;
    btnSaveOne.disabled = true;
    if (btnCancelOne) btnCancelOne.disabled = true;

    // 편집 시작 (개별 카드)
    btnEditOne.onclick = () => {
      if (!hasBridge) return alert("편집은 데스크톱 앱에서만 가능합니다.");

      // P5-2: 현재 내용을 스냅샷으로 보관 (DOM 프로퍼티, data-* 아님)
      inner.__snapshotHtml = inner.innerHTML;

      inner.contentEditable = "true";
      inner.classList.add("editable");
      btnEditOne.disabled = true;
      btnSaveOne.disabled = false;
      if (btnCancelOne) btnCancelOne.disabled = false;
    };

    // P5-2: 편집 취소 (개별 카드)
    if (btnCancelOne) {
      btnCancelOne.onclick = () => {
        if (!inner.__snapshotHtml) return; // 스냅샷 없으면 취소 무시

        inner.innerHTML = inner.__snapshotHtml;
        delete inner.__snapshotHtml;

        inner.contentEditable = "false";
        inner.classList.remove("editable");
        btnEditOne.disabled = false;
        btnSaveOne.disabled = true;
        btnCancelOne.disabled = true;
      };
    }

    // 저장
    btnSaveOne.onclick = async () => {
      if (!hasBridge) return;
      btnSaveOne.disabled = true;
      try {
        // ✅ 저장 직전 전체 카드에 대해 오토링크/버튼화 보정
        $$(".card .inner").forEach(el => { autoLinkify(el); decorateExternalLinks(el); });

        await call("save_master", serializeMaster());
        await loadMaster(); // 저장된 내용으로 즉시 재로딩(렌더 상태 확인)
        showStatus({ level: "ok", title: "저장 완료", autoHideMs: 1800 });
        inner.contentEditable = "false";
        inner.classList.remove("editable");
        btnEditOne.disabled = false;
        btnSaveOne.disabled = true;

        // 저장 성공 시 스냅샷 폐기 + 취소 버튼 비활성화
        if (btnCancelOne) {
          btnCancelOne.disabled = true;
        }
        delete inner.__snapshotHtml;

      } catch (exc) {
        console.error(exc);
        showStatus({ level: "error", title: "저장 실패", lines: [String(exc?.message || exc)] });
        btnSaveOne.disabled = false;
      }
    };

    // 썸네일 갱신 (P5-썸네일 v2: 타입 순환 + 즉시 썸네일 리로드)
    btnThumb.onclick = async () => {
      if (!hasBridge) return alert("데스크톱 앱에서만 가능합니다.");
      btnThumb.disabled = true;
      showStatus({ level: "warn", title: "썸네일 갱신 중…", lines: [`${folder}`] });
      try {
        const result = await call("refresh_thumb", folder, 640);

        // 공통 헬퍼: DOM에서 썸네일 완전히 제거
        const removeThumbDom = () => {
          if (thumbWrap) {
            thumbWrap.remove();
            thumbWrap = null;
          }
        };

        if (result?.ok) {
          const srcRaw = result.source ?? null;
          const src = typeof srcRaw === "string" ? srcRaw.toLowerCase() : null;

          // ✅ 소스가 없다고 응답한 경우 (예: source:null) → 썸네일 제거 모드
          if (!src) {
            removeThumbDom();

            // DOM에서 썸네일 제거한 상태를 master_content/master_index에 저장
            queueMetaSave();

            showStatus({
              level: "ok",
              title: "썸네일 제거 완료",
              lines: [folder],
              autoHideMs: 1800,
            });
            return;
          }

          // ✅ 정상 생성 케이스: 백엔드가 알려주는 사용 소스 타입(image/pdf/video)을 상태바에 표시
          const srcLabel =
            src === "image" ? "이미지" :
              src === "pdf" ? "PDF" :
                src === "video" ? "동영상" :
                  null;

          const lines = [folder];
          if (srcLabel) {
            lines.push(`사용 소스: ${srcLabel}`);
          }

          // ✅ 썸네일 DOM이 없던 카드라면 새로 생성
          if (!thumbWrap) {
            const head = $(".card-head", div);
            if (head) {
              thumbWrap = document.createElement("div");
              thumbWrap.className = "thumb-wrap";
              const imgEl = document.createElement("img");
              imgEl.className = "thumb";
              imgEl.alt = "썸네일";
              thumbWrap.appendChild(imgEl);
              head.appendChild(thumbWrap);
            }
          }

          // ✅ img 엘리먼트 확보(없으면 새로 만듦)
          let img = thumbWrap && thumbWrap.querySelector("img");
          if (!img && thumbWrap) {
            img = document.createElement("img");
            img.className = "thumb";
            img.alt = "썸네일";
            thumbWrap.appendChild(img);
          }

          if (img) {
            const ts = Date.now().toString();

            // 1) 기본값은 기존 data-thumb-src (이미 enhanceBlocks에서 정리해둔 값)
            let storedSrc = img.getAttribute("data-thumb-src");

            // 2) 혹시 없으면 현재 src에서 다시 추출 시도
            if (!storedSrc) {
              let raw = img.getAttribute("src") || "";
              raw = raw.split("?")[0];
              raw = raw
                .replace(/^(\.\.\/)+resource\//, "")
                .replace(/^\.\/?resource\//, "")
                .replace(/^resource\//, "");
              if (/\/thumbs\/[^\/]+\.(jpe?g|png|webp)$/i.test(raw)) {
                storedSrc = raw;
              }
            }

            // 3) 그래도 없으면 최후 fallback으로 folder 기반 추정
            if (!storedSrc) {
              storedSrc = `${folder}/thumbs/${safeThumbName(folder)}.jpg`;
            }

            img.setAttribute("data-thumb-src", storedSrc);
            const displaySrc = `../../resource/${storedSrc}?_ts=${ts}`;
            img.src = displaySrc;
          }

          // ✅ 썸네일 변경 내용을 바로 master_content/master_index에 반영
          //   (소스가 없는 경우 썸네일 DOM 제거까지 포함한 상태로 저장)
          queueMetaSave();

          showStatus({
            level: "ok",
            title: "썸네일 갱신 완료",
            lines,
            autoHideMs: 1800,
          });
        } else {
          const msg = result?.error || "";

          // 이전 버전 호환용 (예전 서버가 "소스 이미지 없음" 문구를 줄 수도 있으니)
          const isNoSource =
            /소스 이미지 없음/.test(msg) ||
            /no source/i.test(msg);

          if (isNoSource) {
            removeThumbDom();
            queueMetaSave();
            showStatus({
              level: "ok",
              title: "썸네일 제거 완료",
              lines: [folder],
              autoHideMs: 1800,
            });
            return;
          }

          // 🔹 새 디버그 정보: source_type + tool
          const kindRaw = (result?.source_type || result?.source || "").toLowerCase();
          let srcLabel = null;
          if (kindRaw === "image") srcLabel = "이미지";
          else if (kindRaw === "pdf") srcLabel = "PDF";
          else if (kindRaw === "video") srcLabel = "동영상";

          const tool = result?.tool || null;

          const lines = [folder];
          if (srcLabel) {
            lines.push(`시도한 소스: ${srcLabel}`);
          }
          if (tool === "ffmpeg") {
            lines.push("필요 도구: ffmpeg (동영상 썸네일)");
          } else if (tool === "poppler") {
            lines.push("필요 도구: poppler (pdftoppm / pdfinfo, PDF 썸네일)");
          }

          const hint = msg ? [msg] : ["소스 이미지 없음 또는 변환 실패"];
          showStatus({
            level: "error",
            title: "썸네일 갱신 실패",
            lines,
            errors: hint,
          });
        }
      } catch (exc) {
        showStatus({
          level: "error",
          title: "썸네일 갱신 예외",
          lines: [folder],
          errors: [String(exc?.message || exc)],
        });
      } finally {
        btnThumb.disabled = false;
      }
    };

    div.__enhanced = true;
  });
}

function safeThumbName(name) {
  // Python _safe_name과 최대한 동일하게
  return name
    .normalize("NFKC")
    .replace(/[\s\u00A0\u202F\u2009\u2007\u2060]+/g, "_")
    .replace(/[\/\\:*?"<>|]/g, "_");
}

// 저장 직렬화: h2 + thumb-wrap + inner(본문)만 남기고, 버튼/편집속성 제거
function serializeMaster() {
  const rootClone = document.querySelector("#content").cloneNode(true);

  rootClone.querySelectorAll(".card").forEach(div => {
    const head = div.querySelector(".card-head");
    const inner = div.querySelector(".inner");
    if (!head || !inner) return;

    const titleEl = head.querySelector("h2");
    const thumbWrapEl = div.querySelector(".thumb-wrap");

    const clean = document.createElement("div");
    // --- 메타 클래스를 보존하여 저장 (is-hidden)
    const metaClasses = [];
    if (div.classList.contains("is-hidden")) metaClasses.push("is-hidden");
    clean.className = ["card", ...metaClasses].join(" ");

    // --- P3-2: 기존 data-* 메타 보존 ---
    [
      "data-card",
      "data-card-id",
      "data-hidden",
      "data-order",
      "data-created-at",
    ].forEach(attr => {
      const val = div.getAttribute(attr);
      if (val !== null && val !== "") clean.setAttribute(attr, val);
    });

    // h2 (편집 제외)
    const h2 = document.createElement("h2");
    h2.textContent = (titleEl?.textContent || "").trim();
    clean.appendChild(h2);

    // thumb-wrap (편집 제외)
    if (thumbWrapEl) {
      const tw = thumbWrapEl.cloneNode(true);
      tw.removeAttribute("contenteditable");
      tw.querySelectorAll("[contenteditable]").forEach(el =>
        el.removeAttribute("contenteditable")
      );

      // 썸네일 img는 표시용 src(../../resource/...)가 아니라
      //     data-thumb-src에 저장된 "폴더/thumbs/폴더.jpg" 형태로 되돌려서 저장
      // 저장할 때도 다음 로딩에서 바로 올바른 위치를 읽도록
      //    backend/ui/index.html 기준 상대경로(../../resource/...)로 저장
      tw.querySelectorAll("img.thumb, img[alt='썸네일']").forEach(img => {
        const storedSrc = img.getAttribute("data-thumb-src");
        if (storedSrc) {
          img.setAttribute("src", `../../resource/${storedSrc}`);
        }
      });

      clean.appendChild(tw);
    }

    // inner (편집 가능 영역만 저장)
    const tmp = document.createElement("div");
    tmp.innerHTML = inner.innerHTML;
    tmp.querySelectorAll("[contenteditable]").forEach(el => el.removeAttribute("contenteditable"));
    tmp.querySelectorAll(".editable").forEach(el => el.classList.remove("editable"));

    const innerClean = document.createElement("div");
    innerClean.className = "inner";
    innerClean.innerHTML = tmp.innerHTML;
    clean.appendChild(innerClean);

    div.replaceWith(clean);
  });

  // 버튼/툴바 제거, 잔여 편집 속성 제거
  rootClone.querySelectorAll(".card-actions, button.btn").forEach(el => el.remove());
  rootClone.querySelectorAll("[contenteditable]").forEach(el => el.removeAttribute("contenteditable"));

  return rootClone.innerHTML;
}