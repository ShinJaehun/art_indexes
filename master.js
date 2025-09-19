// master.js
const $  = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

let hasBridge = false;
let _toolbarWired = false;

function detectBridge() {
  hasBridge = !!(window.pywebview && window.pywebview.api);
  $("#readonlyNote")?.classList.toggle("hidden", hasBridge);
  const toolbar = $("#globalToolbar");
  if (toolbar) toolbar.style.visibility = hasBridge ? "visible" : "hidden";
}

async function onBridgeReady() {
  detectBridge();
  await loadMaster();
}

document.addEventListener("DOMContentLoaded", async () => {
  detectBridge();
  if (!hasBridge) {
    const blocks = $$(".folder", document);
    $("#content").innerHTML = "";
    if (blocks.length) {
      for (const b of blocks) $("#content").appendChild(b.cloneNode(true));
    } else {
      $("#content").innerHTML = `<p class="hint">브라우저 미리보기: <code>.folder</code> 블록이 없습니다.</p>`;
    }
    enhanceBlocks();
    wireGlobalToolbar();
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
  if (!hasBridge) throw new Error("pywebview bridge not available");
  return await window.pywebview.api[method](...args);
}

async function loadMaster() {
  if (hasBridge) {
    const { html } = await call("get_master");
    $("#content").innerHTML = html || "<p>내용 없음</p>";
  } else {
    const blocks = $$(".folder", document);
    $("#content").innerHTML = "";
    if (blocks.length) {
      for (const b of blocks) $("#content").appendChild(b.cloneNode(true));
    } else {
      $("#content").innerHTML = `<p class="hint">브라우저 미리보기: <code>.folder</code> 블록이 없습니다.</p>`;
    }
  }
  enhanceBlocks();
  wireGlobalToolbar();
}

function enhanceBlocks() {
  $$(".folder").forEach(div => {
    if (div.__enhanced) return;

    if (!div.querySelector(".folder-head")) {
      const h2 = $("h2", div);
      if (!h2) return;

      const head = document.createElement("div");
      head.className = "folder-head";
      h2.replaceWith(head);
      head.appendChild(h2);

      const actions = document.createElement("div");
      actions.className = "folder-actions" + (hasBridge ? "" : " hidden");
      actions.innerHTML = `
        <button class="btn btnEditOne">편집</button>
        <button class="btn btnSaveOne" disabled>저장</button>
        <button class="btn btnThumb">썸네일 갱신</button>
      `;
      head.appendChild(actions);

      // 1) 썸네일 영역은 편집영역 밖(HEAD)에 고정
      let thumbWrap = div.querySelector(".thumb-wrap");
      if (!thumbWrap) {
        thumbWrap = document.createElement("div");
        thumbWrap.className = "thumb-wrap";
        head.appendChild(thumbWrap);
      }

      // 2) head 다음 형제들 중 썸네일 후보는 먼저 thumb-wrap으로 이동
      {
        let node = head.nextSibling;
        while (node) {
          const next = node.nextSibling;
          if (
            node.nodeType === 1 && node.matches &&
            (
              node.matches("img.thumb, img[alt='썸네일']") ||
              (node.tagName === "IMG" && /\/thumbs\//.test(node.getAttribute("src") || ""))
            )
          ) {
            thumbWrap.appendChild(node);
          }
          node = next;
        }
      }

      // 3) 본문 컨테이너 생성 및 나머지(썸네일 외)만 .inner로 이동
      let inner = $(".inner", div);
      if (!inner) {
        inner = document.createElement("div");
        inner.className = "inner";

        const rest = [];
        let n = head.nextSibling;
        while (n) { rest.push(n); n = n.nextSibling; }
        rest.forEach(nd => inner.appendChild(nd));

        div.appendChild(inner);
      }

      // 4) 혹시 이미 .inner 안으로 들어간 썸네일이 있다면 꺼내오기(보정)
      const stray = $(".inner img.thumb, .inner img[alt='썸네일'], .inner img[src*='/thumbs/']", div);
      if (stray) {
        thumbWrap.appendChild(stray);
      }
    }

    // 5) 제목/썸네일은 항상 편집 제외
    const title = $(".folder-head h2", div);
    const thumbWrap = $(".thumb-wrap", div);
    title?.setAttribute("contenteditable", "false");
    title?.setAttribute("draggable", "false");
    thumbWrap?.setAttribute("contenteditable", "false");
    thumbWrap?.setAttribute("draggable", "false");
    thumbWrap?.querySelectorAll("*").forEach(el => {
      el.setAttribute("contenteditable", "false");
      el.setAttribute("draggable", "false");
    });

    // 6) 버튼 핸들러: 편집은 시작만, 저장은 종료까지
    const actions = $(".folder-head .folder-actions", div);
    const inner = $(".inner", div);
    const folder = div.getAttribute("data-folder") || (title?.textContent || "").trim();

    const btnEditOne = $(".btnEditOne", actions);
    const btnSaveOne = $(".btnSaveOne", actions);
    const btnThumb   = $(".btnThumb", actions);

    // ✅ 기본 상태: 편집 꺼짐, [편집] 활성 / [저장] 비활성
    inner.contentEditable = "false";
    inner.classList.remove("editable");
    btnEditOne.disabled = false;
    btnSaveOne.disabled = true;

    // ✅ 편집 시작(토글 없음)
    btnEditOne.onclick = () => {
      if (!hasBridge) return alert("편집은 데스크톱 앱에서만 가능합니다.");
      inner.contentEditable = "true";
      inner.classList.add("editable");
      btnEditOne.disabled = true;
      btnSaveOne.disabled = false;
    };

    // ✅ 저장 → 자동 종료 & 버튼 원복
    btnSaveOne.onclick = async () => {
      if (!hasBridge) return;
      btnSaveOne.disabled = true;
      try {
        await call("save_master", serializeMaster());
        alert("저장 완료");
        inner.contentEditable = "false";
        inner.classList.remove("editable");
        btnEditOne.disabled = false;
        btnSaveOne.disabled = true;
      } catch (e) {
        console.error(e);
        alert("저장 실패");
        // 실패 시 다시 저장 시도 가능하도록 복구
        btnSaveOne.disabled = false;
      }
    };

    // 썸네일 갱신은 기존 동작 유지
    btnThumb.onclick = async () => {
      if (!hasBridge) return alert("데스크톱 앱에서만 가능합니다.");
      btnThumb.disabled = true;
      try {
        const r = await call("refresh_thumb", folder, 640);
        alert(r.ok ? "썸네일 갱신 완료" : "썸네일 생성 실패(소스/의존성 확인)");
      } catch (e) {
        console.error(e); alert("실패");
      } finally {
        btnThumb.disabled = false;
      }
    };

    div.__enhanced = true;
  });
}

// 저장 직렬화: h2 + thumb-wrap + inner(본문)만 남기고, 버튼/편집속성 제거
function serializeMaster() {
  const root = document.querySelector("#content").cloneNode(true);

  root.querySelectorAll(".folder").forEach(div => {
    const head = div.querySelector(".folder-head");
    const inner = div.querySelector(".inner");
    if (!head || !inner) return;

    const titleEl = head.querySelector("h2");
    const thumbWrapEl = div.querySelector(".thumb-wrap");

    const clean = document.createElement("div");
    clean.className = "folder";

    // h2 (편집 제외)
    const h2 = document.createElement("h2");
    h2.textContent = (titleEl?.textContent || "").trim();
    clean.appendChild(h2);

    // thumb-wrap (편집 제외)
    if (thumbWrapEl) {
      const tw = thumbWrapEl.cloneNode(true);
      tw.removeAttribute("contenteditable");
      tw.querySelectorAll("[contenteditable]").forEach(el => el.removeAttribute("contenteditable"));
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
  root.querySelectorAll(".folder-actions, .btn").forEach(el => el.remove());
  root.querySelectorAll("[contenteditable]").forEach(el => el.removeAttribute("contenteditable"));

  return root.innerHTML;
}

function wireGlobalToolbar() {
  if (_toolbarWired) return;
  _toolbarWired = true;

  const btnSync     = $("#btnSync");
  const btnRebuild  = $("#btnRebuild");
  const btnRegenAll = $("#btnRegenAll");

  // 선택적: 전역 편집/저장 버튼이 있는 경우 동일한 UX 적용
  const btnEditAll  = $("#btnEdit");     // 존재하면 전역 편집 시작
  const btnSaveAll  = $("#btnSaveAll");  // 존재하면 전역 저장

  // ---- 필수 툴바(있을 때만) ----
  if (btnSync) {
    btnSync.addEventListener("click", async () => {
      if (!hasBridge) return alert("데스크톱 앱에서 실행하세요.");
      btnSync.disabled = true;
      try {
        const r = await call("sync");
        await loadMaster();
        const detail = (r.scanOk !== undefined && r.pushOk !== undefined)
          ? `\n(thumbs: ${r.scanOk ? "OK" : "FAIL"}, push: ${r.pushOk ? "OK" : "FAIL"})`
          : "";
        alert((r.ok ? "Sync 완료" : "Sync 실패") + detail);
      } catch (e) {
        console.error(e);
        alert("Sync 실패: " + e.message);
      } finally {
        btnSync.disabled = false;
      }
    });
  }

  if (btnRebuild) {
    btnRebuild.addEventListener("click", async () => {
      if (!hasBridge) return alert("데스크톱 앱에서 실행하세요.");
      btnRebuild.disabled = true;
      try {
        await call("rebuild_master");
        await loadMaster();
        alert("마스터 재생성 완료");
      } catch (e) {
        console.error(e); alert("실패");
      } finally {
        btnRebuild.disabled = false;
      }
    });
  }

  if (btnRegenAll) {
    btnRegenAll.addEventListener("click", async () => {
      if (!hasBridge) return alert("데스크톱 앱에서 실행하세요.");
      btnRegenAll.disabled = true;
      try {
        const names = $$(".folder").map(div => div.getAttribute("data-folder") || $("h2", div)?.textContent.trim());
        for (const name of names) {
          await call("refresh_thumb", name, 640);
        }
        alert("썸네일 일괄 갱신 완료");
      } catch (e) {
        console.error(e); alert("실패");
      } finally {
        btnRegenAll.disabled = false;
      }
    });
  }

  // ---- 전역 편집/저장(선택적) ----
  if (btnEditAll && btnSaveAll) {
    // 기본 상태: 편집 꺼짐, [편집] 활성 / [저장] 비활성
    btnEditAll.disabled = false;
    btnSaveAll.disabled = true;

    btnEditAll.addEventListener("click", () => {
      if (!hasBridge) return alert("편집은 데스크톱 앱에서만 가능합니다.");
      // 모든 카드의 .inner 편집 시작
      $$(".folder .inner").forEach(inner => {
        inner.contentEditable = "true";
        inner.classList.add("editable");
      });
      btnEditAll.disabled = true;
      btnSaveAll.disabled = false;
    });

    btnSaveAll.addEventListener("click", async () => {
      if (!hasBridge) return;
      btnSaveAll.disabled = true;
      try {
        await call("save_master", serializeMaster());
        alert("전체 저장 완료");
        // 편집 종료
        $$(".folder .inner").forEach(inner => {
          inner.contentEditable = "false";
          inner.classList.remove("editable");
        });
        btnEditAll.disabled = false;
        btnSaveAll.disabled = true;
      } catch (e) {
        console.error(e); alert("저장 실패");
        btnSaveAll.disabled = false;
      }
    });
  }
}
