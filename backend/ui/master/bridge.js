window.detectBridge = function detectBridge() {
    // API 객체가 있고, 키도 하나 이상 있어야 "실제 준비됨"으로 판단
    const api = (window.pywebview && window.pywebview.api) || null;
    window.hasBridge = !!api;

    window.$("#readonlyNote")?.classList.toggle("hidden", window.hasBridge);
    const toolbar = window.$("#globalToolbar");
    if (toolbar) toolbar.style.visibility = window.hasBridge ? "visible" : "hidden";
};

// API 준비를 보장하는 유틸: 특정 메서드들이 function이 될 때까지 대기
window.waitForApi = async function waitForApi(methods = [], timeoutMs = 3000, interval = 50) {
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
};

window.call = async function call(method, ...args) {
    // 1) 대상 메서드가 실제 function이 될 때까지 대기하고 api 핸들 확보
    let api;
    try {
        api = await window.waitForApi([method], 3000);
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
};