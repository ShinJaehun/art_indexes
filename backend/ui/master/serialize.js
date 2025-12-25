// 저장 직렬화: h2 + thumb-wrap + inner(본문)만 남기고, 버튼/편집속성 제거
window.serializeMaster = function serializeMaster() {
    const rootClone = document.querySelector("#content").cloneNode(true);

    // "내용 없음" 플레이스홀더는 파일에 절대 저장하지 않도록 정리
    (function stripPlaceholder(root) {
        const firstCard = root.querySelector(".card");

        if (firstCard) {
            // 카드가 하나라도 있을 때:
            // 첫 번째 카드 앞에 있는 형제들 중에서
            // <p>내용 없음</p>만 제거한다.
            let node = root.firstChild;
            while (node && node !== firstCard) {
                const next = node.nextSibling;
                if (
                    node.nodeType === 1 &&
                    node.tagName === "P" &&
                    node.textContent.trim() === "내용 없음"
                ) {
                    root.removeChild(node);
                }
                node = next;
            }
        } else {
            // 카드가 하나도 없고, 루트에 플레이스홀더 문단만 있는 경우 → 완전 빈 상태로 저장
            const onlyP =
                root.children.length === 1 &&
                root.children[0].tagName === "P" &&
                root.children[0].textContent.trim() === "내용 없음";

            if (onlyP) {
                root.innerHTML = "";
            } else {
                // 혹시 모를 상단 플레이스홀더를 한 번 더 방어적으로 제거
                root.querySelectorAll("p").forEach((p) => {
                    if (p.textContent.trim() === "내용 없음") p.remove();
                });
            }
        }
    })(rootClone);

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
};