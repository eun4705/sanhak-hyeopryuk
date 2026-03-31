// capture.js — PC 사이트 API 요청 캡쳐
// 페이지 컨텍스트에서 실행, ajax 객체의 모든 호출을 가로채서 기록
(function () {
  'use strict';

  const captured = [];

  // XMLHttpRequest 가로채기
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...args) {
    this._captureMethod = method;
    this._captureUrl = url;
    return origOpen.call(this, method, url, ...args);
  };

  XMLHttpRequest.prototype.send = function (body) {
    const xhr = this;
    const entry = {
      time: new Date().toISOString(),
      method: xhr._captureMethod,
      url: xhr._captureUrl,
      requestBody: null,
      status: null,
      responseBody: null,
    };

    // request body 파싱
    if (body) {
      try {
        entry.requestBody = JSON.parse(body);
      } catch (e) {
        entry.requestBody = body;
      }
    }

    xhr.addEventListener('load', function () {
      entry.status = xhr.status;
      try {
        entry.responseBody = JSON.parse(xhr.responseText);
      } catch (e) {
        entry.responseBody = xhr.responseText?.substring(0, 500);
      }
      entry.responseHeaders = xhr.getAllResponseHeaders();
      captured.push(entry);

      // API 요청만 필터해서 콘솔에 표시
      if (entry.url && entry.url.includes('/api/')) {
        console.log(
          `[CAP] ${entry.method} ${entry.url}\n` +
          `  status: ${entry.status}\n` +
          `  body: ${JSON.stringify(entry.requestBody, null, 2)?.substring(0, 500)}`
        );
      }
    });

    xhr.addEventListener('error', function () {
      entry.status = 'ERROR';
      entry.responseBody = 'network error';
      captured.push(entry);
    });

    return origSend.call(this, body);
  };

  // fetch도 가로채기
  const origFetch = window.fetch;
  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : input.url;
    const method = init?.method || 'GET';
    const entry = {
      time: new Date().toISOString(),
      method,
      url,
      requestBody: null,
      status: null,
      responseBody: null,
    };

    if (init?.body) {
      try {
        entry.requestBody = JSON.parse(init.body);
      } catch (e) {
        entry.requestBody = String(init.body).substring(0, 500);
      }
    }

    try {
      const resp = await origFetch.call(this, input, init);
      entry.status = resp.status;
      const clone = resp.clone();
      try {
        entry.responseBody = await clone.json();
      } catch (e) {
        entry.responseBody = (await clone.text()).substring(0, 500);
      }
      captured.push(entry);

      if (url.includes('/api/')) {
        console.log(`[CAP-fetch] ${method} ${url} → ${resp.status}`);
      }
      return resp;
    } catch (e) {
      entry.status = 'ERROR';
      entry.responseBody = String(e);
      captured.push(entry);
      throw e;
    }
  };

  // 결과 다운로드 함수
  window.__captureDownload = function () {
    const apiOnly = captured.filter(e => e.url && e.url.includes('/api/'));
    const text = JSON.stringify(apiOnly, null, 2);
    const blob = new Blob([text], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'kb_capture_' + Date.now() + '.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    console.log(`${apiOnly.length}건 API 요청 다운로드 (전체 ${captured.length}건 중)`);
  };

  // 캡쳐 목록 보기
  window.__captureList = function () {
    const apiOnly = captured.filter(e => e.url && e.url.includes('/api/'));
    console.log(`=== 캡쳐된 API 요청: ${apiOnly.length}건 ===`);
    apiOnly.forEach((e, i) => {
      console.log(`${i + 1}. [${e.method}] ${e.url} → ${e.status}`);
    });
  };

  // 전체 캡쳐 데이터 보기
  window.__captureAll = function () { return captured; };

  console.log('=== API 캡쳐 시작 ===');
  console.log('이제 수동으로 보험료 계산을 해주세요.');
  console.log('완료 후:');
  console.log('  __captureList()     → 캡쳐 목록');
  console.log('  __captureDownload() → JSON 다운로드');
})();
