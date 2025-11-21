// 주의: 아래 전역에 의존합니다 — hasBridge, call, loadMaster, showStatus, renderSyncResult
// master.js가 먼저 로드되고(Defer), 그 다음 이 파일이 로드되도록 index.html에서 순서가 잡혀있습니다.
// Sync 버튼 자체는 master.js 쪽 wireGlobalToolbar에서만 담당합니다.

let _toolbarWired = false;

// --- prune report renderer ---
function renderPruneReport(rep) {
  if (!rep) return ["리포트 없음"];
  const s = rep.summary || {};
  const lines = [];
  lines.push(
    `FS 폴더: ${s.fs_slugs ?? "-"}, MasterContent: ${s.master_content_slugs ?? "-"}, MasterIndex: ${s.master_index_slugs ?? "-"}`
  );
  lines.push(
    `프룬 대상(missing_in_fs): ${rep.folders_missing_in_fs?.length ?? 0}건`
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

  const btnRebuild = $("#btnRebuild");
  const btnRegenAll = $("#btnRegenAll");

  // 선택적: 전역 편집/저장 버튼이 있는 경우 동일한 UX 적용
  const btnEditAll = $("#btnEdit");     // 존재하면 전역 편집 시작
  const btnSaveAll = $("#btnSaveAll");  // 존재하면 전역 저장

  // ---- PRUNE: 드라이런 / 적용 ----
  const btnPruneDryRun = $("#btnPruneDryRun");
  const btnPruneApply = $("#btnPruneApply");
  const chkPruneDeleteThumbs = $("#chkPruneDeleteThumbs"); // optional

  const sortField = $("#sortField");
  const btnSortAsc = $("#btnSortAsc");
  const btnSortDesc = $("#btnSortDesc");

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
        const names = $$(".card").map(div => div.getAttribute("data-card") || $("h2", div)?.textContent.trim());
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
      $$(".card .inner").forEach(inner => {
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
        $$(".card .inner").forEach(el => { autoLinkify(el); decorateExternalLinks(el); });

        await call("save_master", serializeMaster());
        await loadMaster(); // 저장된 내용으로 즉시 재로딩(렌더 상태 확인)
        showStatus({ level: "ok", title: "전체 저장 완료", autoHideMs: 2000 });
        // 편집 종료
        $$(".card .inner").forEach(inner => {
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

  if (btnPruneDryRun) {
    btnPruneDryRun.addEventListener("click", async () => {
      if (!hasBridge) return alert("데스크톱 앱에서 실행하세요.");
      btnPruneDryRun.disabled = true;
      showStatus({ level: "warn", title: "프룬 점검 중…", lines: ["리포트 생성"] });
      try {
        // 백엔드: MasterApi.diff_and_report(include_thumbs=True)
        const rep = await call("diff_and_report");
        window._lastPruneReport = rep;  // 적용 전 재사용
        const lines = renderPruneReport(rep);
        showStatus({
          level: "ok",
          title: "프룬 드라이런 완료",
          lines
        });
      } catch (e) {
        console.error(e);
        showStatus({
          level: "error",
          title: "프룬 드라이런 실패",
          lines: [String(e?.message || e)]
        });
      } finally {
        btnPruneDryRun.disabled = false;
      }
    });
  }

  if (btnPruneApply) {
    btnPruneApply.addEventListener("click", async () => {
      if (!hasBridge) return alert("데스크톱 앱에서 실행하세요.");
      btnPruneApply.disabled = true;

      try {
        // 1) 최신 리포트 확보(없으면 즉시 생성)
        let rep = window._lastPruneReport;
        if (!rep) rep = await call("diff_and_report");
        const lines = renderPruneReport(rep);

        // 2) 사용자 확인(UI에 라이트하게 요약도 표시)
        const cnt = (rep.folders_missing_in_fs?.length ?? 0);
        const thumbsCnt = (rep.thumbs_orphans?.length ?? 0);
        const wantDeleteThumbs = !!(chkPruneDeleteThumbs && chkPruneDeleteThumbs.checked);

        const ok = confirm(
          [
            "프룬을 적용합니다.",
            `- master_content에서 제거: ${cnt}건`,
            wantDeleteThumbs ? `- 고아 썸네일 삭제: ${thumbsCnt}개` : "- 고아 썸네일은 유지",
            "",
            "진행할까요?",
          ].join("\n")
        );
        if (!ok) { btnPruneApply.disabled = false; return; }

        showStatus({ level: "warn", title: "프룬 적용 중…", lines });

        // 3) 적용 호출
        // 백엔드 시그니처: prune_apply(report=None, *, delete_thumbs=False)
        // → JS에선 report를 넘기면 1번째 위치인자로 매핑됨.
        // (delete_thumbs 토글은 아래 주석 참고)
        const result = await call("prune_apply", null, wantDeleteThumbs);

        // 4) 적용 결과 표기 + 화면 갱신
        const post = [
          `master 제거: ${result?.removed_from_master ?? 0}건`,
          `child 재생성: ${result?.child_built ?? 0}건`,
        ];
        if (typeof result?.thumbs_deleted === "number") {
          post.push(`썸네일 삭제: ${result.thumbs_deleted}개`);
        }
        await loadMaster();
        showStatus({ level: "ok", title: "프룬 적용 완료", lines: post });

      } catch (e) {
        console.error(e);
        showStatus({
          level: "error",
          title: "프룬 적용 실패",
          lines: [String(e?.message || e)]
        });
      } finally {
        btnPruneApply.disabled = false;
      }
    });
  }

  // ---- 정렬(생성순 / 이름순 + 오름/내림) ----
  async function applySort(direction) {
    if (!sortField) return;
    const field = sortField.value || "created";

    const container = $("#content") || document.body;
    const cards = $$(".card", container);
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
    if (!hasBridge) {
      if (typeof showStatus === "function") {
        const label = field === "title" ? "이름" : "생성";
        showStatus({
          level: "ok",
          title: `정렬 완료 (${label} ${direction === "asc" ? "↑" : "↓"})`,
        });
      }
      return;
    }

    // 데스크톱 앱: 정렬 상태를 master_content + master_index에 즉시 반영
    try {
      const label = field === "title" ? "이름" : "생성";
      showStatus &&
        showStatus({
          level: "warn",
          title: `정렬 후 저장 중… (${label} ${direction === "asc" ? "↑" : "↓"})`,
        });
      await call("save_master", serializeMaster());
      await loadMaster();
      showStatus &&
        showStatus({
          level: "ok",
          title: `정렬 + 저장 완료 (${label} ${direction === "asc" ? "↑" : "↓"})`,
          autoHideMs: 2500,
        });
    } catch (e) {
      console.error(e);
      showStatus &&
        showStatus({
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