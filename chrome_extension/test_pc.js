// test_pc.js — PC 사이트 2단계 호출 테스트
(function () {
  window.__testPC = async function () {
    if (typeof ajax === 'undefined') {
      console.error('ajax 없음! 먼저 수동으로 계산 1번 해주세요.');
      return;
    }

    console.log('=== PC 2단계 호출 테스트 ===');

    // 1단계: premium-calculate (전처리)
    console.log('1단계: premium-calculate...');
    try {
      var r1 = await ajax.post('INSURANCEPLAN', '/premium-calculate', null, {
        productCode: '334000104',
        productCode2: '',
        birthday: '19960101',
        genderCode: '1',
        isVariable: false,
        isAnnuity: false,
        pcOnline: false,
        keywords: [],
        prmumCalMthdTpCd: '1',
        prodCrncCd: '410',
        grade: ''
      });
      console.log('1단계 응답:', JSON.stringify(r1));
    } catch (e) {
      console.error('1단계 실패:', e.status, e.responseText?.substring(0, 300));
      return;
    }

    // 2단계: premium-new-calculate (본 계산)
    console.log('2단계: premium-new-calculate...');
    try {
      var r2 = await ajax.post('INSURANCEPLAN', '/premium-new-calculate', null, {
        annuityGuaranteeTerm: null,
        annuityPaymentCycle: null,
        annuityPaymentMethod: null,
        annuityPaymentTerm: null,
        annuityStartAge: '100',
        annuityBaseAge: 0,
        annuityStartBeforeInsuranceTerm: 0,
        annuityYn: null,
        birthday: '19960101',
        calculationAfterAmount: 0,
        categoryCode: null,
        channel: '1001',
        creditingRate: null,
        creditingRateYearMonth: null,
        investmentIncomeRate: null,
        customers: [],
        entityVersion: 0,
        fcbokPownYn: null,
        fundYn: null,
        funds: [],
        genderCode: '1',
        gradualIncreaseForm: null,
        id: null,
        insuranceAge: 0,
        insurancePlanNo: null,
        insuranceTerm: '100',
        insuranceTermType: '2',
        kkoPownYn: null,
        mainAmount: 100000000,
        mainPremium: 0,
        paymentMethod: '3',
        paymentTerm: '10',
        paymentTermType: '1',
        premium: 0,
        jobNm: null,
        jobCd: null,
        drvCd: null,
        drvnm: null,
        dngrcd: null,
        productCode: '334000104',
        productKind: '05',
        productMainId: '501616711',
        productName: 'test',
        commonLogic: null,
        registDatetime: null,
        riders: [],
        srndRefndAmnt2: '',
        srndRefndAmnt10: '',
        productCrncCd: '410',
        recommendationPlanName: '',
        grade: '3'
      });
      console.log('2단계 성공:', JSON.stringify(r2));

      if (r2.result) {
        // vestDec 디코딩
        var resultId = cmmUtil.vestDec(r2.result);
        console.log('디코딩:', r2.result.substring(0, 20) + '... →', resultId);

        // 3단계: 결과 조회
        console.log('3단계: 결과 조회...');
        var r3 = await ajax.get('INSURANCEPLAN', '/insuranceplans/' + resultId);
        console.log('보험료:', r3.mainPremium, '원 (총', r3.premium, '원)');
        console.log('특약:', (r3.riders || []).length, '개');
        console.log('전체:', JSON.stringify(r3).substring(0, 500));
      }
    } catch (e) {
      console.error('2단계 실패:', e.status, e.responseText?.substring(0, 300));
    }

    console.log('=== 테스트 완료 ===');
  };

  console.log('[test_pc] __testPC() 로 테스트 실행');
})();
