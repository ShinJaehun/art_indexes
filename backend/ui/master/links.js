// --- 외부 링크 버튼화 & 보안 속성 보강 ---
window.decorateExternalLinks = function decorateExternalLinks(scopeEl) {
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
};

// --- 텍스트 속 URL을 자동으로 <a>로 감싸기 ---
window.autoLinkify = function autoLinkify(scopeEl) {
    // 1) http(s)://...  2) www.example.com/...  3) example.com/...
    const urlRe = /\b(?:https?:\/\/[^\s<>"']+|www\.[^\s<>"']+|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/[^\s<>"']*)?)/gi;

    const walker = document.createTreeWalker(
        scopeEl,
        NodeFilter.SHOW_TEXT,
        {
            acceptNode(node) {
                const nodeText = node.nodeValue;
                if (!nodeText) return NodeFilter.FILTER_REJECT;

                // 1) HTML 엔티티/태그 기호가 섞인 텍스트는 건너뜀
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

        // 2) 따옴표 안 구간 범위 미리 수집 → 그 안의 매치는 스킵
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
};