// query helpers
window.$ = (selector, el = document) => el.querySelector(selector);
window.$$ = (selector, el = document) => Array.from(el.querySelectorAll(selector));

// data URL 썸네일은 브라우저/웹뷰의 file:// 제한을 우회하기 위한 것이므로
// 절대 ../../resource/... 로 덮어쓰지 않는다.
window.isDataImageUrl = function isDataImageUrl(src) {
    return typeof src === "string" && /^data:image\//i.test(src.trim());
};

// --- escape 유틸 ---
window.escapeHTML = function escapeHTML(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
};

window.safeThumbName = function safeThumbName(name) {
    // Python _safe_name과 최대한 동일하게
    return name
        .normalize("NFKC")
        .replace(/[\s\u00A0\u202F\u2009\u2007\u2060]+/g, "_")
        .replace(/[\/\\:*?"<>|]/g, "_");
};