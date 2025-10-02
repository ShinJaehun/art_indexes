// master.js
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

let hasBridge = false;
let _toolbarWired = false;
let _statusTimer = null;

// --- paste modifier 키 상태 추적 (Shift/Alt 감지)---
const __pasteMods = { shift: false, alt: false };
window.addEventListener("keydown", (e) => {
  if (e.key === "Shift") __pasteMods.shift = true;
  if (e.key === "Alt") __pasteMods.alt = true;
});
window.addEventListener("keyup", (e) => {
  if (e.key === "Shift") __pasteMods.shift = false;
  if (e.key === "Alt") __pasteMods.alt = false;
});
window.addEventListener("blur", () => { __pasteMods.shift = __pasteMods.alt = false; });

// --- escape 유틸 ---
function escapeHTML(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

// --- 외부 링크 버튼화 & 보안 속성 보강 ---
function decorateExternalLinks(scopeEl) {
  const links = scopeEl.querySelectorAll('a[href]');
  links.forEach(a => {

    let href = (a.getAttribute('href') || '').trim();
    // 스킴이 없고, www. 또는 도메인 형태라면 https:// 보강
    if (!/^(?:https?:\/\/|mailto:|tel:|#|\/|\.\.\/)/i.test(href)) {
      if (/^(?:www\.|(?:[a-z0-9-]+\.)+[a-z]{2,})/i.test(href)) {
        href = `https://${href}`;
        a.setAttribute('href', href);
      }
    }
    if (!/^https?:\/\//i.test(href)) return; // 외부 http(s)만 버튼화 대상
    a.setAttribute('target', '_blank');

    // 기존 rel 유지 + 보안 속성 보장
    const relSet = new Set(((a.getAttribute('rel') || '')).split(/\s+/).filter(Boolean));
    relSet.add('noopener'); relSet.add('noreferrer');
    a.setAttribute('rel', Array.from(relSet).join(' '));
    // 버튼 스타일(있으면 유지)
    a.classList.add('btn', 'btnExternal');
    // 라벨이 비어있으면 도메인으로 기본 라벨
    if (!a.textContent.trim()) {
      try {
        const u = new URL(href);
        a.textContent = `열기 (${u.hostname})`;
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
        const s = node.nodeValue;
        if (!s) return NodeFilter.FILTER_REJECT;

        // ✅ 1) HTML 엔티티/태그 기호가 섞인 텍스트는 건너뜀
        // (&lt; / &gt; / 실제 < > 가 들어있으면 사용자가 '코드'를 입력 중인 것으로 판단)
        if (/[<>]/.test(s) || /&lt;|&gt;/i.test(s)) return NodeFilter.FILTER_REJECT;

        // URL 패턴이 없으면 스킵
        if (!urlRe.test(s)) return NodeFilter.FILTER_REJECT;

        // a/pre/code/script/style 내부는 건너뜀
        const p = node.parentElement;
        if (p && p.closest('a, pre, code, script, style')) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    }
  );

  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);

  nodes.forEach(textNode => {
    const text = textNode.nodeValue;

    // ✅ 2) 따옴표 안 구간 범위 미리 수집 → 그 안의 매치는 스킵
    const quoteRanges = [];
    const quoteRe = /"[^"]*"|'[^']*'/g;
    let qm;
    while ((qm = quoteRe.exec(text)) !== null) {
      quoteRanges.push([qm.index, qm.index + qm[0].length]); // [start, end)
    }
    const inQuoted = (idx) => quoteRanges.some(([s, e]) => idx >= s && idx < e);

    urlRe.lastIndex = 0;

    let match;
    let lastIdx = 0;
    const frag = document.createDocumentFragment();

    while ((match = urlRe.exec(text)) !== null) {
      const start = match.index;
      const end = start + match[0].length;

      // 따옴표 안이면 링크화하지 않고 건너뜀
      if (inQuoted(start)) continue;

      if (start > lastIdx) {
        frag.appendChild(document.createTextNode(text.slice(lastIdx, start)));
      }

      const raw = match[0];

      // href 정규화: 스킴이 없으면 https:// 보강
      let href = raw;
      if (!/^(?:https?:\/\/|mailto:|tel:)/i.test(raw)) {
        href = /^\/\//.test(raw) ? `https:${raw}` : `https://${raw}`;
      }

      const a = document.createElement('a');
      a.href = href;                // 실제 링크는 정규화된 href
      a.textContent = raw;          // 화면에는 사용자가 쓴 원문 표시
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.classList.add('btn', 'btnExternal');
      frag.appendChild(a);

      lastIdx = end;
    }

    // 남은 꼬리 텍스트
    if (lastIdx < text.length) {
      frag.appendChild(document.createTextNode(text.slice(lastIdx)));
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
    // CSS 예: .status--ok{background:#e8fff0;border:1px solid #9ad3ae}
    //         .status--warn{background:#fff8e6;border:1px solid #e6c98e}
    //         .status--error{background:#ffecec;border:1px solid #e39b9b}
    $("#content").insertAdjacentElement("beforebegin", bar);
  }

  let details = $("#statusDetails");
  if (!details) {
    details = document.createElement("div");
    details.id = "statusDetails";
    details.className = "status-details hidden";
    // CSS 예: .status-details{font-size:.95rem;margin:.25rem 0 1rem}
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
  // 기존 타이머가 있으면 먼저 클리어
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
      errors.map(e => `<li>${e}</li>`).join("") + `</ul></details>`);
  }

  if (parts.length) {
    details.innerHTML = parts.map(p => `<div>${p}</div>`).join("");
    details.classList.remove("hidden");
  } else {
    details.classList.add("hidden");
    details.innerHTML = "";
  }

  // ✅ auto-hide: ms 지정 시 그 시간 후 자동으로 감춤
  if (typeof autoHideMs === "number" && autoHideMs > 0) {
    _statusTimer = setTimeout(() => {
      _statusTimer = null;
      clearStatus();
    }, autoHideMs);
  }
}

function renderSyncResult(r) {
  const lines = [
    `썸네일 스캔: ${r.scanOk ? "OK" : "FAIL"}`,
    `파일 반영: ${r.pushOk ? "OK" : "FAIL"}`
  ];

  // 순수 성공(둘 다 OK, 에러 없음) → 플래시
  const pureOk = r.ok && r.scanOk && r.pushOk && (!r.errors || r.errors.length === 0);

  if (pureOk) {
    showStatus({
      level: "ok",
      title: "동기화 완료",
      lines,
      errors: [],
      metrics: r.metrics || null,
      autoHideMs: 2500,         // ✅ 성공은 자동 숨김
    });
    return;
  }

  // 부분 성공(경고 표시, 유지)
  if (r.ok) {
    showStatus({
      level: "warn",
      title: "동기화 부분 완료",
      lines,
      errors: r.errors || [],
      metrics: r.metrics || null,
      // autoHide 없음 → 남겨둠
    });
    return;
  }

  // 실패(유지)
  showStatus({
    level: "error",
    title: "동기화 실패",
    lines,
    errors: r.errors || [],
    metrics: r.metrics || null,
  });
}

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
  clearStatus();
}

function enhanceBlocks() {
  $$(".folder").forEach(div => {
    if (div.__enhanced) return;

    // head: h2 → actions → thumb-wrap 순서 보정
    function normalizeHead(headEl) {
      const h2 = $("h2", headEl);
      let actions = $(".folder-actions", headEl);
      let thumbWrap = $(".thumb-wrap", headEl);

      if (!actions) {
        actions = document.createElement("div");
        actions.className = "folder-actions" + (hasBridge ? "" : " hidden");
        actions.innerHTML = `
          <button class="btn btnEditOne">편집</button>
          <button class="btn btnSaveOne" disabled>저장</button>
          <button class="btn btnThumb">썸네일 갱신</button>
        `;
      }
      if (!thumbWrap) {
        thumbWrap = document.createElement("div");
        thumbWrap.className = "thumb-wrap";
      }

      if (h2) headEl.appendChild(h2);
      headEl.appendChild(actions);
      headEl.appendChild(thumbWrap);
      return { actions, thumbWrap };
    }

    // .folder-head 구성 없으면 생성
    const hasHead = !!div.querySelector(".folder-head");
    if (!hasHead) {
      const h2 = $("h2", div);
      if (!h2) return;

      const head = document.createElement("div");
      head.className = "folder-head";
      h2.replaceWith(head);
      head.appendChild(h2);
      const { thumbWrap } = normalizeHead(head);

      // head 다음 형제 중 썸네일 후보를 thumb-wrap으로 이동
      let node = head.nextSibling;
      while (node) {
        const next = node.nextSibling;
        if (
          node.nodeType === 1 && node.matches &&
          (node.matches("img.thumb, img[alt='썸네일']") ||
            (node.tagName === "IMG" && /\/thumbs\//.test(node.getAttribute("src") || "")))
        ) {
          thumbWrap.appendChild(node);
        }
        node = next;
      }

      // .inner 생성 및 나머지 내용을 .inner로 이동
      let innerEl = $(".inner", div);
      if (!innerEl) {
        innerEl = document.createElement("div");
        innerEl.className = "inner";
        const rest = [];
        let n = head.nextSibling;
        while (n) { rest.push(n); n = n.nextSibling; }
        rest.forEach(nd => innerEl.appendChild(nd));
        div.appendChild(innerEl);
      }

      // .inner 안으로 들어간 썸네일이 있다면 다시 head로
      const stray = $(".inner img.thumb, .inner img[alt='썸네일'], .inner img[src*='/thumbs/']", div);
      if (stray) $(".thumb-wrap", head).appendChild(stray);

    } else {
      const head = $(".folder-head", div);
      normalizeHead(head);
    }

    // 제목/썸네일은 편집 제외
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

    // 버튼/inner 참조
    const actions = $(".folder-head .folder-actions", div);
    const inner = $(".inner", div);

    // ✅ URL 오토링크 + 버튼화(초기 표시 시 1회)
    autoLinkify(inner);
    decorateExternalLinks(inner);

    const folder = div.getAttribute("data-folder") || (title?.textContent || "").trim();
    const btnEditOne = $(".btnEditOne", actions);
    const btnSaveOne = $(".btnSaveOne", actions);
    const btnThumb = $(".btnThumb", actions);

    // --- 붙여넣기 핸들러 (중복 제거, escape 유틸 사용) ---
    if (inner && !inner.__pasteWired) {
      inner.addEventListener("paste", (e) => {
        try {
          if (!e.clipboardData) return;

          // Shift/Alt 누르면 "문자 그대로 붙여넣기" 모드
          const forceLiteral = __pasteMods.shift || __pasteMods.alt;

          // 1) HTML 클립보드가 있고 literal이 아니면 → 그대로 삽입
          const html = e.clipboardData.getData("text/html");
          if (html && !forceLiteral) {
            e.preventDefault();
            document.execCommand("insertHTML", false, html);
            return;
          }

          // 2) 평문 처리
          const raw = e.clipboardData.getData("text/plain");
          if (!raw) return;

          const hasLiteralTags = /<[^>]+>/.test(raw);      // <h2>...</h2>
          const hasEscapedTags = /&lt;[^&]+&gt;/.test(raw);// &lt;h2&gt;...&lt;/h2&gt;
          const hasCodeFence = /(^|\n)```/.test(raw);    // 코드펜스

          // 2-A) 문자 그대로 붙여넣기(코드펜스 or 강제 literal)
          if (forceLiteral || hasCodeFence) {
            e.preventDefault();
            const stripped = raw.replace(/(^|\n)```([\s\S]*?)```/g, (_, pre, body) => pre + body);
            const literal = escapeHTML(stripped);
            document.execCommand("insertHTML", false, `<pre><code>${literal}</code></pre>`);
            return;
          }

          // 2-B) 태그형 텍스트를 실제 HTML로 삽입 (보안 필터 포함)
          if (hasLiteralTags || hasEscapedTags) {
            e.preventDefault();

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
                const k = attr.name.toLowerCase();
                const v = (attr.value || "").trim().toLowerCase();
                if (k.startsWith("on") || k === "style" || k === "contenteditable" || k === "draggable" || k.startsWith("data-")) {
                  el.removeAttribute(attr.name);
                }
                if ((k === "href" || k === "src") && (v.startsWith("javascript:") || v.startsWith("data:"))) {
                  el.removeAttribute(attr.name);
                }
              });
              if (!allowed.has(el.tagName)) {
                const p = el.parentNode;
                while (el.firstChild) p.insertBefore(el.firstChild, el);
                p.removeChild(el);
              }
            });

            // === 2-4) 구조 보정: 헤딩 강등 + 고아 li 래핑 + 빈 태그 정리 ===

            // 본문에서는 h1/h2를 h3로 강등 (제목 <h2>는 folder-head 쪽이 담당하므로)
            (function demoteHeadings(root) {
              root.querySelectorAll("h1,h2").forEach(h => {
                const h3 = document.createElement("h3");
                h3.innerHTML = h.innerHTML;
                // 기존 id/class는 유지(원하면 제거 가능)
                [...h.attributes].forEach(a => h3.setAttribute(a.name, a.value));
                h.replaceWith(h3);
              });
            })(divTmp);

            // 고아 <li>들을 인접 구간별로 <ul>로 감싸기
            (function normalizeOrphanLis(root) {
              const lis = Array.from(root.querySelectorAll("li")).filter(li => {
                const p = li.parentElement;
                return !(p && (p.tagName === "UL" || p.tagName === "OL"));
              });
              if (!lis.length) return;

              let run = [];
              const flush = () => {
                if (!run.length) return;
                const ul = document.createElement("ul");
                run[0].parentNode.insertBefore(ul, run[0]);
                run.forEach(li => ul.appendChild(li));
                run = [];
              };

              // 문서 순서대로 그룹핑
              const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
              let node;
              while ((node = walker.nextNode())) {
                if (node.tagName === "LI" && lis.includes(node)) {
                  run.push(node);
                } else if (run.length) {
                  flush();
                }
              }
              flush();
            })(divTmp);

            // 빈/무의미 태그 정리: 비어있는 p/div/span 등 제거 (img, br는 보존)
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
        } catch (err) {
          console.warn("paste handler error", err);
        }
      });
      inner.__pasteWired = true;
    }

    // 기본 상태
    inner.contentEditable = "false";
    inner.classList.remove("editable");
    btnEditOne.disabled = false;
    btnSaveOne.disabled = true;

    // 편집 시작
    btnEditOne.onclick = () => {
      if (!hasBridge) return alert("편집은 데스크톱 앱에서만 가능합니다.");
      inner.contentEditable = "true";
      inner.classList.add("editable");
      btnEditOne.disabled = true;
      btnSaveOne.disabled = false;
    };

    // 저장
    btnSaveOne.onclick = async () => {
      if (!hasBridge) return;
      btnSaveOne.disabled = true;
      try {
        // ✅ 저장 직전 전체 카드에 대해 오토링크/버튼화 보정
        $$(".folder .inner").forEach(el => { autoLinkify(el); decorateExternalLinks(el); });

        await call("save_master", serializeMaster());
        await loadMaster(); // 저장된 내용으로 즉시 재로딩(렌더 상태 확인)
        showStatus({ level: "ok", title: "저장 완료", autoHideMs: 1800 });
        inner.contentEditable = "false";
        inner.classList.remove("editable");
        btnEditOne.disabled = false;
        btnSaveOne.disabled = true;
      } catch (e) {
        console.error(e);
        showStatus({ level: "error", title: "저장 실패", lines: [String(e?.message || e)] });
        btnSaveOne.disabled = false;
      }
    };

    // 썸네일 갱신
    btnThumb.onclick = async () => {
      if (!hasBridge) return alert("데스크톱 앱에서만 가능합니다.");
      btnThumb.disabled = true;
      showStatus({ level: "warn", title: "썸네일 갱신 중…", lines: [`${folder}`] });
      try {
        const r = await call("refresh_thumb", folder, 640);
        if (r?.ok) {
          showStatus({ level: "ok", title: "썸네일 갱신 완료", lines: [folder], autoHideMs: 1800 });
        } else {
          const hint = r?.error ? [r.error] : ["소스 이미지 없음 또는 변환 실패"];
          showStatus({ level: "error", title: "썸네일 갱신 실패", lines: [folder], errors: hint });
        }
      } catch (e) {
        showStatus({ level: "error", title: "썸네일 갱신 예외", lines: [folder], errors: [String(e?.message || e)] });
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
  root.querySelectorAll(".folder-actions, button.btn").forEach(el => el.remove());
  root.querySelectorAll("[contenteditable]").forEach(el => el.removeAttribute("contenteditable"));

  return root.innerHTML;
}

function wireGlobalToolbar() {
  if (_toolbarWired) return;
  _toolbarWired = true;

  const btnSync = $("#btnSync");
  const btnRebuild = $("#btnRebuild");
  const btnRegenAll = $("#btnRegenAll");

  // 선택적: 전역 편집/저장 버튼이 있는 경우 동일한 UX 적용
  const btnEditAll = $("#btnEdit");     // 존재하면 전역 편집 시작
  const btnSaveAll = $("#btnSaveAll");  // 존재하면 전역 저장

  // ---- 필수 툴바(있을 때만) ----
  if (btnSync) {
    btnSync.addEventListener("click", async () => {
      if (!hasBridge) return alert("데스크톱 앱에서 실행하세요.");
      btnSync.disabled = true;

      // 진행중 표시
      showStatus({ level: "warn", title: "동기화 중…", lines: ["잠시만 기다려주세요."] });

      try {
        const r = await call("sync");       // {ok, scanOk, pushOk, errors, metrics}
        await loadMaster();                 // 최신 내용 다시 로드 (상태바는 유지됨)
        renderSyncResult(r);                // 상태바 업데이트
      } catch (e) {
        console.error(e);
        showStatus({
          level: "error",
          title: "동기화 호출 실패",
          lines: [String(e?.message || e)]
        });
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
        // ✅ 저장 직전 보정
        $$(".folder .inner").forEach(el => { autoLinkify(el); decorateExternalLinks(el); });

        await call("save_master", serializeMaster());
        await loadMaster(); // 저장된 내용으로 즉시 재로딩(렌더 상태 확인)
        showStatus({ level: "ok", title: "전체 저장 완료", autoHideMs: 2000 });
        // 편집 종료
        $$(".folder .inner").forEach(inner => {
          inner.contentEditable = "false";
          inner.classList.remove("editable");
        });
        btnEditAll.disabled = false;
        btnSaveAll.disabled = true;
      } catch (e) {
        console.error(e);
        showStatus({ level: "error", title: "저장 실패", lines: [String(e?.message || e)] });
        btnSaveAll.disabled = false;
      }
    });
  }
}
