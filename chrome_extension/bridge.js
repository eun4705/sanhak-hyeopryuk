// bridge.js — content script
// 1) 페이지 컨텍스트에 스크래퍼 스크립트 주입
// 2) popup ↔ 페이지 컨텍스트 메시지 중계

const SCRIPTS = [
  'scraper.js', 'scraper_universal.js', 'scraper_health.js',
  'scan_annuity.js', 'scraper_annuity.js', 'scraper_3n5.js',
  'page_runner.js',
];

for (const file of SCRIPTS) {
  const s = document.createElement('script');
  s.src = chrome.runtime.getURL(file);
  (document.head || document.documentElement).appendChild(s);
}

// 페이지 컨텍스트에서 올라오는 로그/상태 저장
let logs = [];
let scrapeState = { running: false, ajaxReady: false };

window.addEventListener('message', (event) => {
  if (event.source !== window) return;
  const d = event.data;

  if (d.type === 'KB_LOG') {
    logs.push({ level: d.level, msg: d.msg, t: Date.now() });
    if (logs.length > 500) logs = logs.slice(-300);
  }

  if (d.type === 'KB_STATE') {
    Object.assign(scrapeState, d.state);
  }
});

// popup에서 오는 메시지 처리
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target !== 'bridge') return false;

  if (msg.cmd === 'poll') {
    const newLogs = logs.splice(0);
    sendResponse({ logs: newLogs, state: scrapeState });
    return true;
  }

  // 나머지 명령은 페이지 컨텍스트로 전달
  window.postMessage({ type: 'KB_CMD', ...msg }, '*');
  sendResponse({ ok: true });
  return true;
});
