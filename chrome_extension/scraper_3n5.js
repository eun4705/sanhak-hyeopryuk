/**
 * KB Life 3N5 건강보험 스크래퍼 — premium-new-calculate API
 *
 * 사용법:
 * 1. m.kblife.co.kr 아무 상품 페이지에서 보험료 계산 1회 실행
 * 2. 콘솔에서 이 스크립트 붙여넣기
 * 3. window.__scrape3n5('334000104', '3N5_간편335_표준형')
 *
 * 유틸:
 *   window.__list3n5()          → 상품 목록
 *   window.__status3n5()        → 진행 상태
 *   window.__reset3n5('코드')   → 초기화
 */

(function () {
  'use strict';

  var BATCH_SIZE = 3;
  var SAVE_EVERY = 100;

  var PRODUCTS = [
    { name: '3N5_간편335_표준형', prodCd: '334000104' },
    { name: '3N5_간편335_표준형_납입면제', prodCd: '344000104' },
    { name: '3N5_간편335_미지급형', prodCd: '333000104' },
    { name: '3N5_간편335_미지급형_납입면제', prodCd: '343000104' },
    { name: '3N5_간편355_표준형', prodCd: '332000104' },
    { name: '3N5_간편355_표준형_납입면제', prodCd: '342000104' },
    { name: '3N5_간편355_미지급형', prodCd: '331000104' },
    { name: '3N5_간편355_미지급형_납입면제', prodCd: '341000104' },
    { name: '3N5_갱신_간편315_미지급형', prodCd: '335200104' },
    { name: '3N5_갱신_간편335_미지급형', prodCd: '333200104' },
    { name: '3N5_갱신_간편355_미지급형', prodCd: '331200104' },
    { name: '3N5_갱신_일반심사_미지급형', prodCd: '337200104' },
    { name: '3N5_일반심사_표준형', prodCd: '336000104' },
    { name: '3N5_일반심사_표준형_납입면제', prodCd: '346000104' },
    { name: '3N5_일반심사_미지급형', prodCd: '335000104' },
    { name: '3N5_일반심사_미지급형_납입면제', prodCd: '345000104' },
  ];

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function downloadJSON(data, filename) {
    var blob = new Blob([data], { type: 'text/plain' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function sKey(prodCd) { return 'kb_3n5_' + prodCd; }

  function ajaxPost(path, params) {
    return new Promise(function (resolve, reject) {
      ajax.post('INSURANCEPLAN', path, null, params).done(resolve).fail(reject);
    });
  }

  function ajaxGet(path, params) {
    return new Promise(function (resolve, reject) {
      if (params) {
        ajax.get('INSURANCEPLAN', path, null, params).done(resolve).fail(reject);
      } else {
        ajax.get('INSURANCEPLAN', path).done(resolve).fail(reject);
      }
    });
  }

  // === 특약 제한 조건 (요약서 기반 하드코딩) ===
  function isRiderAllowed(name, age, gender, mainIns, mainInsType, mainPay) {
    // 자궁 관련: 여자만, 20~37세
    if (name.indexOf('자궁') !== -1) {
      return gender === '2' && age >= 20 && age <= 37;
    }
    // 전립선바늘생검(갱신형): 남자만, 18세+
    if (name.indexOf('전립선') !== -1) {
      return gender === '1' && age >= 18;
    }
    // 갑상선바늘생검(갱신형): 25세+
    if (name.indexOf('갑상선바늘생검') !== -1) {
      return age >= 25;
    }
    // 간동맥화학색전술: 남자 25세~
    if (name.indexOf('간동맥화학색전술') !== -1) {
      return gender === '1' && age >= 25;
    }
    // 간동맥방사선색전술: 여자 30세~
    if (name.indexOf('간동맥방사선색전술') !== -1) {
      return gender === '2' && age >= 30;
    }
    // 30년납 특약: 58세까지 (요약서: 만 15세~58세)
    if (mainInsType === '2' && parseInt(mainPay) === 30) {
      var maxRiderAge = parseInt(mainIns) - parseInt(mainPay) - 2;
      if (age > maxRiderAge) return false;
    }
    return true;
  }

  // 특약의 보험기간/납입기간 결정
  function getRiderTerms(rider, mainIns, mainInsType, mainPay, mainPayType) {
    var insTerms = rider.availableInsuranceTerms || [];
    var payTerms = rider.availablePaymentTerms || [];

    // 주계약 보험기간을 지원하는지
    var hasMainIns = insTerms.some(function (t) {
      return t.bkBhgg === mainIns && t.bkYsgb === mainInsType;
    });

    if (hasMainIns) {
      // 주계약 납입기간도 지원하는지
      var matchPay = payTerms.filter(function (t) { return t.insrnPdCo === mainIns; });
      var hasMainPay = matchPay.some(function (t) { return t.nkNigg === mainPay; });
      if (hasMainPay) {
        return { ins: mainIns, insType: mainInsType, pay: mainPay, payType: mainPayType };
      }
      // 첫 번째 가능한 납입기간
      if (matchPay.length > 0) {
        return { ins: mainIns, insType: mainInsType, pay: matchPay[0].nkNigg, payType: matchPay[0].nkYsgb };
      }
      // 전기납
      return { ins: mainIns, insType: mainInsType, pay: mainIns, payType: mainInsType };
    }

    // 주계약 보험기간 미지원 → 특약 자체 보험기간 사용 (갱신형, 80세 등)
    if (insTerms.length > 0) {
      var t = insTerms[0];
      var rPay = payTerms.filter(function (pt) { return pt.insrnPdCo === t.bkBhgg; });
      if (rPay.length > 0) {
        return { ins: t.bkBhgg, insType: t.bkYsgb, pay: rPay[0].nkNigg, payType: rPay[0].nkYsgb };
      }
      return { ins: t.bkBhgg, insType: t.bkYsgb, pay: t.bkBhgg, payType: t.bkYsgb };
    }

    return null;
  }

  // 특약 목록 빌드
  function buildRidersForCall(allRiders, age, gender, mainIns, mainInsType, mainPay, mainPayType) {
    var ridersForCall = [];
    for (var ri = 0; ri < allRiders.length; ri++) {
      var r = allRiders[ri];
      if (!isRiderAllowed(r.gsBhir, age, gender, mainIns, mainInsType, mainPay)) continue;
      var terms = getRiderTerms(r, mainIns, mainInsType, mainPay, mainPayType);
      if (!terms) continue;
      ridersForCall.push({
        code: r.gsSpSpcd1,
        name: r.gsBhir,
        minAmount: parseInt(r.gsCsgiga),
        terms: terms,
      });
    }
    return ridersForCall;
  }

  // premium-new-calculate 1건 호출
  async function calcOne(prodCd, mainProduct, ridersForCall, birthday, genderCode,
    mainIns, mainInsType, mainPay, mainPayType, amountMult) {

    var mainAmount = parseInt(mainProduct.gsCsgiga) * amountMult;

    var riderParams = ridersForCall.map(function (r) {
      return {
        riderCode: r.code,
        riderName: r.name,
        entryAmount: r.minAmount * amountMult,
        insuranceTerm: r.terms.ins,
        insuranceTermType: r.terms.insType,
        paymentTerm: r.terms.pay,
        paymentTermType: r.terms.payType,
        entryAmountcls: false,
      };
    });

    var params = {
      annuityBaseAge: 0, annuityGuaranteeTerm: null, annuityPaymentCycle: null,
      annuityPaymentMethod: null, annuityPaymentTerm: null,
      annuityStartAge: mainIns,
      annuityStartBeforeInsuranceTerm: 0, annuityYn: null,
      birthday: birthday, calculationAfterAmount: 0, categoryCode: null,
      channel: '1001', commonLogic: null, creditingRate: null,
      creditingRateYearMonth: null, customers: [], dngrcd: null, drvCd: null,
      drvnm: null, entityVersion: 0, fcbokPownYn: null, fundYn: null, funds: [],
      genderCode: genderCode, grade: '3', gradualIncreaseForm: null, id: null,
      insuranceAge: 0, insurancePlanNo: null,
      insuranceTerm: mainIns, insuranceTermType: mainInsType,
      investmentIncomeRate: null, jobCd: null, jobNm: null, kkoPownYn: null,
      mainAmount: mainAmount, mainPremium: 0, paymentMethod: '3',
      paymentTerm: mainPay, paymentTermType: mainPayType,
      premium: 0, productCode: prodCd, productCrncCd: '410',
      productKind: '05', productMainId: '501616711',
      productName: mainProduct.gsBhir,
      recommendationPlanName: '', registDatetime: null,
      riders: riderParams,
      srndRefndAmnt2: '', srndRefndAmnt10: '',
    };

    try {
      var calcResult = await ajaxPost('/premium-new-calculate', params);

      // WAF가 status 200으로 HTML 차단 페이지를 반환하는 경우
      if (typeof calcResult === 'string' && calcResult.indexOf('firewall') !== -1) {
        return { error: 'waf' };
      }
      if (!calcResult || typeof calcResult.result === 'undefined') {
        var calcStr = String(calcResult || '').toLowerCase();
        if (calcStr.indexOf('contrary') !== -1 || calcStr.indexOf('firewall') !== -1 || calcStr.indexOf('blocked') !== -1) {
          return { error: 'waf' };
        }
        return { error: 'no_result' };
      }
      var resultId = calcResult.result;
      if (!resultId) return { error: 'no_result' };

      // PC 사이트: vest 암호화 디코딩
      if (typeof cmmUtil !== 'undefined' && cmmUtil.vestDec) {
        try { resultId = cmmUtil.vestDec(resultId); } catch (e) {}
      }

      var detail = await ajaxGet('/insuranceplans/' + resultId);

      return {
        mainPremium: detail.mainPremium,
        mainAmount: detail.mainAmount || mainAmount,
        totalPremium: detail.premium,
        insuranceAge: detail.insuranceAge,
        riders: (detail.riders || []).map(function (r) {
          return {
            code: r.riderCode, name: r.riderName,
            premium: r.riderPremium, amount: r.entryAmount,
            insTerm: r.insuranceTerm, payTerm: r.paymentTerm,
          };
        }),
      };
    } catch (e) {
      var txt = (e.responseText || '').substring(0, 200).toLowerCase();
      if (txt.indexOf('contrary') !== -1 || txt.indexOf('firewall') !== -1 || txt.indexOf('blocked') !== -1) {
        return { error: 'waf' };
      }
      if (e.status === 500) return { error: 'server_500' };
      return { error: String(e).substring(0, 100) };
    }
  }

  // === 메인 스크래핑 함수 ===
  async function scrape3n5(prodCd, productName) {
    if (typeof ajax === 'undefined') {
      console.error('ajax 없음! 먼저 수동으로 보험료 계산 1번 해주세요.');
      return;
    }

    if (!productName) productName = prodCd;
    console.log('=== ' + productName + ' (' + prodCd + ') 스크래핑 시작 ===');

    // 1. 상품 옵션 조회
    var optionData;
    try {
      optionData = await ajaxGet('/insuranceplan-option/' + prodCd, {
        genderCode: '1', isVariable: 'false', isAnnuity: 'false',
        riskGrdCd: '3', insuranceAge: '30', channel: '1001',
      });
    } catch (e) {
      console.error('옵션 조회 실패:', e);
      return { success: 0, errors: 0, waf: false, optionFail: true };
    }

    var mainProduct = optionData.products[0];
    var allRiders = optionData.products.slice(1);
    var insTerms = mainProduct.availableInsuranceTerms || [];
    var payTerms = mainProduct.availablePaymentTerms || [];

    // 보험기간/납입기간 조합
    var combos = [];
    for (var i = 0; i < insTerms.length; i++) {
      var it = insTerms[i];
      var matching = payTerms.filter(function (pt) { return pt.insrnPdCo === it.bkBhgg; });
      for (var j = 0; j < matching.length; j++) {
        combos.push({ ins: it.bkBhgg, insType: it.bkYsgb, pay: matching[j].nkNigg, payType: matching[j].nkYsgb });
      }
    }

    console.log('주계약 조합: ' + combos.length + '개, 특약: ' + allRiders.length + '개');

    // 2. 진행 상태 로드
    var sk = sKey(prodCd);
    var done = JSON.parse(localStorage.getItem(sk + '_done') || '{}');
    var results = JSON.parse(localStorage.getItem(sk + '_results') || '[]');
    var fileCount = parseInt(localStorage.getItem(sk + '_files') || '0');

    console.log('이전: ' + Object.keys(done).length + '건 완료, ' + results.length + '건 미저장');

    // 3. 작업 목록 생성
    var items = [];
    var genders = [['1', '남'], ['2', '여']];
    var amounts = [1, 2];

    for (var ci = 0; ci < combos.length; ci++) {
      var combo = combos[ci];
      // 나이 상한: 보험기간(세) - 납입기간(년), 년만기는 80세 고정
      var maxAge = combo.insType === '2'
        ? parseInt(combo.ins) - parseInt(combo.pay)
        : 80;
      for (var age = 15; age <= Math.min(maxAge, 80); age++) {
        for (var gi = 0; gi < genders.length; gi++) {
          for (var ai = 0; ai < amounts.length; ai++) {
            var key = age + '_' + genders[gi][1] + '_' + combo.ins + '_' + combo.pay + '_x' + amounts[ai];
            if (done[key]) continue;
            items.push({
              key: key, age: age,
              birthday: (2026 - age) + '0101',
              gc: genders[gi][0], gn: genders[gi][1],
              combo: combo, mult: amounts[ai],
            });
          }
        }
      }
    }

    var totalAll = items.length + Object.keys(done).length;
    console.log('전체: ' + totalAll + '건, 남은: ' + items.length + '건');
    console.log('배치: ' + BATCH_SIZE + '건씩 병렬');

    if (items.length === 0) {
      console.log('모든 작업 완료!');
      return;
    }

    var success = 0, errors = 0, wafHit = false;
    var startTime = Date.now();

    for (var b = 0; b < items.length; b += BATCH_SIZE) {
      // 배치 간 2초 대기 (WAF 방지)
      if (b > 0) await sleep(2000);
      var batch = items.slice(b, b + BATCH_SIZE);
      var t0 = Date.now();

      var batchPromises = batch.map(function (item) {
        // 이 나이/성별에 맞는 특약 필터링 + 보험기간/납입기간 매칭
        var ridersForCall = buildRidersForCall(allRiders, item.age, item.gc,
          item.combo.ins, item.combo.insType, item.combo.pay, item.combo.payType);

        return calcOne(prodCd, mainProduct, ridersForCall, item.birthday, item.gc,
          item.combo.ins, item.combo.insType, item.combo.pay, item.combo.payType, item.mult)
          .then(function (result) {
            // 500 에러 시 특약 없이 주계약만 재시도
            if (result.error === 'server_500') {
              return calcOne(prodCd, mainProduct, [], item.birthday, item.gc,
                item.combo.ins, item.combo.insType, item.combo.pay, item.combo.payType, item.mult)
                .then(function (retryResult) {
                  if (!retryResult.error) retryResult._ridersSkipped = true;
                  return retryResult;
                });
            }
            return result;
          });
      });

      var batchResults = await Promise.all(batchPromises);
      var dt = ((Date.now() - t0) / 1000).toFixed(1);

      for (var j = 0; j < batch.length; j++) {
        var item2 = batch[j];
        var result = batchResults[j];

        if (result.error === 'waf') {
          wafHit = true;
          console.error('WAF 차단! key=' + item2.key);
          break;
        }

        done[item2.key] = true;

        if (result.error) {
          errors++;
          if (errors <= 10) console.log('에러: ' + item2.key + ' - ' + result.error);
          continue;
        }

        var entry = {
          _key: item2.key,
          product: productName, prodCd: prodCd,
          age: item2.age, gender: item2.gn,
          insuranceTerm: item2.combo.ins, insuranceTermType: item2.combo.insType,
          paymentTerm: item2.combo.pay, paymentTermType: item2.combo.payType,
          amountMultiplier: item2.mult,
          mainAmount: result.mainAmount, mainPremium: result.mainPremium,
          totalPremium: result.totalPremium, insuranceAge: result.insuranceAge,
          riders: result.riders,
        };
        if (result._ridersSkipped) {
          entry._ridersSkipped = true;
          console.log('⚠ ' + item2.key + ' → 특약 제외하고 주계약만 (500 fallback)');
        }
        results.push(entry);
        success++;
      }

      // localStorage 저장
      localStorage.setItem(sk + '_done', JSON.stringify(done));
      localStorage.setItem(sk + '_results', JSON.stringify(results));

      // 100건마다 파일 저장 + localStorage 비우기
      if (results.length >= SAVE_EVERY) {
        fileCount++;
        var lines = results.map(function (r) { return JSON.stringify(r); }).join('\n');
        downloadJSON(lines, productName + '_part' + fileCount + '.jsonl');
        console.log('>>> ' + results.length + '건 저장 (part' + fileCount + ')');
        localStorage.setItem(sk + '_files', String(fileCount));
        results = [];
        localStorage.setItem(sk + '_results', '[]');
      }

      if (wafHit) {
        // WAF 시 남은 결과 저장
        if (results.length > 0) {
          fileCount++;
          var wafLines = results.map(function (r) { return JSON.stringify(r); }).join('\n');
          downloadJSON(wafLines, productName + '_waf_part' + fileCount + '.jsonl');
          localStorage.setItem(sk + '_files', String(fileCount));
          results = [];
          localStorage.setItem(sk + '_results', '[]');
        }
        localStorage.setItem(sk + '_done', JSON.stringify(done));
        console.error('WAF 차단. 성공: ' + success + '건. 나중에 다시 실행하면 이어서 진행됩니다.');
        return { success: success, errors: errors, waf: true };
      }

      var elapsed = (Date.now() - startTime) / 1000;
      var batchNum = Math.floor(b / BATCH_SIZE) + 1;
      var totalBatches = Math.ceil(items.length / BATCH_SIZE);
      var remaining = Math.round((totalBatches - batchNum) * (elapsed / batchNum));
      console.log('[' + batchNum + '/' + totalBatches + '] ' + dt + 's | 성공=' + success + ' 에러=' + errors + ' | 남은: ~' + Math.round(remaining / 60) + '분');
    }

    // 마지막 남은 결과 저장
    if (results.length > 0) {
      fileCount++;
      var finalLines = results.map(function (r) { return JSON.stringify(r); }).join('\n');
      downloadJSON(finalLines, productName + '_part' + fileCount + '.jsonl');
      localStorage.setItem(sk + '_files', String(fileCount));
      localStorage.setItem(sk + '_results', '[]');
    }

    console.log('\n=== ' + productName + ' 완료! 성공=' + success + ' 에러=' + errors + ' 파일=' + fileCount + '개 ===');
    return { success: success, errors: errors, waf: false };
  }

  // === 16개 전체 연속 실행 ===
  async function scrapeAll() {
    if (typeof ajax === 'undefined') {
      console.error('ajax 없음! 먼저 수동으로 보험료 계산 1번 해주세요.');
      return;
    }

    console.log('=== 3N5 전체 16개 상품 연속 스크래핑 시작 ===\n');
    var totalStart = Date.now();

    for (var i = 0; i < PRODUCTS.length; i++) {
      var p = PRODUCTS[i];
      console.log('\n[' + (i + 1) + '/16] ' + p.name + ' (' + p.prodCd + ')');

      // 이미 완료된 상품 스킵 체크
      var sk = sKey(p.prodCd);
      var doneCount = Object.keys(JSON.parse(localStorage.getItem(sk + '_done') || '{}')).length;
      if (doneCount > 0) {
        console.log('  이전 진행: ' + doneCount + '건 완료 → 이어서 진행');
      }

      var result = await scrape3n5(p.prodCd, p.name);

      if (result && result.waf) {
        console.error('\nWAF 차단으로 중단. 나중에 __scrapeAll() 다시 실행하면 이어서 진행됩니다.');
        return;
      }

      // 옵션 조회 실패 시 10초 대기 후 재시도 1회
      if (result && result.optionFail) {
        console.log('옵션 조회 실패 — 10초 대기 후 재시도...');
        await sleep(10000);
        result = await scrape3n5(p.prodCd, p.name);
        if (result && result.optionFail) {
          console.error(p.name + ' 옵션 조회 2회 실패 — 스킵');
        }
        if (result && result.waf) {
          console.error('\nWAF 차단으로 중단.');
          return;
        }
      }

      // 상품 간 3초 대기 (WAF 방지)
      if (i < PRODUCTS.length - 1) {
        console.log('다음 상품까지 3초 대기...');
        await sleep(3000);
      }
    }

    var totalElapsed = Math.round((Date.now() - totalStart) / 1000 / 60);
    console.log('\n=== 전체 16개 상품 완료! 총 소요시간: ~' + totalElapsed + '분 ===');
  }

  // === 유틸 함수 ===
  window.__scrape3n5 = scrape3n5;
  window.__scrapeAll = scrapeAll;

  window.__list3n5 = function () {
    PRODUCTS.forEach(function (p, i) { console.log((i + 1) + '. ' + p.prodCd + ' ' + p.name); });
  };

  window.__status3n5 = function () {
    var totalDone = 0, totalFiles = 0;
    PRODUCTS.forEach(function (p) {
      var d = Object.keys(JSON.parse(localStorage.getItem(sKey(p.prodCd) + '_done') || '{}')).length;
      var s = JSON.parse(localStorage.getItem(sKey(p.prodCd) + '_results') || '[]').length;
      var f = parseInt(localStorage.getItem(sKey(p.prodCd) + '_files') || '0');
      totalDone += d;
      totalFiles += f;
      var status = d === 0 ? '미시작' : (s === 0 && f > 0 ? '완료' : '진행중');
      console.log(p.name + ': ' + d + '건 (' + status + ', ' + f + '파일)');
    });
    console.log('---\n전체: ' + totalDone + '건 완료, ' + totalFiles + '파일');
  };

  window.__reset3n5 = function (prodCd) {
    if (prodCd === 'all') {
      PRODUCTS.forEach(function (p) {
        localStorage.removeItem(sKey(p.prodCd) + '_done');
        localStorage.removeItem(sKey(p.prodCd) + '_results');
        localStorage.removeItem(sKey(p.prodCd) + '_files');
      });
      console.log('전체 초기화 완료');
    } else {
      localStorage.removeItem(sKey(prodCd) + '_done');
      localStorage.removeItem(sKey(prodCd) + '_results');
      localStorage.removeItem(sKey(prodCd) + '_files');
      console.log(prodCd + ' 초기화');
    }
  };

  console.log('=== 3N5 스크래퍼 로드됨 ===');
  console.log('  window.__scrapeAll()                              → 16개 전체 연속');
  console.log('  window.__scrape3n5("334000104", "3N5_간편335_표준형") → 개별 실행');
  console.log('  window.__list3n5()                                → 상품 목록');
  console.log('  window.__status3n5()                              → 진행 상태');
  console.log('  window.__reset3n5("코드" 또는 "all")               → 초기화');
})();
