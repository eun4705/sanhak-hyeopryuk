(function(){
  var PROD_CD = "118500105";
  var PAY_TERMS = ["5","7","10","15"];
  var PREMIUMS = [200000, 500000];
  var ANNUITY_START = "65";
  var DELAY = 15000;

  function sKey(){ return "kb_annuity_"+PROD_CD; }

  function downloadJSON(data, filename){
    var blob = new Blob([data],{type:"text/plain"});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function sleep(ms){ return new Promise(function(resolve){ setTimeout(resolve, ms); }); }

  async function calcOne(birthday, genderCode, payTerm, premium){
    // 1) m-premium-calculate -> 적립액
    var r1 = await ajax.post("INSURANCEPLAN","/m-premium-calculate",null,{
      productCode: PROD_CD,
      birthday: birthday,
      genderCode: genderCode,
      isVariable: false,
      isAnnuity: true,
      pcOnline: true,
      premium: String(premium),
      insuranceTerm: ANNUITY_START,
      insuranceTermType: 2,
      paymentTerm: payTerm,
      paymentTermType: 1,
      entryAmount: 0,
      isReCal: "true",
      paymentMethod: "3",
      anutyPayTyCd: "2",
      grtInsrnPdCo: "20",
      anutyPayFrqcyCd: "4",
      anutyPayPdVal: "99"
    });

    // PC: vest 디코딩 (results 항목이 암호화된 문자열일 수 있음)
    if (typeof r1.results[0] === 'string' && typeof cmmUtil !== 'undefined' && cmmUtil.vestDec) {
      try { r1.results[0] = JSON.parse(cmmUtil.vestDec(r1.results[0])); } catch(e) {}
    }
    var cal = r1.results[0].cal;
    var arr = cal.periodicDeathBenefitsDTO;
    var fin = arr[arr.length - 1];
    var resv = fin.ownerResvAmnt1;
    var insrnAge = r1.results[0].recomm.insuranceAge;

    // 2) getAnnuityExampleTotal -> 연금액 6개
    var r2 = await ajax.post("INSURANCEPLAN","/insuranceplans/getAnnuityExampleTotal",null,{
      prodCd: PROD_CD,
      insrnAge: insrnAge,
      gndrCd: genderCode,
      anutyBgnAge: parseInt(ANNUITY_START),
      anutyExmpTp: "1",
      anutyExmpTyCd: "1",
      prmum: premium,
      ownerResvAmnt1: resv,
      anutyCreatAmntTyCd: "1"
    });

    var annuities = [];
    var dtos = r2[0].annuityBenefitDTO;
    var codeNames = {
      "1020_1": "종신20년보증",
      "2100_1": "종신100세보증",
      "9000_1": "종신기대여명보증",
      "1010_2": "확정10년",
      "1020_2": "확정20년",
      "3000_1": "상속"
    };
    var codeCount = {};
    for(var i=0; i<dtos.length; i++){
      var d = dtos[i];
      var code = d.anutyPayGrtPdCd;
      codeCount[code] = (codeCount[code]||0) + 1;
      var key = code + "_" + codeCount[code];
      var a = d.annuityBenefitAmountInfo[0];
      annuities.push({
        code: code,
        name: codeNames[key] || code,
        publicRate: a.anutyAmnt1,
        minRate: a.anutyAmnt2
      });
    }

    return {
      accumulation: resv,
      totalPaid: fin.prepPrmum,
      periods: arr.length,
      annuities: annuities
    };
  }

  window.__scrapeAnnuity = async function(){
    if(typeof ajax === "undefined"){
      console.error("ajax 없음! 먼저 수동으로 계산 1번 해주세요.");
      return;
    }

    console.log("=== 하이파이브연금 스크래핑 시작 ===");

    var sk = sKey();
    var saved = JSON.parse(localStorage.getItem(sk+"_done") || "{}");
    var savedResults = JSON.parse(localStorage.getItem(sk+"_results") || "[]");
    console.log("이전: "+Object.keys(saved).length+"건 완료, "+savedResults.length+"건 저장");

    // 작업 목록
    var items = [];
    // 5/7/10년납: 19~65세, 15년납: 19~60세
    for(var pi=0; pi<PAY_TERMS.length; pi++){
      var pt = PAY_TERMS[pi];
      var maxAge = (pt === "15") ? 60 : 65;
      for(var age=19; age<=maxAge; age++){
        for(var gi=0; gi<2; gi++){
          var gc = gi===0 ? "1" : "2";
          var gn = gi===0 ? "남" : "여";
          for(var pri=0; pri<PREMIUMS.length; pri++){
            var pm = PREMIUMS[pri];
            var key = age+"_"+gn+"_"+pt+"년_"+pm;
            if(saved[key]) continue;
            items.push({key:key, age:age, birthday:String(2026-age)+"0101", gc:gc, gn:gn, payTerm:pt, premium:pm});
          }
        }
      }
    }

    console.log("남은: "+items.length+"건, 15초 간격");
    if(items.length === 0){ console.log("완료!"); return; }

    var success = 0;
    var errors = 0;
    var results = savedResults.slice();
    var startTime = Date.now();

    for(var i=0; i<items.length; i++){
      var item = items[i];

      if(i > 0) await sleep(DELAY);

      try{
        var result = await calcOne(item.birthday, item.gc, item.payTerm, item.premium);

        results.push({
          _key: item.key,
          product: "하이파이브연금",
          prodCd: PROD_CD,
          age: item.age,
          gender: item.gn,
          paymentTerm: item.payTerm,
          premium: item.premium,
          annuityStartAge: parseInt(ANNUITY_START),
          accumulation: result.accumulation,
          totalPaid: result.totalPaid,
          annuities: result.annuities
        });
        saved[item.key] = true;
        success++;
      }catch(e){
        var txt = (e.responseText||"").substring(0,100).toLowerCase();
        if(txt.indexOf("contrary")>=0 || txt.indexOf("firewall")>=0 || txt.indexOf("blocked")>=0){
          console.error("WAF 차단! "+item.key);
          localStorage.setItem(sk+"_done", JSON.stringify(saved));
          localStorage.setItem(sk+"_results", JSON.stringify(results));
          var lines = results.map(function(r){return JSON.stringify(r)}).join("\n");
          downloadJSON(lines, "하이파이브연금_"+results.length+"건_중단.jsonl");
          return;
        }
        errors++;
        if(errors <= 5) console.log("에러: "+item.key+" - "+String(e).substring(0,100));
      }

      // 100건마다 자동 저장 + 비우기
      if(results.length >= 100){
        localStorage.setItem(sk+"_done", JSON.stringify(saved));
        var lines = results.map(function(r){return JSON.stringify(r)}).join("\n");
        downloadJSON(lines, "하이파이브연금_"+Date.now()+".jsonl");
        results = [];
        localStorage.removeItem(sk+"_results");
        console.log("[자동저장] 100건 다운로드 + 비움");
      }else{
        localStorage.setItem(sk+"_done", JSON.stringify(saved));
        localStorage.setItem(sk+"_results", JSON.stringify(results));
      }

      var elapsed = (Date.now() - startTime) / 1000;
      var remaining = Math.round((items.length - i - 1) * DELAY / 60000);
      if((i+1) % 10 === 0 || i === 0){
        console.log("["+(i+1)+"/"+items.length+"] 성공="+success+" 에러="+errors+" 남은:~"+remaining+"분");
      }
    }

    console.log("\n=== 완료! 성공="+success+" 에러="+errors+" ===");
    localStorage.setItem(sk+"_done", JSON.stringify(saved));
    if(results.length > 0){
      var lines = results.map(function(r){return JSON.stringify(r)}).join("\n");
      downloadJSON(lines, "하이파이브연금_"+results.length+"건_완료.jsonl");
    }
  };

  window.__annuityStatus = function(){
    var sk = sKey();
    var done = Object.keys(JSON.parse(localStorage.getItem(sk+"_done")||"{}")).length;
    var saved = JSON.parse(localStorage.getItem(sk+"_results")||"[]").length;
    console.log("하이파이브연금: "+done+"건 완료, "+saved+"건 미저장");
  };

  window.__annuityDownload = function(){
    var sk = sKey();
    var results = JSON.parse(localStorage.getItem(sk+"_results")||"[]");
    if(!results.length){ console.log("결과 없음"); return; }
    var lines = results.map(function(r){return JSON.stringify(r)}).join("\n");
    downloadJSON(lines, "하이파이브연금_"+results.length+"건.jsonl");
    console.log(results.length+"건 다운로드");
  };

  window.__annuityReset = function(){
    var sk = sKey();
    localStorage.removeItem(sk+"_done");
    localStorage.removeItem(sk+"_results");
    console.log("하이파이브연금 초기화");
  };

  if(location.href.indexOf("productDetails")>=0 || location.href.indexOf("product-detail")>=0){
    console.log("=== 하이파이브연금 스크래퍼 로드됨 ===");
    console.log("  window.__scrapeAnnuity() -> 시작");
    console.log("  window.__annuityStatus() -> 상태");
    console.log("  window.__annuityDownload() -> 다운로드");
    console.log("  window.__annuityReset() -> 초기화");
  }
})();
