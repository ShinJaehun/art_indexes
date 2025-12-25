// ---- Status UI helpers -------------------------------------------------
window.ensureStatusUI = function ensureStatusUI() {
    let bar = window.$("#statusBar");
    if (!bar) {
        bar = document.createElement("div");
        bar.id = "statusBar";
        bar.className = "status hidden"; // CSS: .status{padding:.6rem;border-radius:.5rem;margin:.5rem 0}
        window.$("#content").insertAdjacentElement("beforebegin", bar);
    }

    let details = window.$("#statusDetails");
    if (!details) {
        details = document.createElement("div");
        details.id = "statusDetails";
        details.className = "status-details hidden";
        bar.insertAdjacentElement("afterend", details);
    }
    return { bar, details };
};

window.clearStatus = function clearStatus() {
    // NOTE: _statusTimer는 master.js 전역에 그대로 둡니다(동작 동일).
    if (window._statusTimer) { clearTimeout(window._statusTimer); window._statusTimer = null; }
    const { bar, details } = window.ensureStatusUI();
    bar.className = "status hidden";
    bar.textContent = "";
    details.className = "status-details hidden";
    details.innerHTML = "";
};

window.showStatus = function showStatus({ level, title, lines = [], errors = [], metrics = null, autoHideMs = null }) {
    // NOTE: _statusTimer는 master.js 전역에 그대로 둡니다(동작 동일).
    if (window._statusTimer) { clearTimeout(window._statusTimer); window._statusTimer = null; }

    const { bar, details } = window.ensureStatusUI();

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
        window._statusTimer = setTimeout(() => {
            window._statusTimer = null;
            window.clearStatus();
        }, autoHideMs);
    }
};

window.renderSyncResult = function renderSyncResult(result) {
    const scanOk = !!result.scanOk;
    const pushOk = !!result.pushOk;

    const pureOk =
        !!result.ok &&
        scanOk &&
        pushOk &&
        (!result.errors || result.errors.length === 0);

    // 1) 완전 성공 + 변경 요약
    if (pureOk) {
        window.showStatus({
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
        window.showStatus({
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

    window.showStatus({
        level: "error",
        title: "동기화 중 오류가 발생했습니다",
        lines: errLines,
        errors: result.errors || [],
        metrics: result.metrics || null,
    });
};