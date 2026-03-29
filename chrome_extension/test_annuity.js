(function(){
  window.__testAnnuity = function(age, startAge, payTerm, amount){
    if(!age) age = 30;
    if(!startAge) startAge = 65;
    if(!payTerm) payTerm = 5;
    if(!amount) amount = 12000000;
    var bday = String(2026-age)+"0101";
    ajax.post("INSURANCEPLAN","/premium-calculate",null,{productCode:"118500105",birthday:bday,genderCode:"1",isVariable:false,isAnnuity:true,pcOnline:true,entryAmount:amount,paymentMethod:"3",paymentTerm:String(payTerm),paymentTermType:"1",annuityStartAge:String(startAge)}).then(function(r){return ajax.get("INSURANCEPLAN","/insuranceplans/"+r.results[0])}).then(function(d){console.log("=== 결과 ===");console.log("나이:"+age+" 개시:"+d.annuityStartAge+" 납입:"+d.paymentTerm+"년");console.log("가입금액:"+d.mainAmount+" 월보험료:"+d.premium);console.log("연금액:"+d.calculationAfterAmount);console.log("보증기간:"+d.annuityGuaranteeTerm+" 지급주기:"+d.annuityPaymentCycle);console.log("전체:",JSON.stringify(d).substring(0,800))});
  };

  window.__testAmounts = function(age, startAge, payTerm){
    if(!age) age = 30;
    if(!startAge) startAge = 65;
    if(!payTerm) payTerm = 5;
    var bday = String(2026-age)+"0101";
    var amounts = [6000000,12000000,24000000,36000000,60000000];
    amounts.forEach(function(amt){
      ajax.post("INSURANCEPLAN","/premium-calculate",null,{productCode:"118500105",birthday:bday,genderCode:"1",isVariable:false,isAnnuity:true,pcOnline:true,entryAmount:amt,paymentMethod:"3",paymentTerm:String(payTerm),paymentTermType:"1",annuityStartAge:String(startAge)}).then(function(r){return ajax.get("INSURANCEPLAN","/insuranceplans/"+r.results[0])}).then(function(d){console.log("가입금액:"+amt+" -> 월보험료:"+d.premium+" 연금액:"+d.calculationAfterAmount+" 개시:"+d.annuityStartAge)});
    });
  };

  console.log("=== 연금 테스트 로드됨 ===");
  console.log("  window.__testAnnuity(나이, 개시나이, 납입기간, 가입금액)");
  console.log("  예: window.__testAnnuity(30, 65, 5, 12000000)");
  console.log("  window.__testAmounts(나이, 개시나이, 납입기간)");
  console.log("  예: window.__testAmounts(30, 65, 5)");
})();
