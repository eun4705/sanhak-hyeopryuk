"""
Golden Set v3 생성: 모든 질문에 상품명 지정
"""

import json
import os
import re
from collections import defaultdict
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

client = chromadb.PersistentClient(path=os.path.join(BASE_DIR, "data", "chroma_db"))
col = client.get_collection("insurance_articles")
all_data = col.get(include=["metadatas"])
all_ids_set = set(all_data["ids"])

# prodCode+title → ID 매핑
prod_title_to_ids = defaultdict(list)
for did, meta in zip(all_data["ids"], all_data["metadatas"]):
    title = re.sub(r"\s+", "", meta.get("title", ""))
    key = (meta["prodCode"], title)
    prod_title_to_ids[key].append(did)


def get_ids(prod_code, title_kw):
    result = []
    for (pc, title), ids in prod_title_to_ids.items():
        if pc == prod_code and title_kw in title:
            result.extend(ids)
    return result[:5]


golden = []
qid = 1


def add(query, prod, title_kw, qtype="상품특정"):
    global qid
    ids = get_ids(prod, title_kw)
    if ids:
        golden.append({
            "id": qid,
            "query": query,
            "type": qtype,
            "product": prod,
            "relevant_ids": ids,
        })
        qid += 1


# ── 착한암보험 (KL0420) ──
P, N = "KL0420", "KB 착한암보험"
add(f"{N}에서 암에 걸리면 보험금 얼마 받아?", P, "보험금의지급사유")
add(f"{N}에서 고액암이란 뭐야?", P, "고액암")
add(f"{N} 암 진단 후 보험료 납입 면제되나요?", P, "보험금지급에관한세부규정")
add(f"{N} 보험금 지급하지 않는 경우는?", P, "보험금을지급하지않는사유")
add(f"{N}에서 갑상선암도 보장되나요?", P, "갑상선암")
add(f"{N}의 제자리암이 뭐야?", P, "제자리암")
add(f"{N}의 경계성종양도 보장돼?", P, "경계성종양")
add(f"{N}의 대장점막내암은 일반암이야?", P, "대장점막내암")
add(f"{N} 해약환급금은 얼마야?", P, "해약환급금")
add(f"{N} 청약 철회 기간은?", P, "청약의철회")
add(f"{N} 계약 무효 조건은?", P, "계약의무효")
add(f"{N} 보험 언제부터 보장 시작돼?", P, "제1회보험료및회사의보장개시")

# ── 하이파이브연금 (KL0490) ──
P, N = "KL0490", "KB 하이파이브연금"
add(f"{N} 해약환급금은 얼마야?", P, "해약환급금")
add(f"{N} 연금 수령 방식은?", P, "보험금의지급사유")
add(f"{N} 청약 철회 기간은?", P, "청약의철회")
add(f"{N} 보험계약대출 받을 수 있어?", P, "보험계약대출")
add(f"{N} 보험료 납입 연체되면?", P, "보험료의납입이연체")

# ── 골든라이프 치매 (KL0810) ──
P, N = "KL0810", "KB 골든라이프 치매보장형"
add(f"{N}에서 치매 진단 받으면 보험금 나와?", P, "보험금의지급사유")
add(f"{N}에서 경도치매랑 중증치매 차이가 뭐야?", P, "용어의정의")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")
add(f"{N} 해약환급금은?", P, "해약환급금")

# ── 대중교통안심 (KL1041) ──
P, N = "KL1041", "KB 대중교통안심보험"
add(f"{N} 사고로 사망하면 보험금 얼마?", P, "보험금의지급사유")
add(f"{N} 면책 사유는?", P, "보험금을지급하지않는사유")
add(f"{N} 해약환급금은?", P, "해약환급금")
add(f"{N} 보험수익자 지정은?", P, "보험수익자의지정")

# ── 교통안심 (KL1042) ──
P, N = "KL1042", "KB 교통안심보험"
add(f"{N} 보험금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")

# ── 골든라이프 상해 (KL1044) ──
P, N = "KL1044", "KB 골든라이프 상해보장형"
add(f"{N}에서 재해란 뭐야?", P, "용어의정의")
add(f"{N} 보험금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")

# ── 세번의약속 e연금 (KL1060) ──
P, N = "KL1060", "KB 세번의약속 e연금"
add(f"{N} 연금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 해약환급금은?", P, "해약환급금")
add(f"{N} 계약 무효 조건은?", P, "계약의무효")

# ── 달러평생보장 간편 (KL1602) ──
P, N = "KL1602", "KB 달러평생보장 간편심사형"
add(f"{N}은 환율 어떻게 적용해?", P, "통화의정의")
add(f"{N} 보험금 지급사유는?", P, "보험금의지급사유")

# ── 달러평생보장 일반 (KL1603) ──
P, N = "KL1603", "KB 달러평생보장 일반심사형"
add(f"{N}은 환율 어떻게 적용해?", P, "통화의정의")
add(f"{N} 해약환급금은?", P, "해약환급금")

# ── 소득보장 (KL1606) ──
P, N = "KL1606", "KB 소득보장보험"
add(f"{N}에서 월급여금은 뭐야?", P, "월급여금")
add(f"{N} 보험금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")
add(f"{N} 보험료 납입면제 조건은?", P, "보험금지급에관한세부규정")

# ── 정기보험 (KL1607) ──
P, N = "KL1607", "KB 정기보험"
add(f"{N} 사망보험금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 해약환급금은?", P, "해약환급금")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")
add(f"{N} 계약 전 알릴 의무는?", P, "계약전알릴의무")

# ── 종신보험 간편 (KL1608) ──
P, N = "KL1608", "KB 종신보험 간편심사형"
add(f"{N} 사망보험금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 해약환급금은?", P, "해약환급금")
add(f"{N} 감액 조건은?", P, "보험금지급에관한세부규정")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")

# ── 종신보험 일반 (KL1609) ──
P, N = "KL1609", "KB 종신보험 일반심사형"
add(f"{N} 사망보험금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 해약환급금은?", P, "해약환급금")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")
add(f"{N} 계약 내용 변경할 수 있어?", P, "계약내용의변경")
add(f"{N} 보험계약대출 받을 수 있어?", P, "보험계약대출")

# ── 착한정기보험II (KL1611) ──
P, N = "KL1611", "KB 착한정기보험II"
add(f"{N} 사망보험금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 보험금 안 되는 경우는?", P, "보험금을지급하지않는사유")
add(f"{N} 보험 나이는 어떻게 계산해?", P, "보험나이")
add(f"{N} 보험료 자동대출납입이 뭐야?", P, "보험료의자동대출납입")
add(f"{N} 계약 전 알릴 의무 위반하면?", P, "계약전알릴의무위반의효과")
add(f"{N} 보험수익자 변경할 수 있어?", P, "보험수익자의지정")
add(f"{N} 사기로 가입하면 어떻게 돼?", P, "사기에의한계약")
add(f"{N} 분쟁 조정 신청은?", P, "분쟁의조정")
add(f"{N} 보험금 청구 필요 서류는?", P, "보험금등의청구")
add(f"{N} 보험금 지급 절차는?", P, "보험금등의지급절차")
add(f"{N} 보험료 안 내면 해지되나?", P, "보험료의납입이연체")
add(f"{N} 보험계약대출 어떻게 받아?", P, "보험계약대출")
add(f"{N} 해약환급금은?", P, "해약환급금")
add(f"{N} 계약 무효 조건은?", P, "계약의무효")

# ── 약속플러스종신 일반 (KL1616) ──
P, N = "KL1616", "KB 약속플러스 종신보험 일반심사형"
add(f"{N} 해약환급금은?", P, "해약환급금")
add(f"{N} 보험금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")

# ── 약속플러스종신 간편 (KL1617) ──
P, N = "KL1617", "KB 약속플러스 종신보험 간편심사형"
add(f"{N} 해약환급금은?", P, "해약환급금")
add(f"{N} 보험금 지급사유는?", P, "보험금의지급사유")

# ── e건강보험 일반 (KLT028) ──
P, N = "KLT028", "KB e건강보험 일반심사형"
add(f"{N} 입원비는 얼마나 나와?", P, "보험금의지급사유")
add(f"{N} 갱신은 어떻게 해?", P, "계약내용의변경")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")
add(f"{N} 해약환급금은?", P, "해약환급금")

# ── e건강보험 간편 (KLT029) ──
P, N = "KLT029", "KB e건강보험 간편심사형"
add(f"{N} 보험금 지급사유는?", P, "보험금의지급사유")
add(f"{N} 면책사유는?", P, "보험금을지급하지않는사유")

# ── 구어체 (상품 지정) ──
add("KB 착한암보험 들었다가 취소하고 싶어", "KL0420", "청약의철회", "구어체")
add("KB 종신보험 일반심사형 해지하면 돈 돌려받을 수 있어?", "KL1609", "해약환급금", "구어체")
add("KB 착한정기보험II 보험료를 어떻게 내나요?", "KL1611", "제2회이후보험료의납입", "구어체")
add("KB 종신보험 간편심사형 사고로 죽으면 보험금 나와?", "KL1608", "보험금의지급사유", "구어체")
add("KB 하이파이브연금 보험 언제부터 보장 시작이야?", "KL0490", "제1회보험료및회사의보장개시", "구어체")
add("KB 정기보험 보험금 얼마나 빨리 받을 수 있어?", "KL1607", "보험금등의지급절차", "구어체")
add("KB 대중교통안심보험 내가 죽으면 누가 보험금 받아?", "KL1041", "보험수익자의지정", "구어체")
add("KB 착한정기보험II 가입하고 바로 해지하면?", "KL1611", "해약환급금", "구어체")
add("KB e건강보험 일반심사형 보험금 신청하려면 어떻게 해?", "KLT028", "보험금등의청구", "구어체")
add("KB 소득보장보험 보험 계약서 안 받았는데?", "KL1606", "약관교부및설명의무", "구어체")

# 검증
missing = sum(1 for q in golden for rid in q["relevant_ids"] if rid not in all_ids_set)

from collections import Counter
type_dist = Counter(q["type"] for q in golden)
prod_dist = Counter(q["product"] for q in golden)

print(f"총 {len(golden)}개 QA 쌍, 누락 ID: {missing}개")
for t, c in sorted(type_dist.items()):
    print(f"  {t}: {c}개")
print(f"상품 커버: {len(prod_dist)}/{18}개")
for p, c in sorted(prod_dist.items()):
    print(f"  {p}: {c}개")

with open(os.path.join(BASE_DIR, "eval", "golden_set_v3.json"), "w", encoding="utf-8") as f:
    json.dump(golden, f, ensure_ascii=False, indent=2)
print(f"\n저장: eval/golden_set_v3.json")
