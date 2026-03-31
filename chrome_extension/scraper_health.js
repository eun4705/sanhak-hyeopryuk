/**
 * KB Life e-건강보험 스크래퍼 — Chrome Extension (모바일 API)
 *
 * 사용법:
 * 1. 모바일 모드로 m.kblife.co.kr 상품 페이지 접속
 * 2. 수동으로 보험료 계산 1번 실행
 * 3. 콘솔에서:
 *    window.__scrapeHealth('337600104', 'e건강보험_일반심사')
 *    window.__scrapeHealth('331600104', 'e건강보험_간편심사355')
 */

(function () {
  'use strict';

  const BATCH_SIZE = 10;
  const PLAN_NAMES = ['든든', '실속', '뇌심', '입원'];

  // 선택형 특약 이름 매핑 (일반심사 837xxx, 간편심사 831xxx)
  const SELECTABLE_NAMES = {
    // 일반심사형
    '837667104': '중환자실입원(1일이상 60일한도)(갱)(해약환급금 미지급형)',
    '837668104': '응급실내원(응급)(갱)(해약환급금 미지급형)',
    '837606104': '간암·폐암·췌장암진단(갱)(해약환급금 미지급형)',
    '837611104': '암(기타피부암 및 갑상선암 제외) 주요치료(갱)(해약환급금 미지급형)',
    '837612104': '기타피부암 및 갑상선암 주요치료(갱)(해약환급금 미지급형)',
    // 간편심사형
    '831667104': '(간편355)중환자실입원(1일이상 60일한도)(갱)(해약환급금 미지급형)',
    '831668104': '(간편355)응급실내원(응급)(갱)(해약환급금 미지급형)',
    '831606104': '(간편355)간암·폐암·췌장암진단(갱)(해약환급금 미지급형)',
    '831611104': '(간편355)암(기타피부암 및 갑상선암 제외) 주요치료(갱)(해약환급금 미지급형)',
    '831612104': '(간편355)기타피부암 및 갑상선암 주요치료(갱)(해약환급금 미지급형)',
  };

  // 나이별 보험기간
  // 20~34세: 30년만, 35~64세: 10년/20년
  function getInsuranceTerms(age) {
    if (age >= 20 && age <= 34) return [30];
    if (age >= 35 && age <= 64) return [10, 20];
    return [];
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

  function sKey(prodCd) { return `kb_health_${prodCd}`; }

  async function calcOne(prodCd, birthday, genderCode, planName, insuranceTerm) {
    let data;
    try {
      data = await ajax.post('INSURANCEPLAN', '/premium-calculate', null, {
        productCode: prodCd,
        birthday,
        genderCode,
        isVariable: false,
        isAnnuity: false,
        pcOnline: true,
        planName,
      });
    } catch (e) {
      const txt = (e.responseText || '').substring(0, 200).toLowerCase();
      if (txt.includes('contrary') || txt.includes('firewall') || txt.includes('blocked')) {
        return { error: 'waf' };
      }
      return { error: String(e).substring(0, 100) };
    }

    if (!data || !data.results || !data.results.length) return { error: 'empty' };

    let resultId = data.results[0];
    // PC: vest 디코딩
    if (typeof cmmUtil !== 'undefined' && cmmUtil.vestDec) {
      try { resultId = cmmUtil.vestDec(resultId); } catch(e) {}
    }
    if (!resultId || !/^[0-9]+$/.test(String(resultId))) return { error: 'no_resultId' };

    // 1) 선택형 특약 보험료 파싱 (results[1], Java toString 형식)
    const selectRiders = [];
    if (data.results.length > 1 && typeof data.results[1] === 'string') {
      try {
        const raw = data.results[1];
        const matches = [...raw.matchAll(/\{([^}]+)\}/g)];
        for (const m of matches) {
          const obj = {};
          m[1].split(',').forEach(pair => {
            const kv = pair.trim().split('=');
            if (kv.length === 2) obj[kv[0].trim()] = kv[1].trim();
          });
          if (obj.prodCd && obj.prodCd !== prodCd) {
            selectRiders.push({
              prodCd: obj.prodCd,
              premium: parseFloat(obj.prmum) || 0,
              entryAmount: parseFloat(obj.riderFaceamnt) || 0,
            });
          }
        }
      } catch (e) { }
    }

    // 2) 기본 특약 상세 조회 (insuranceplans/{id})
    let detail = null;
    try {
      detail = await ajax.get('INSURANCEPLAN', '/insuranceplans/' + resultId);
    } catch (e) {
      return { error: 'detail_fetch' };
    }

    // 3) 기본 특약 (riders에 이름+보험료 포함)
    const allRiders = [];
    let totalPremium = 0;

    // 주계약
    totalPremium += detail.mainPremium || 0;

    // 기본 특약
    for (const r of (detail.riders || [])) {
      allRiders.push({
        prodCd: r.riderCode,
        name: r.riderName,
        premium: r.riderPremium || 0,
        entryAmount: r.entryAmount || 0,
      });
      totalPremium += r.riderPremium || 0;
    }

    // 선택형 특약 추가 (기본에 없는 것만)
    const basicCodes = new Set(allRiders.map(r => r.prodCd));
    for (const sr of selectRiders) {
      if (!basicCodes.has(sr.prodCd)) {
        allRiders.push({
          prodCd: sr.prodCd,
          name: SELECTABLE_NAMES[sr.prodCd] || sr.prodCd,
          premium: sr.premium,
          entryAmount: sr.entryAmount,
        });
        totalPremium += sr.premium;
      }
    }

    return {
      results: {
        planFullName: detail.productName || '',
        insuranceTerm: detail.insuranceTerm,
        paymentTerm: detail.paymentTerm,
        mainPremium: detail.mainPremium || 0,
        totalPremium,
        riders: allRiders,
      }
    };
  }

  async function scrapeHealth(prodCd, productName) {
    if (typeof ajax === 'undefined') {
      console.error('ajax 없음! 먼저 수동으로 보험료 계산 1번 해주세요.');
      return;
    }

    if (!productName) productName = prodCd;

    console.log(`=== ${productName} (${prodCd}) 스크래핑 시작 ===`);

    const sk = sKey(prodCd);
    const saved = JSON.parse(localStorage.getItem(sk + '_done') || '{}');
    const savedResults = JSON.parse(localStorage.getItem(sk + '_results') || '[]');
    console.log(`이전: ${Object.keys(saved).length}건 완료, ${savedResults.length}건 저장`);

    // 작업 목록 생성
    const items = [];
    for (let age = 20; age <= 64; age++) {
      const terms = getInsuranceTerms(age);
      for (const term of terms) {
        for (const plan of PLAN_NAMES) {
          for (const [gc, gn] of [['1', '남'], ['2', '여']]) {
            const key = `${age}_${gn}_${plan}_${term}`;
            if (saved[key]) continue;
            items.push({
              key, age,
              birthday: `${2026 - age}0101`,
              gc, gn, plan, term,
            });
          }
        }
      }
    }

    const totalCombos = items.length + Object.keys(saved).length;
    console.log(`전체: ${totalCombos}건, 완료: ${Object.keys(saved).length}건, 남은: ${items.length}건`);
    console.log(`배치: ${BATCH_SIZE}건씩 병렬`);

    if (items.length === 0) {
      console.log('모든 작업 완료!');
      return;
    }

    let success = 0, errors = 0, wafHit = false;
    const results = [...savedResults];
    const startTime = Date.now();

    for (let b = 0; b < items.length; b += BATCH_SIZE) {
      const batch = items.slice(b, b + BATCH_SIZE);
      const t0 = Date.now();

      const batchResults = await Promise.all(
        batch.map(item => calcOne(prodCd, item.birthday, item.gc, item.plan, item.term))
      );

      const dt = ((Date.now() - t0) / 1000).toFixed(1);

      for (let j = 0; j < batch.length; j++) {
        const item = batch[j];
        const result = batchResults[j];

        if (result.error === 'waf') {
          wafHit = true;
          console.error(`WAF! key=${item.key}`);
          continue;
        }

        if (result.results) {
          results.push({
            _key: item.key,
            product: productName,
            prodCd,
            age: item.age,
            gender: item.gn,
            planName: item.plan,
            insuranceTerm: result.results.insuranceTerm,
            paymentTerm: result.results.paymentTerm,
            paymentMethod: '월납',
            totalPremium: result.results.totalPremium,
            riders: result.results.riders,
          });
          saved[item.key] = true;
          success++;
        } else {
          errors++;
          if (errors <= 5) console.log(`에러: ${item.key} - ${result.error}`);
        }
      }

      const elapsed = (Date.now() - startTime) / 1000;
      const batchNum = Math.floor(b / BATCH_SIZE) + 1;
      const totalBatches = Math.ceil(items.length / BATCH_SIZE);
      const remaining = Math.round((totalBatches - batchNum) * (elapsed / batchNum));
      console.log(
        `[${batchNum}/${totalBatches}] ${dt}s | 성공=${success} 에러=${errors} | 남은: ~${Math.round(remaining / 60)}분`
      );

      localStorage.setItem(sk + '_done', JSON.stringify(saved));
      localStorage.setItem(sk + '_results', JSON.stringify(results));

      if (wafHit) {
        console.error(`WAF 차단. 성공: ${success}건`);
        const lines = results.map(r => JSON.stringify(r)).join('\n');
        downloadJSON(lines, `${productName}_${results.length}건_중단.jsonl`);
        return;
      }
    }

    console.log(`\n=== ${productName} 완료! 성공=${success} 에러=${errors} ===`);
    localStorage.setItem(sk + '_done', JSON.stringify(saved));
    localStorage.setItem(sk + '_results', JSON.stringify(results));
    const lines = results.map(r => JSON.stringify(r)).join('\n');
    downloadJSON(lines, `${productName}_${results.length}건_완료.jsonl`);
  }

  window.__scrapeHealth = scrapeHealth;

  window.__healthStatus = function () {
    const products = [
      { name: 'e건강보험_일반심사', prodCd: '337600104' },
      { name: 'e건강보험_간편심사355', prodCd: '331600104' },
    ];
    for (const p of products) {
      const done = Object.keys(JSON.parse(localStorage.getItem(sKey(p.prodCd) + '_done') || '{}')).length;
      const saved = JSON.parse(localStorage.getItem(sKey(p.prodCd) + '_results') || '[]').length;
      console.log(`${p.name}: ${done}건 완료, ${saved}건 저장`);
    }
  };

  window.__healthDownload = function (prodCd) {
    const results = JSON.parse(localStorage.getItem(sKey(prodCd) + '_results') || '[]');
    if (!results.length) { console.log('결과 없음'); return; }
    const lines = results.map(r => JSON.stringify(r)).join('\n');
    const name = results[0]?.product || prodCd;
    downloadJSON(lines, `${name}_${results.length}건.jsonl`);
    console.log(`${results.length}건 다운로드`);
  };

  window.__healthReset = function (prodCd) {
    localStorage.removeItem(sKey(prodCd) + '_done');
    localStorage.removeItem(sKey(prodCd) + '_results');
    console.log(`${prodCd} 초기화`);
  };

  if (location.href.includes('productDetails') || location.href.includes('product-detail')) {
    console.log('=== e-건강보험 스크래퍼 로드됨 ===');
    console.log('  window.__scrapeHealth("337600104", "e건강보험_일반심사")');
    console.log('  window.__scrapeHealth("331600104", "e건강보험_간편심사355")');
    console.log('  window.__healthStatus()  → 진행 상태');
    console.log('  window.__healthDownload("상품코드") → 다운로드');
  }
})();
