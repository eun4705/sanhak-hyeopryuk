/**
 * KB Life 범용 보험료 스크래퍼 — Chrome Extension (모바일 API)
 *
 * 사용법:
 * 1. 모바일 모드로 m.kblife.co.kr 상품 페이지 접속
 * 2. 수동으로 보험료 계산 1번 실행
 * 3. 콘솔에서:
 *    window.__scrape('316401101', '지켜주는교통안심보험')
 *    window.__list()
 *    window.__downloadResults()
 *    window.__resetScraper()
 */

(function () {
  'use strict';

  const BATCH_SIZE = 10;

  const PRODUCTS = [
    { name: "3N5_간편335_표준형", prodCd: "334000104" },
    { name: "3N5_간편335_표준형_납입면제", prodCd: "344000104" },
    { name: "3N5_간편335_미지급형", prodCd: "333000104" },
    { name: "3N5_간편335_미지급형_납입면제", prodCd: "343000104" },
    { name: "3N5_간편355_표준형", prodCd: "332000104" },
    { name: "3N5_간편355_표준형_납입면제", prodCd: "342000104" },
    { name: "3N5_간편355_미지급형", prodCd: "331000104" },
    { name: "3N5_간편355_미지급형_납입면제", prodCd: "341000104" },
    { name: "3N5_갱신_간편315_미지급형", prodCd: "335200104" },
    { name: "3N5_갱신_간편335_미지급형", prodCd: "333200104" },
    { name: "3N5_갱신_간편355_미지급형", prodCd: "331200104" },
    { name: "3N5_갱신_일반심사_미지급형", prodCd: "337200104" },
    { name: "3N5_일반심사_표준형", prodCd: "336000104" },
    { name: "3N5_일반심사_표준형_납입면제", prodCd: "346000104" },
    { name: "3N5_일반심사_미지급형", prodCd: "335000104" },
    { name: "3N5_일반심사_미지급형_납입면제", prodCd: "345000104" },
    { name: "착한암보험", prodCd: "316100104" },
    { name: "e건강보험_일반심사", prodCd: "337600104" },
    { name: "e건강보험_간편심사355", prodCd: "331600104" },
    { name: "착한정기보험II", prodCd: "314700102" },
    { name: "하이파이브연금", prodCd: "118500105" },
  ];

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

  function sKey(prodCd) { return `kb_uni_${prodCd}`; }

  async function getProductInfo(prodCd) {
    const d = await ajax.get('INSURANCEPLAN', '/insuranceplan-option/' + prodCd, null, {
      genderCode: '1', isVariable: 'false', isAnnuity: 'false',
      riskGrdCd: '3', insuranceAge: '30', channel: '1001'
    });

    const main = d.products[0];
    const insTerms = main.availableInsuranceTerms || [];
    const payTerms = main.availablePaymentTerms || [];
    const minAmount = parseInt(main.gsCsgiga || '1000000');
    const maxAmount = parseInt(main.gsCdgiga || minAmount);
    const isAnnuity = (main.annuityYn === 'Y');
    const isVariable = (main.fundYn === 'Y');
    const subProdCds = d.products.slice(1, 4).map(p => p.gsSpSpcd1).filter(Boolean);

    const combos = [];
    for (const it of insTerms) {
      const matching = payTerms.filter(pt => pt.insrnPdCo === it.bkBhgg);
      if (matching.length === 0) {
        // 납입기간 없으면 보험기간만으로 (일시납 등)
        combos.push({ ins: it.bkBhgg, insType: it.bkYsgb, pay: '0', payType: '1' });
      } else {
        for (const pt of matching) {
          combos.push({ ins: it.bkBhgg, insType: it.bkYsgb, pay: pt.nkNigg, payType: pt.nkYsgb });
        }
      }
    }

    // 나이 범위: 첫 호출 응답에서 추천 정보로 파악하거나, option API로 탐색
    // 일단 19~80 범위에서 option API로 확인
    const ageLimits = {};
    for (const combo of combos) {
      const key = `${combo.ins}_${combo.pay}_${combo.payType}`;
      let maxAge = 19;

      for (let age = 80; age >= 19; age -= 5) {
        try {
          const opt = await ajax.get('INSURANCEPLAN', '/insuranceplan-option/' + prodCd, null, {
            genderCode: '1', isVariable: String(isVariable), isAnnuity: String(isAnnuity),
            riskGrdCd: '3', insuranceAge: String(age), channel: '1001'
          });
          const m = opt.products[0];
          const hasIns = (m.availableInsuranceTerms || []).some(t => t.bkBhgg === combo.ins);
          if (hasIns) { maxAge = age; break; }
        } catch (e) { }
      }

      // 상세 스캔
      for (let age = Math.min(maxAge + 4, 80); age > maxAge; age--) {
        try {
          const opt = await ajax.get('INSURANCEPLAN', '/insuranceplan-option/' + prodCd, null, {
            genderCode: '1', isVariable: String(isVariable), isAnnuity: String(isAnnuity),
            riskGrdCd: '3', insuranceAge: String(age), channel: '1001'
          });
          const m = opt.products[0];
          const hasIns = (m.availableInsuranceTerms || []).some(t => t.bkBhgg === combo.ins);
          if (hasIns) { maxAge = age; break; }
        } catch (e) { }
      }

      ageLimits[key] = maxAge;
    }

    // paymentMethod 감지: 일시납(payTerm=0)이면 "8", 아니면 일반 납입주기
    let paymentMethods;
    if (combos.every(c => c.pay === '0')) {
      paymentMethods = [{ code: '8', name: '일시납' }];
    } else if (combos.some(c => c.pay === '0')) {
      paymentMethods = [
        { code: '3', name: '월납' },
        { code: '4', name: '3개월납' },
        { code: '5', name: '6개월납' },
        { code: '6', name: '연납' },
        { code: '8', name: '일시납' },
      ];
    } else {
      paymentMethods = [
        { code: '3', name: '월납' },
        { code: '4', name: '3개월납' },
        { code: '5', name: '6개월납' },
        { code: '6', name: '연납' },
      ];
    }

    return { combos, ageLimits, subProdCds, entryAmount: minAmount, isAnnuity, isVariable, paymentMethods };
  }

  async function calcOne(prodCd, subProdCds, birthday, genderCode, ins, insType, pay, payType, paymentMethod, entryAmount, isAnnuity, isVariable) {
    const params = {
      productCode: prodCd,
      birthday, genderCode,
      isVariable, isAnnuity,
      pcOnline: true,
      isReCal: 'true',
      entryAmount, paymentMethod,
      insuranceTerm: String(ins), insuranceTermType: insType,
      paymentTerm: String(pay), paymentTermType: payType,
    };

    // [전] WAF 더미
    for (const cd of subProdCds) {
      try {
        await ajax.get('INSURANCEPLAN', '/insuranceplan-option/' + cd, null,
          { isVariable: false, isAnnuity: false, riskGrdCd: '3', insuranceAge: 0 });
      } catch (e) { }
    }

    // premium-calculate (정기보험과 동일)
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

    if (!data) return { error: 'no_response' };

    const details = [];
    const resultIds = data.results || [];
    const resultId = data.result;

    if (resultId) {
      try {
        const det = await ajax.get('INSURANCEPLAN', '/insuranceplans/' + resultId);
        details.push({
          id: resultId,
          productName: det.productName || '',
          productShortName: det.productShortName || '',
          mainPremium: det.mainPremium || 0,
          totalPremium: det.premium || 0,
        });
      } catch (e) { }
    } else if (resultIds.length > 0) {
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
    }

    if (!details.length) return { error: 'empty' };

    // [후] WAF 더미
    try { await ajax.get('INSURANCEPLAN', '/insuranceplan-code/product-display-fixed-orders'); } catch (e) { }
    try { await ajax.get('INSURANCEPLAN', '/insuranceplan-code/product-display-orders'); } catch (e) { }

    return { results: details };
  }

  async function getProductInfoFast(prodCd) {
    // 나이 스캔 없이 option API 1번만 호출해서 기본 정보만 가져옴
    const d = await ajax.get('INSURANCEPLAN', '/insuranceplan-option/' + prodCd, null, {
      genderCode: '1', isVariable: 'false', isAnnuity: 'false',
      riskGrdCd: '3', insuranceAge: '30', channel: '1001'
    });

    const main = d.products[0];
    const insTerms = main.availableInsuranceTerms || [];
    const payTerms = main.availablePaymentTerms || [];
    const minAmount = parseInt(main.gsCsgiga || '1000000');
    const isAnnuity = (main.annuityYn === 'Y');
    const isVariable = (main.fundYn === 'Y');
    const subProdCds = d.products.slice(1, 4).map(p => p.gsSpSpcd1).filter(Boolean);

    const combos = [];
    for (const it of insTerms) {
      const matching = payTerms.filter(pt => pt.insrnPdCo === it.bkBhgg);
      if (matching.length === 0) {
        combos.push({ ins: it.bkBhgg, insType: it.bkYsgb, pay: '0', payType: '1' });
      } else {
        for (const pt of matching) {
          combos.push({ ins: it.bkBhgg, insType: it.bkYsgb, pay: pt.nkNigg, payType: pt.nkYsgb });
        }
      }
    }

    let paymentMethods;
    if (combos.every(c => c.pay === '0')) {
      paymentMethods = [{ code: '8', name: '일시납' }];
    } else if (combos.some(c => c.pay === '0')) {
      paymentMethods = [
        { code: '3', name: '월납' }, { code: '4', name: '3개월납' },
        { code: '5', name: '6개월납' }, { code: '6', name: '연납' },
        { code: '8', name: '일시납' },
      ];
    } else {
      paymentMethods = [
        { code: '3', name: '월납' }, { code: '4', name: '3개월납' },
        { code: '5', name: '6개월납' }, { code: '6', name: '연납' },
      ];
    }

    return { combos, subProdCds, entryAmount: minAmount, isAnnuity, isVariable, paymentMethods };
  }

  async function scrape(prodCd, productName, minAge, maxAge) {
    if (typeof ajax === 'undefined') {
      console.error('ajax 없음! 먼저 수동으로 보험료 계산 1번 해주세요.');
      return;
    }

    if (!minAge) minAge = 19;
    if (!maxAge) maxAge = 70;

    const prod = PRODUCTS.find(p => p.prodCd === prodCd);
    if (!productName) productName = prod ? prod.name : prodCd;

    console.log(`=== ${productName} (${prodCd}) 스크래핑 시작 ===`);
    console.log(`나이 범위: ${minAge}~${maxAge}세`);

    const sk = sKey(prodCd);
    const saved = JSON.parse(localStorage.getItem(sk + '_done') || '{}');
    const savedResults = JSON.parse(localStorage.getItem(sk + '_results') || '[]');
    console.log(`이전: ${Object.keys(saved).length}건 완료, ${savedResults.length}건 저장`);

    console.log('상품 옵션 분석 중 (빠른 모드)...');
    const info = await getProductInfoFast(prodCd);
    console.log(`조합: ${info.combos.length}개, 가입금액: ${info.entryAmount.toLocaleString()}원`);
    console.log(`납입주기: ${info.paymentMethods.map(p => p.name).join(', ')}`);

    // 작업 목록
    const items = [];
    for (const combo of info.combos) {
      const pms = (combo.pay === '0')
        ? [{ code: '8', name: '일시납' }]
        : info.paymentMethods.filter(p => p.code !== '8');

      for (const pm of pms) {
        for (let age = minAge; age <= maxAge; age++) {
          for (const [gc, gn] of [['1', '남'], ['2', '여']]) {
            const key = `${age}_${gn}_${combo.ins}_${combo.pay}_${pm.code}`;
            if (saved[key]) continue;
            items.push({ key, age, birthday: `${2026 - age}0101`, gc, gn, combo, pm });
          }
        }
      }
    }

    console.log(`남은: ${items.length}건 (배치 ${BATCH_SIZE}건)`);
    if (items.length === 0) { console.log('완료!'); return; }

    let success = 0, errors = 0, wafHit = false;
    const results = [...savedResults];
    const startTime = Date.now();

    for (let b = 0; b < items.length; b += BATCH_SIZE) {
      const batch = items.slice(b, b + BATCH_SIZE);
      const t0 = Date.now();

      const batchResults = await Promise.all(
        batch.map(item => calcOne(
          prodCd, info.subProdCds,
          item.birthday, item.gc,
          item.combo.ins, item.combo.insType,
          item.combo.pay, item.combo.payType,
          item.pm.code, info.entryAmount,
          info.isAnnuity, info.isVariable
        ))
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
            product: productName, prodCd,
            age: item.age, gender: item.gn,
            insuranceTerm: item.combo.ins, insuranceTermType: item.combo.insType,
            paymentTerm: item.combo.pay, paymentTermType: item.combo.payType,
            paymentMethod: item.pm.name,
            entryAmount: info.entryAmount,
            results: result.results,
          });
          saved[item.key] = true;
          success++;
        } else {
          errors++;
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

  window.__scrape = scrape;

  window.__list = function () {
    console.log('=== 상품 목록 ===');
    for (const p of PRODUCTS) {
      const done = Object.keys(JSON.parse(localStorage.getItem(sKey(p.prodCd) + '_done') || '{}')).length;
      const saved = JSON.parse(localStorage.getItem(sKey(p.prodCd) + '_results') || '[]').length;
      const status = done > 0 ? `${done}건 완료, ${saved}건 저장` : '미시작';
      console.log(`  ${p.prodCd} | ${p.name} | ${status}`);
    }
    console.log('\n사용: window.__scrape("상품코드", "이름")');
  };

  window.__downloadResults = function (prodCd) {
    if (prodCd) {
      const results = JSON.parse(localStorage.getItem(sKey(prodCd) + '_results') || '[]');
      if (!results.length) { console.log('결과 없음'); return; }
      const prod = PRODUCTS.find(p => p.prodCd === prodCd);
      const name = prod ? prod.name : prodCd;
      downloadJSON(results.map(r => JSON.stringify(r)).join('\n'), `${name}_${results.length}건.jsonl`);
      console.log(`${results.length}건 다운로드`);
    } else {
      for (const p of PRODUCTS) {
        const results = JSON.parse(localStorage.getItem(sKey(p.prodCd) + '_results') || '[]');
        if (results.length > 0) {
          downloadJSON(results.map(r => JSON.stringify(r)).join('\n'), `${p.name}_${results.length}건.jsonl`);
          console.log(`${p.name}: ${results.length}건`);
        }
      }
    }
  };

  window.__resetScraper = function (prodCd) {
    if (prodCd) {
      localStorage.removeItem(sKey(prodCd) + '_done');
      localStorage.removeItem(sKey(prodCd) + '_results');
      console.log(`${prodCd} 초기화`);
    } else {
      for (const p of PRODUCTS) {
        localStorage.removeItem(sKey(p.prodCd) + '_done');
        localStorage.removeItem(sKey(p.prodCd) + '_results');
      }
      console.log('전체 초기화');
    }
  };

  if (location.href.includes('productDetails') || location.href.includes('product-detail')) {
    console.log('=== KB Life 범용 스크래퍼 v2 로드됨 ===');
    console.log('  window.__scrape("상품코드", "이름")  → 스크래핑');
    console.log('  window.__list()                     → 상품 목록');
    console.log('  window.__downloadResults()           → 다운로드');
    console.log('  window.__resetScraper()              → 초기화');
  }
})();
