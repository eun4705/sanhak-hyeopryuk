// popup.js — 팝업 UI 로직
(function () {
  'use strict';

  const logsEl = document.getElementById('logs');
  const startBtn = document.getElementById('startBtn');
  const statusBtn = document.getElementById('statusBtn');
  const dlBtn = document.getElementById('dlBtn');
  const resetBtn = document.getElementById('resetBtn');
  const productSel = document.getElementById('product');
  const ajaxStatusEl = document.getElementById('ajaxStatus');
  const runStatusEl = document.getElementById('runStatus');

  let tabId = null;
  let isRunning = false;
  let pollTimer = null;

  // 현재 탭 ID 가져오기
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]) {
      tabId = tabs[0].id;
      startPolling();
      // ajax 체크 요청
      sendTobridge({ cmd: 'check_ajax' });
    }
  });

  function sendTobridge(msg) {
    if (!tabId) return;
    msg.target = 'bridge';
    chrome.tabs.sendMessage(tabId, msg, () => {
      if (chrome.runtime.lastError) {
        appendLog('error', '[팝업] 페이지와 연결 안 됨 — KB 사이트에서 열어주세요');
      }
    });
  }

  function parseProduct() {
    const val = productSel.value;
    const [prodCd, action, scope, name] = val.split('|');
    return { prodCd, action, scope, name };
  }

  function getScope(action) {
    if (action.includes('3n5')) return '3n5';
    if (action.includes('health')) return 'health';
    if (action.includes('annuity')) return 'annuity';
    if (action.includes('term')) return 'term';
    if (action.includes('universal')) return 'universal';
    return '';
  }

  // === 버튼 이벤트 ===

  startBtn.addEventListener('click', () => {
    if (isRunning) {
      // 정지 = 페이지 새로고침
      if (confirm('스크래핑을 중지하시겠습니까?\n(페이지가 새로고침됩니다. 진행 상태는 저장됨)')) {
        chrome.tabs.reload(tabId);
        isRunning = false;
        updateRunUI();
      }
      return;
    }

    const { prodCd, action, name } = parseProduct();
    appendLog('log', `>>> ${name} 시작`);
    sendTobridge({ cmd: 'start', action, prodCd, name });
    isRunning = true;
    updateRunUI();
  });

  statusBtn.addEventListener('click', () => {
    sendTobridge({ cmd: 'status' });
    appendLog('log', '>>> 상태 조회 중...');
  });

  dlBtn.addEventListener('click', () => {
    const { prodCd, action } = parseProduct();
    const scope = getScope(action);
    sendTobridge({ cmd: 'download', scope, prodCd });
    appendLog('log', '>>> 다운로드 요청');
  });

  resetBtn.addEventListener('click', () => {
    const { prodCd, action, name } = parseProduct();
    if (!confirm(`${name} 진행 상태를 초기화하시겠습니까?`)) return;
    const scope = getScope(action);
    sendTobridge({ cmd: 'reset', scope, prodCd });
    appendLog('log', `>>> ${name} 초기화`);
  });

  // === 폴링 ===

  function startPolling() {
    pollTimer = setInterval(poll, 500);
    poll();
  }

  function poll() {
    if (!tabId) return;
    chrome.tabs.sendMessage(
      tabId,
      { target: 'bridge', cmd: 'poll' },
      (resp) => {
        if (chrome.runtime.lastError || !resp) return;

        // 로그 추가
        if (resp.logs) {
          for (const log of resp.logs) {
            appendLog(log.level, log.msg);
          }
        }

        // 상태 업데이트
        if (resp.state) {
          updateAjaxStatus(resp.state.ajaxReady);
          if (resp.state.running !== undefined) {
            if (isRunning && !resp.state.running) {
              // 스크래핑 완료됨
              isRunning = false;
              updateRunUI();
            } else if (!isRunning && resp.state.running) {
              isRunning = true;
              updateRunUI();
            }
          }
        }
      }
    );
  }

  // === UI 업데이트 ===

  function updateAjaxStatus(ready) {
    if (ready) {
      ajaxStatusEl.innerHTML = '<span class="dot green"></span>ajax 준비됨';
    } else {
      ajaxStatusEl.innerHTML = '<span class="dot red"></span>ajax 없음 — 계산 1회 실행 필요';
    }
  }

  function updateRunUI() {
    if (isRunning) {
      startBtn.textContent = '정지';
      startBtn.classList.add('running');
      runStatusEl.innerHTML = '<span class="dot yellow"></span>스크래핑 중...';
      productSel.disabled = true;
    } else {
      startBtn.textContent = '시작';
      startBtn.classList.remove('running');
      runStatusEl.innerHTML = '';
      productSel.disabled = false;
    }
  }

  function appendLog(level, msg) {
    const line = document.createElement('div');
    line.className = 'log-line ' + level;
    line.textContent = msg;
    logsEl.appendChild(line);
    logsEl.scrollTop = logsEl.scrollHeight;

    // 최대 300줄
    while (logsEl.children.length > 300) {
      logsEl.removeChild(logsEl.firstChild);
    }
  }

  // 팝업 닫힐 때 정리
  window.addEventListener('unload', () => {
    if (pollTimer) clearInterval(pollTimer);
  });
})();
