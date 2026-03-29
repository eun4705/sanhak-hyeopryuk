/**
 * KB Life 착한정기보험II 스크래퍼 — Chrome Extension Content Script
 *
 * 사용법:
 * 1. 착한정기보험II 상품 페이지에서 첫 계산을 수동으로 1번 실행
 * 2. 콘솔(F12)에서: window.__startScraper() 입력
 * 3. 결과는 자동으로 다운로드됨
 */

(function () {
  'use strict';

  const PROD_CD = '314700102';
  const SR_PROD_CDS = ['314700202', '314700302', '314700402'];
  const KEYWORDS = ['표준체', '비흡연체', '건강체', '슈퍼건강체'];
  const ENTRY_AMOUNT = 100000000;
  const BATCH_SIZE = 10;  // 동시 호출 수

  const PAYMENT_METHODS = [
    { code: '3', name: '월납' },
    { code: '4', name: '3개월납' },
    { code: '5', name: '6개월납' },
    { code: '6', name: '연납' },
  ];

  const AGE_LIMITS = {
    '10_5_1': 70, '10_10_1': 70,
    '60_5_1': 50, '60_7_1': 50, '60_10_1': 50, '60_15_1': 45, '60_20_1': 40, '60_55_2': 50, '60_60_2': 50,
    '65_5_1': 55, '65_7_1': 55, '65_10_1': 55, '65_15_1': 50, '65_20_1': 45, '65_55_2': 50, '65_60_2': 55, '65_65_2': 55,
    '70_5_1': 60, '70_7_1': 60, '70_10_1': 60, '70_15_1': 55, '70_20_1': 50, '70_55_2': 50, '70_60_2': 55, '70_70_2': 60,
    '80_5_1': 70, '80_7_1': 70, '80_10_1': 70, '80_15_1': 65, '80_20_1': 60, '80_55_2': 50, '80_60_2': 55, '80_80_2': 70,
  };

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function downloadJSON(data, filename) {
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function calcOne(birthday, genderCode, ins, insType, pay, payType, paymentMethod) {
    const params = {
      productCode: PROD_CD,
      birthday, genderCode,
      isVariable: 'false', isAnnuity: 'false', pcOnline: 'true',
      keywords: KEYWORDS, isReCal: 'true',
      entryAmount: ENTRY_AMOUNT, paymentMethod,
      insuranceTerm: String(ins), insuranceTermType: String(insType),
      paymentTerm: String(pay), paymentTermType: String(payType),
      annuityStartAge: String(ins), annuityGuaranteeTerm: null,
      prmumCalMthdTpCd: '1', prodCrncCd: '410',
    };

    // [전] 옵션조회 3건
    for (const cd of SR_PROD_CDS) {
      try {
        await ajax.get('INSURANCEPLAN', '/insuranceplan-option/' + cd, null,
          { isVariable: false, isAnnuity: false, riskGrdCd: '3', insuranceAge: 0 });
      } catch (e) { }
    }

    // [핵심] premium-calculate
    let data;
    try {
      data = await ajax.post('INSURANCEPLAN', '/premium-calculate', null, params);
    } catch (e) {
      const txt = (e.responseText || '').substring(0, 200).toLowerCase();
      if (txt.includes('contrary') || txt.includes('firewall') || txt.includes('blocked')) {
        return { error: 'waf' };
      }
      return { error: String(e).substring(0, 100) };
    }

    const resultIds = data.results || [];
    if (!resultIds.length) return { error: 'empty' };

    // [후] 결과조회
    const details = [];
    for (const rid of resultIds) {
      if (!rid || !/^[0-9]+$/.test(String(rid))) continue;
      try {
        const det = await ajax.get('INSURANCEPLAN', '/insuranceplans/' + rid);
        details.push({
          id: rid,
          productName: det.productName || '',
          productShortName: det.productShortName || '',
          mainPremium: det.mainPremium || 0,
          totalPremium: det.premium || 0,
        });
      } catch (e) { }
    }

    // [후] orders + option
    try { await ajax.get('INSURANCEPLAN', '/insuranceplan-code/product-display-fixed-orders'); } catch (e) { }
    try { await ajax.get('INSURANCEPLAN', '/insuranceplan-code/product-display-orders'); } catch (e) { }
    try {
      await ajax.get('INSURANCEPLAN', '/insuranceplan-option/' + PROD_CD, null, {
        genderCode, isVariable: false, isAnnuity: false,
        riskGrdCd: '3', insuranceAge: 0, channel: '1001'
      });
    } catch (e) { }

    return { results: details };
  }

  async function getTermCombos() {
    const d = await ajax.get('INSURANCEPLAN', '/insuranceplan-option/' + PROD_CD, null, {
      genderCode: '1', isVariable: 'false', isAnnuity: 'false',
      riskGrdCd: '3', insuranceAge: '30', channel: '1001'
    });
    const main = d.products[0];
    const insTerms = main.availableInsuranceTerms || [];
    const payTerms = main.availablePaymentTerms || [];

    const combos = [];
    for (const it of insTerms) {
      const matching = payTerms.filter(pt => pt.insrnPdCo === it.bkBhgg);
      for (const pt of matching) {
        combos.push({
          ins: it.bkBhgg, insType: it.bkYsgb,
          pay: pt.nkNigg, payType: pt.nkYsgb,
        });
      }
    }
    return combos;
  }

  async function loadExistingKeys() {
    // 1) localStorage에서 이전 진행 상태
    const saved = JSON.parse(localStorage.getItem('kb_scraper_done') || '{}');

    // 2) existing_keys.json (기존 스크래핑 4004건)
    try {
      const url = document.querySelector('script[src*="scraper.js"]')?.src?.replace('scraper.js', 'existing_keys.json');
      if (url) {
        const resp = await fetch(url);
        const existing = await resp.json();
        let added = 0;
        for (const key of Object.keys(existing)) {
          if (!saved[key]) {
            saved[key] = true;
            added++;
          }
        }
        if (added > 0) console.log(`기존 데이터에서 ${added}건 키 로드`);
      }
    } catch (e) {
      console.log('existing_keys.json 로드 실패 (무시)', e.message);
    }

    return saved;
  }

  async function startScraper() {
    if (typeof ajax === 'undefined') {
      console.error('ajax 객체 없음! 상품 페이지에서 첫 계산을 먼저 수동으로 해주세요.');
      return;
    }

    console.log('=== KB Life 착한정기보험II 스크래퍼 시작 ===');

    // 저장된 진행 상태 + 기존 데이터 키 불러오기
    const saved = await loadExistingKeys();
    const savedResults = JSON.parse(localStorage.getItem('kb_scraper_results') || '[]');
    console.log(`이전 진행: ${Object.keys(saved).length}건 완료 (기존 데이터 포함), ${savedResults.length}건 저장됨`);

    // 보험기간/납입기간 조합
    const combos = await getTermCombos();
    console.log(`보험/납입 조합: ${combos.length}개`);

    // 전체 작업 목록
    const items = [];
    for (const combo of combos) {
      const limitKey = `${combo.ins}_${combo.pay}_${combo.payType}`;
      const maxAge = AGE_LIMITS[limitKey];
      if (!maxAge) continue;

      for (const pm of PAYMENT_METHODS) {
        for (let age = 19; age <= maxAge; age++) {
          for (const [gc, gn] of [['1', '남'], ['2', '여']]) {
            const key = `${age}_${gn}_${combo.ins}_${combo.pay}_${pm.code}`;
            if (saved[key]) continue;
            items.push({ key, age, birthday: `${2026 - age}0101`, gc, gn, combo, pm });
          }
        }
      }
    }

    console.log(`남은 작업: ${items.length}건`);
    console.log(`배치 크기: ${BATCH_SIZE}건 동시 호출`);
    console.log(`예상 배치 수: ${Math.ceil(items.length / BATCH_SIZE)}`);
    console.log('');

    let success = 0;
    let errors = 0;
    let wafHit = false;
    const results = [...savedResults];
    const startTime = Date.now();

    // 배치 단위로 병렬 호출
    for (let b = 0; b < items.length; b += BATCH_SIZE) {
      const batch = items.slice(b, b + BATCH_SIZE);
      const t0 = Date.now();

      // 10건 동시 호출
      const batchResults = await Promise.all(
        batch.map(item => calcOne(
          item.birthday, item.gc,
          item.combo.ins, item.combo.insType,
          item.combo.pay, item.combo.payType,
          item.pm.code
        ))
      );

      const dt = ((Date.now() - t0) / 1000).toFixed(1);

      // 결과 처리
      for (let j = 0; j < batch.length; j++) {
        const item = batch[j];
        const result = batchResults[j];

        if (result.error === 'waf') {
          wafHit = true;
          console.error(`WAF 차단! key=${item.key}`);
          continue;
        }

        if (result.results) {
          const record = {
            _key: item.key,
            product: '착한정기보험II',
            age: item.age, gender: item.gn,
            insuranceTerm: item.combo.ins, insuranceTermType: item.combo.insType,
            paymentTerm: item.combo.pay, paymentTermType: item.combo.payType,
            paymentMethod: item.pm.name,
            entryAmount: ENTRY_AMOUNT,
            results: result.results,
          };
          results.push(record);
          saved[item.key] = true;
          success++;
        } else {
          errors++;
        }
      }

      // 배치 로그
      const elapsed = (Date.now() - startTime) / 1000;
      const remaining = Math.round((items.length - b - batch.length) / BATCH_SIZE * (elapsed / ((b / BATCH_SIZE) + 1)));
      console.log(
        `[배치 ${Math.floor(b / BATCH_SIZE) + 1}] ${batch.length}건 ${dt}s | ` +
        `총 성공=${success} 에러=${errors} | ` +
        `남은: ~${Math.round(remaining / 60)}분`
      );

      // done 키 저장
      localStorage.setItem('kb_scraper_done', JSON.stringify(saved));

      // 100건마다 자동 다운로드 + results 비우기
      if (results.length >= 100) {
        const lines = results.map(r => JSON.stringify(r)).join('\n');
        downloadJSON(lines, `착한정기보험II_${Date.now()}.jsonl`);
        results.length = 0;
        localStorage.removeItem('kb_scraper_results');
        console.log('[자동저장] 100건 다운로드 + localStorage 비움');
      } else {
        localStorage.setItem('kb_scraper_results', JSON.stringify(results));
      }

      if (wafHit) {
        console.error(`WAF 차단됨. 성공: ${success}건`);
        const lines = results.map(r => JSON.stringify(r)).join('\n');
        downloadJSON(lines, `착한정기보험II_${results.length}건_중단.jsonl`);
        return;
      }
    }

    // 완료
    console.log('\n=== 완료! ===');
    console.log(`성공: ${success}건, 에러: ${errors}건`);

    localStorage.setItem('kb_scraper_done', JSON.stringify(saved));
    localStorage.setItem('kb_scraper_results', JSON.stringify(results));

    const lines = results.map(r => JSON.stringify(r)).join('\n');
    downloadJSON(lines, `착한정기보험II_${success}건_완료.jsonl`);
  }

  // 전역에 노출
  window.__startScraper = startScraper;

  // 결과 다운로드 함수
  window.__downloadResults = function () {
    const results = JSON.parse(localStorage.getItem('kb_scraper_results') || '[]');
    if (!results.length) {
      console.log('저장된 결과 없음');
      return;
    }
    const lines = results.map(r => JSON.stringify(r)).join('\n');
    downloadJSON(lines, `착한정기보험II_${results.length}건.jsonl`);
    console.log(`${results.length}건 다운로드`);
  };

  // 진행 초기화
  window.__resetScraper = function () {
    localStorage.removeItem('kb_scraper_done');
    localStorage.removeItem('kb_scraper_results');
    console.log('진행 상태 초기화됨');
  };

  // 페이지 로드 시 안내
  if (location.href.includes('productDetails') || location.href.includes('product-detail')) {
    console.log('=== KB Life Scraper 로드됨 ===');
    console.log('사용법:');
    console.log('  1. 먼저 수동으로 보험료 계산 1번 실행');
    console.log('  2. window.__startScraper()  → 스크래핑 시작');
    console.log('  3. window.__downloadResults() → 결과 다운로드');
    console.log('  4. window.__resetScraper()  → 진행 초기화');
  }
})();
