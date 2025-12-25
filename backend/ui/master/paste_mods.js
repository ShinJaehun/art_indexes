// --- paste modifier 키 상태 추적 (Shift/Alt 감지) ---
window.__pasteMods = { shift: false, alt: false };

window.addEventListener("keydown", (evt) => {
    if (evt.key === "Shift") window.__pasteMods.shift = true;
    if (evt.key === "Alt") window.__pasteMods.alt = true;
});

window.addEventListener("keyup", (evt) => {
    if (evt.key === "Shift") window.__pasteMods.shift = false;
    if (evt.key === "Alt") window.__pasteMods.alt = false;
});

window.addEventListener("blur", () => {
    window.__pasteMods.shift = false;
    window.__pasteMods.alt = false;
});