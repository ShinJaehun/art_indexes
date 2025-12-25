// 주의: 아래 전역에 의존합니다 — hasBridge, call, loadMaster, showStatus, renderSyncResult
// master.js가 먼저 로드되고(Defer), 그 다음 이 파일이 로드되도록 index.html에서 순서가 잡혀있습니다.
// Sync 버튼 자체는 master.js 쪽 wireGlobalToolbar에서만 담당합니다.

let _toolbarWired = false;

// --- prune report renderer ---
function renderPruneReport(rep) {
  if (!rep) return ["리포트 없음"];
  const s = rep.summary || {};
  const lines = [];
  // 현재는 UI에서 프룬 기능을 노출하지 않지만,
  // 내부 디버깅용으로 쓸 수 있도록 최소한의 요약만 유지해 둔다.
  lines.push(
    `폴더/인덱스 요약 - FS: ${s.fs_slugs ?? "-"}, MC: ${s.master_content_slugs ?? "-"}, MI: ${s.master_index_slugs ?? "-"}`
  );
  if (rep.folders_missing_in_fs?.length) {
    lines.push(" - " + rep.folders_missing_in_fs.join(", "));
  }
  if (rep.child_indexes_missing?.length) {
    lines.push(`child index 누락: ${rep.child_indexes_missing.length}건`);
    lines.push(" - " + rep.child_indexes_missing.join(", "));
  }
  if (rep.orphans_in_master_index_only?.length) {
    lines.push(`master_index 단독 고아: ${rep.orphans_in_master_index_only.length}건`);
    lines.push(" - " + rep.orphans_in_master_index_only.join(", "));
  }
  if (rep.thumbs_orphans?.length) {
    const n = rep.thumbs_orphans.length;
    lines.push(`고아 썸네일 파일: ${n}개${n > 8 ? " (상세 생략)" : ""}`);
    if (n <= 8) lines.push(" - " + rep.thumbs_orphans.join(", "));
  }
  return lines;
}


function wireExtraToolbar() {
  if (_toolbarWired) return;
  _toolbarWired = true;

  const btnRebuild = window.$("#btnRebuild");
  const btnRegenAll = window.$("#btnRegenAll");

  // 선택적: 전역 편집/저장 버튼이 있는 경우 동일한 UX 적용
  const btnEditAll = window.$("#btnEdit");     // 존재하면 전역 편집 시작
  const btnSaveAll = window.$("#btnSaveAll");  // 존재하면 전역 저장
  const btnResetAll = window.$("#btnResetAll"); // ⚠ 전체 초기화 (global toolbar)

  const sortField = window.$("#sortField");
  const btnSortAsc = window.$("#btnSortAsc");
  const btnSortDesc = window.$("#btnSortDesc");

  if (btnRebuild) {
    btnRebuild.addEventListener("click", async () => {
      if (!window.hasBridge) return alert("데스크톱 앱에서 실행하세요.");
      btnRebuild.disabled = true;
      try {
        await window.call("rebuild_master");
        await window.loadMaster();
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
      if (!window.hasBridge) return alert("데스크톱 앱에서 실행하세요.");
      btnRegenAll.disabled = true;
      try {
        const names = window.$$(".card").map(div => div.getAttribute("data-card") || window.$("h2", div)?.textContent.trim());
        for (const name of names) {
          await window.call("refresh_thumb", name, 640);
        }
        alert("썸네일 일괄 갱신 완료");
      } catch (e) {
        console.error(e); alert("실패");
      } finally {
        btnRegenAll.disabled = false;
      }
    });
  }


  // ⚠ 전체 초기화 (reset_all 호출)
  if (btnResetAll) {
    btnResetAll.addEventListener("click", async () => {
      if (!window.hasBridge) {
        window.showStatus({
          level: "warn",
          title: "데스크톱 앱에서만 초기화할 수 있습니다.",
        });
        return;
      }

      const ok = window.confirm(
        "정말 전체 초기화할까요?\n\n" +
        "- backend/master_content.html\n" +
        "- resource/master_index.html\n" +
        "- resource/**/thumbs/ 폴더\n" +
        "- resource/**/index.html 파일\n" +
        "- backend/.suksukidx.registry.json\n\n" +
        "이 작업은 되돌릴 수 없습니다."
      );
      if (!ok) return;

      try {
        window.showStatus({
          level: "warn",
          title: "전체 초기화 중…",
        });

        const r = await window.call("reset_all");
        if (!r?.ok) {
          const msg =
            (r && (r.error || (Array.isArray(r.errors) && r.errors[0]))) ||
            "초기화에 실패했습니다.";
          window.showStatus({
            level: "error",
            title: "전체 초기화 실패",
            lines: [msg],
            errors: r?.errors || [],
          });
          return;
        }

        const summaryLines = [];
        if (r.master_content) summaryLines.push("master_content.html 삭제");
        if (r.master_index) summaryLines.push("master_index.html 삭제");
        if (r.registry) summaryLines.push("레지스트리 삭제");
        summaryLines.push(`thumbs 폴더 ${r.thumb_dirs || 0}곳`);
        summaryLines.push(`child index ${r.child_indexes || 0}개`);

        window.showStatus({
          level: "ok",
          title: "전체 초기화 완료",
          lines: summaryLines,
        });

        // 비워진 상태로 다시 로드
        await window.loadMaster();
      } catch (e) {
        window.showStatus({
          level: "error",
          title: "전체 초기화 예외",
          lines: [String(e?.message || e)],
        });
      }
    });
  }

  // ---- P5: 프룬/고아 썸네일 정리 UI 숨기기 ------------------------------
  // HTML에는 예전 버튼이 남아 있을 수 있으므로, 로딩 시점에 통째로 제거한다.
  (function hidePruneControls() {

    const btnPruneDryRun = window.$("#btnPruneDryRun");
    const btnPruneApply = window.$("#btnPruneApply");
    const chkPruneDeleteThumbs = window.$("#chkPruneDeleteThumbs");

    if (btnPruneDryRun) btnPruneDryRun.remove();
    if (btnPruneApply) btnPruneApply.remove();

    if (chkPruneDeleteThumbs) {
      const label = chkPruneDeleteThumbs.closest("label");
      if (label) label.remove();
      else chkPruneDeleteThumbs.remove();
    }
  })();


  // ---- 전역 편집/저장(선택적) ----
  if (btnEditAll && btnSaveAll) {
    // 기본 상태: 편집 꺼짐, [편집] 활성 / [저장] 비활성
    btnEditAll.disabled = false;
    btnSaveAll.disabled = true;

    btnEditAll.addEventListener("click", () => {
      if (!window.hasBridge) return alert("편집은 데스크톱 앱에서만 가능합니다.");
      // 모든 카드의 .inner 편집 시작
      window.$$(".card .inner").forEach(inner => {
        inner.contentEditable = "true";
        inner.classList.add("editable");
      });
      btnEditAll.disabled = true;
      btnSaveAll.disabled = false;
    });

    btnSaveAll.addEventListener("click", async () => {
      if (!window.hasBridge) return;
      btnSaveAll.disabled = true;
      try {
        // 저장 직전 보정
        window.$$(".card .inner").forEach(el => { window.autoLinkify(el); window.decorateExternalLinks(el); });

        await window.call("save_master", window.serializeMaster());
        await window.loadMaster(); // 저장된 내용으로 즉시 재로딩(렌더 상태 확인)
        window.showStatus({ level: "ok", title: "전체 저장 완료", autoHideMs: 2000 });
        // 편집 종료
        window.$$(".card .inner").forEach(inner => {
          inner.contentEditable = "false";
          inner.classList.remove("editable");
        });
        btnEditAll.disabled = false;
        btnSaveAll.disabled = true;
      } catch (e) {
        console.error(e);
        window.showStatus({ level: "error", title: "저장 실패", lines: [String(e?.message || e)] });
        btnSaveAll.disabled = false;
      }
    });
  }

  // ---- 정렬(생성순 / 이름순 + 오름/내림) ----
  async function applySort(direction) {
    if (!sortField) return;
    const field = sortField.value || "created";

    const container = window.$("#content") || document.body;
    const cards = window.$$(".card", container);
    if (!cards.length) return;

    // --- 다중 키 정렬키 생성 ---
    const getKey = (el) => {
      const title =
        (el.getAttribute("data-card") ||
          el.querySelector(".card-head h2")?.textContent ||
          "").trim();
      const titleLower = title.toLowerCase();
      const created = (el.getAttribute("data-created-at") || "").trim();

      const missTitle = !title;
      const missCreated = !created;

      if (field === "title") {
        // 이름순 → (제목, 생성일, 결측 여부)
        return [titleLower, created, missTitle || missCreated];
      } else {
        // 생성순 → (생성일, 제목, 결측 여부)
        return [created, titleLower, missCreated || missTitle];
      }
    };

    cards.sort((a, b) => {
      const akey = getKey(a);
      const bkey = getKey(b);

      // 3단계 키 비교
      // key = [primary, secondary, miss]

      // 1) primary 비교
      let cmp = String(akey[0]).localeCompare(String(bkey[0]));
      if (cmp !== 0) return direction === "asc" ? cmp : -cmp;

      // 2) secondary 비교
      cmp = String(akey[1]).localeCompare(String(bkey[1]));
      if (cmp !== 0) return direction === "asc" ? cmp : -cmp;

      // 3) 결측은 뒤로
      const amiss = akey[2] ? 1 : 0;
      const bmiss = bkey[2] ? 1 : 0;
      return amiss - bmiss;
    });

    cards.forEach((el) => container.appendChild(el));

    // 브라우저 미리보기 모드: 화면 정렬만
    if (!window.hasBridge) {
      if (typeof window.showStatus === "function") {
        const label = field === "title" ? "이름" : "생성";
        window.showStatus({
          level: "ok",
          title: `정렬 완료 (${label} ${direction === "asc" ? "↑" : "↓"})`,
        });
      }
      return;
    }

    // 데스크톱 앱: 정렬 상태를 master_content + master_index에 즉시 반영
    try {
      const label = field === "title" ? "이름" : "생성";
      window.showStatus &&
        window.showStatus({
          level: "warn",
          title: `정렬 후 저장 중… (${label} ${direction === "asc" ? "↑" : "↓"})`,
        });
      await window.call("save_master", window.serializeMaster());
      await window.loadMaster();
      window.showStatus &&
        window.showStatus({
          level: "ok",
          title: `정렬 + 저장 완료 (${label} ${direction === "asc" ? "↑" : "↓"})`,
          autoHideMs: 2500,
        });
    } catch (e) {
      console.error(e);
      window.showStatus &&
        window.showStatus({
          level: "error",
          title: "정렬/저장 실패",
          lines: [String(e?.message || e)],
        });
    }
  }

  if (sortField) {
    if (btnSortAsc) {
      btnSortAsc.addEventListener("click", () => applySort("asc"));
    }
    if (btnSortDesc) {
      btnSortDesc.addEventListener("click", () => applySort("desc"));
    }
  }
}

// 전역으로 노출 (master.js에서 window.wireExtraToolbar()로 호출)
window.wireExtraToolbar = wireExtraToolbar;