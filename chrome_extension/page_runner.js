// page_runner.js — 페이지 컨텍스트에서 실행
// console.log 가로채기 + 팝업 명령 수신 + 스크래퍼 함수 호출
(function () {
  'use strict';

  // === 로그 전달 (console 오버라이드 없이) ===
  const _postLog = function (level, msg) {
    window.postMessage({ type: 'KB_LOG', level, msg }, '*');
  };

  // === ajax 상태 체크 (주기적) ===
  function reportAjax() {
    window.postMessage({
      type: 'KB_STATE',
      state: { ajaxReady: typeof ajax !== 'undefined' },
    }, '*');
  }
  setInterval(reportAjax, 2000);
  setTimeout(reportAjax, 500);

  // === 명령 수신 ===
  window.addEventListener('message', async (event) => {
    if (event.source !== window) return;
    if (event.data.type !== 'KB_CMD') return;
    const d = event.data;

    if (d.cmd === 'check_ajax') {
      reportAjax();
      return;
    }

    if (d.cmd === 'start') {
      window.postMessage({ type: 'KB_STATE', state: { running: true } }, '*');
      try {
        switch (d.action) {
          case 'scrape_3n5_all':
            await window.__scrapeAll();
            break;
          case 'scrape_3n5':
            await window.__scrape3n5(d.prodCd, d.name);
            break;
          case 'scrape_term':
            await window.__startScraper();
            break;
          case 'scrape_health':
            await window.__scrapeHealth(d.prodCd, d.name);
            break;
          case 'scrape_universal':
            await window.__scrape(d.prodCd, d.name, d.minAge, d.maxAge);
            break;
          case 'scrape_annuity':
            await window.__scrapeAnnuity();
            break;
          default:
            console.error('알 수 없는 action:', d.action);
        }
      } catch (e) {
        console.error('스크래핑 에러:', e);
      }
      window.postMessage({ type: 'KB_STATE', state: { running: false } }, '*');
    }

    if (d.cmd === 'status') {
      if (window.__status3n5) window.__status3n5();
      if (window.__healthStatus) window.__healthStatus();
      if (window.__annuityStatus) window.__annuityStatus();
      if (window.__list) window.__list();
    }

    if (d.cmd === 'download') {
      if (d.scope === '3n5') {
        // 3N5 전체 다운로드: 각 상품별
        var prods = [
          '334000104','344000104','333000104','343000104',
          '332000104','342000104','331000104','341000104',
          '335200104','333200104','331200104','337200104',
          '336000104','346000104','335000104','345000104',
        ];
        for (var p of prods) {
          var sk = 'kb_3n5_' + p;
          var res = JSON.parse(localStorage.getItem(sk + '_results') || '[]');
          if (res.length > 0) {
            var lines = res.map(function(r){return JSON.stringify(r)}).join('\n');
            var blob = new Blob([lines],{type:'text/plain'});
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url; a.download = p + '_' + res.length + '건.jsonl';
            document.body.appendChild(a); a.click(); a.remove();
            URL.revokeObjectURL(url);
          }
        }
      } else if (d.scope === 'health') {
        if (window.__healthDownload) window.__healthDownload(d.prodCd);
      } else if (d.scope === 'annuity') {
        if (window.__annuityDownload) window.__annuityDownload();
      } else if (d.scope === 'term') {
        if (window.__downloadResults) window.__downloadResults();
      } else if (d.scope === 'universal') {
        if (window.__downloadResults) window.__downloadResults(d.prodCd);
      }
    }

    if (d.cmd === 'reset') {
      if (d.scope === '3n5') {
        if (window.__reset3n5) window.__reset3n5(d.prodCd || 'all');
      } else if (d.scope === 'health') {
        if (window.__healthReset) window.__healthReset(d.prodCd);
      } else if (d.scope === 'annuity') {
        if (window.__annuityReset) window.__annuityReset();
      } else if (d.scope === 'term') {
        if (window.__resetScraper) window.__resetScraper();
      } else if (d.scope === 'universal') {
        if (window.__resetScraper) window.__resetScraper(d.prodCd);
      }
    }
  });

  _postLog('log', '[Runner] KB Life 스크래퍼 컨트롤러 로드됨');
})();
