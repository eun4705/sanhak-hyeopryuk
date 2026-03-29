/**
 * 하이파이브연금 나이별 옵션 스캔 — 콘솔에서 window.__scanAnnuity() 실행
 * 결과를 JSON 파일로 다운로드
 */
(function(){
  window.__scanAnnuity = async function(){
    var results = [];
    for(var age=15; age<=70; age++){
      try{
        var d = await ajax.get("INSURANCEPLAN","/insuranceplan-option/118500105",null,{genderCode:"1",isVariable:"false",isAnnuity:"true",riskGrdCd:"3",insuranceAge:String(age),channel:"1001"});
        var p = d.products[0];
        var ins = p.availableInsuranceTerms || [];
        var pay = p.availablePaymentTerms || [];
        var insVals = ins.map(function(t){return t.bkBhgg});
        var paySet = {};
        pay.forEach(function(x){paySet[x.nkNigg]=1});
        var payVals = Object.keys(paySet);
        var entry = {age:age, insFrom:insVals[0], insTo:insVals[insVals.length-1], insCount:ins.length, payTerms:payVals, minAmt:p.gsCsgiga, maxAmt:p.gsCdgiga};
        results.push(entry);
        console.log(age+"세: 개시="+insVals[0]+"~"+insVals[insVals.length-1]+"("+ins.length+"개) 납입="+payVals.join(","));
      }catch(e){
        results.push({age:age, error:String(e).substring(0,100)});
        console.log(age+"세: 에러");
      }
    }
    var blob = new Blob([JSON.stringify(results,null,2)],{type:"application/json"});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "하이파이브연금_나이별옵션.json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    console.log("완료! "+results.length+"개 나이 스캔");
  };
  console.log("=== 하이파이브연금 스캔 로드됨 ===");
  console.log("  window.__scanAnnuity() → 나이별 옵션 스캔+다운로드");
})();
