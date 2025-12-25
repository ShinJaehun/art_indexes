window.loadMaster = async function loadMaster({ retryThumbs = false, attempt = 0 } = {}) {
    if (window._loadingMaster) return;
    window._loadingMaster = true;
    try {
        if (window.hasBridge) {
            const { html } = await window.call("get_master");

            // 현재 인덱스 파일 절대 경로 업데이트
            try {
                const info = await window.call("get_current_index_path");
                if (info && info.path) {
                    window.__CURRENT_INDEX_PATH = info.path;
                }
            } catch (e) {
                console.warn("get_current_index_path failed", e);
            }

            window.$("#content").innerHTML = html || "<p>내용 없음</p>";
        } else {
            const blocks = window.$$(".card", document);
            window.$("#content").innerHTML = "";
            if (blocks.length) {
                for (const block of blocks) window.$("#content").appendChild(block.cloneNode(true));
            } else {
                window.$("#content").innerHTML = `<p class="hint">브라우저 미리보기: <code>.card</code> 블록이 없습니다.</p>`;
            }
        }

        // --- P6: 부팅 직후(패키징 exe) 재로드 리트라이 ---
        // 조건:
        //   - 브리지 있음(=데스크톱 앱)
        //   - 카드가 있는데 썸네일이 0개
        //   - retryThumbs=true 인 경우에만
        // 목적:
        //   - 앱 시작 시 backend 쪽에서 1~2회 자동 sync가 도는 동안,
        //     첫 get_master가 "썸네일 없는 HTML"을 반환할 수 있음
        //   - 짧게 몇 번만 재시도해서 최종 HTML(thumb 인라인 포함)을 다시 받는다
        if (window.hasBridge && retryThumbs) {
            const cardCnt = window.$$("#content .card").length;
            const thumbCnt = window.$$("#content img.thumb").length; // thumb-wrap 안이든 어디든 class=thumb 기준

            if (cardCnt > 0 && thumbCnt === 0 && attempt < window._BOOT_RELOAD_MAX) {
                // 너무 시끄럽지 않게: 상태바는 띄우지 않고, 조용히 재시도
                window._loadingMaster = false;
                setTimeout(() => {
                    // attempt 누적해서 재호출
                    window.loadMaster({ retryThumbs: true, attempt: attempt + 1 });
                }, window._BOOT_RELOAD_DELAY_MS);
                return;
            }
        }

        // P5-1: 매번 로드 후 현재 파일 경로 표시
        window.updateIndexPathBar();
        window.enhanceBlocks();
        window.wireGlobalToolbar();

        // toolbar.js가 제공하는 보조 툴바 바인딩(재빌드/프룬 등)
        if (typeof window.wireExtraToolbar === "function") {
            window.wireExtraToolbar();
        }

    } catch (exc) {
        console.error(exc);
        window.showStatus({ level: "error", title: "로드 실패", lines: [String(exc?.message || exc)] });
    } finally {
        window._loadingMaster = false;
    }
};