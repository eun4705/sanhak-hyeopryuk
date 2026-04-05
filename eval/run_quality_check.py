"""
품질 검증 — 할루시네이션, 의도 분류, 데이터 정확성 종합 체크
"""

import os, sys, json, time, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from agent_runner import InsuranceAgent, classify_intent
from agent_tools import AgentDataStore, tool_get_product_catalog, tool_lookup_premium, PRODCODE_TO_PREMIUM

# ── 1. 의도 분류 검증 ──

INTENT_TESTS = [
    # (질문, 기대 의도)
    # 상품 탐색/추천 → catalog
    ("어떤 보험 있어?", "catalog"),
    ("보험 추천해줘", "catalog"),
    ("나 23세 남자인데 보통 보험 어떤거 들어야되?", "catalog"),
    ("보험 처음인데 뭐부터 해야돼?", "catalog"),
    ("간편심사로 가입할 수 있는 거 있어요?", "catalog"),
    ("달러로 가입하는 보험 있나요?", "catalog"),
    ("사망 보장 되는 보험 뭐 있어?", "catalog"),
    ("보험 뭐 가입해야돼?", "catalog"),
    ("젊은 사람 보험 뭐가 좋아?", "catalog"),
    ("60대 보험 추천", "catalog"),
    ("치매 보장되는 보험 찾고 있어요", "catalog"),

    # 보험료 → premium
    ("30세 남성 착한암보험 보험료 알려줘", "premium"),
    ("40세 여성 종신보험 보험료는?", "premium"),
    ("보험료 얼마예요?", "premium"),

    # 비교 → compare
    ("종신보험이랑 정기보험 차이가 뭐야?", "compare"),
    ("일반심사형이랑 간편심사형 비교해줘", "compare"),

    # 약관/보장/면책/해지 → search
    ("암보험 면책기간이 얼마예요?", "search"),
    ("보험금 지급 안 되는 경우는?", "search"),
    ("보험료 안 내면 어떻게 돼?", "search"),
    ("청약 철회는 언제까지?", "search"),
    ("해약하면 돈 돌려받을 수 있어?", "search"),
    ("착한암보험 특약 뭐 있어?", "search"),
    ("사망보험금 지급 조건이 뭐야?", "search"),
    ("암 진단받으면 보험금 나와?", "search"),
]


def test_intent_classification():
    print("=" * 60)
    print("1. 의도 분류 검증")
    print("=" * 60)

    passed = 0
    failed = 0
    for q, expected in INTENT_TESTS:
        result = classify_intent(q)
        if result == expected:
            passed += 1
        else:
            failed += 1
            print(f"  ❌ \"{q}\" → {result} (기대: {expected})")

    print(f"  결과: {passed}/{passed+failed} 통과")
    if failed == 0:
        print("  ✅ 전체 통과")
    return failed == 0


# ── 2. 데이터 정확성 검증 ──

def test_data_accuracy():
    print("\n" + "=" * 60)
    print("2. 데이터 정확성 검증")
    print("=" * 60)

    store = AgentDataStore()
    errors = 0

    # 2-1. 18개 상품 전부 prodCode로 보험료 조회 가능한지
    print("\n  [보험료 조회]")
    for code in sorted(PRODCODE_TO_PREMIUM.keys()):
        r = tool_lookup_premium(store, prod_code=code, age=30, gender="남")
        if r["total_found"] == 0:
            print(f"    ❌ {code}: 보험료 0건")
            errors += 1

    if errors == 0:
        print(f"    ✅ 18/18 상품 보험료 조회 성공")

    # 2-2. 카탈로그 데이터 일관성
    print("\n  [카탈로그 일관성]")
    cat = tool_get_product_catalog(store)
    for p in cat["products"]:
        code = p["prodCode"]
        if not p.get("name"):
            print(f"    ❌ {code}: name 없음")
            errors += 1
        if not p.get("product_type"):
            print(f"    ❌ {code}: product_type 없음")
            errors += 1
        if not p.get("main_coverage"):
            print(f"    ❌ {code}: main_coverage 없음")
            errors += 1

    if errors == 0:
        print(f"    ✅ 18개 상품 필수 필드 정상")

    # 2-3. 카탈로그 크기
    cat_str = json.dumps(cat, ensure_ascii=False)
    print(f"\n  [카탈로그 크기] {len(cat_str):,}자 (~{len(cat_str)//4}토큰)")

    return errors == 0


# ── 3. LLM 할루시네이션 검증 ──

HALLUCINATION_TESTS = [
    {
        "q": "암 보장되는 보험 뭐 있어?",
        "must_include": ["착한암보험", "e-건강보험"],
        "must_not_include": [],
        "check": "암 특약 있는 e-건강보험도 포함하는지",
    },
    {
        "q": "착한암보험 특약이 뭐 있어?",
        "must_include": [],
        "must_not_include": ["특약을 추가", "특약 옵션", "치료비 특약을 붙이"],
        "check": "착한암보험에 없는 특약을 지어내지 않는지",
    },
    {
        "q": "KB라이프 보험 종류 알려줘",
        "must_include": [],
        "must_not_include": ["저축보험", "변액보험", "실손보험"],
        "check": "존재하지 않는 상품 유형을 지어내지 않는지",
    },
    {
        "q": "30세 남성 착한암보험 보험료 알려줘",
        "must_include": [],
        "must_not_include": [],
        "check": "보험료 숫자가 데이터와 일치하는지 (수동 확인)",
    },
]


def test_hallucination(agent):
    print("\n" + "=" * 60)
    print("3. LLM 할루시네이션 검증")
    print("=" * 60)

    passed = 0
    failed = 0

    for t in HALLUCINATION_TESTS:
        agent.reset()
        print(f"\n  Q: {t['q']}")
        print(f"  체크: {t['check']}")

        resp = agent.chat(t["q"])
        content = resp.content

        if resp.error:
            print(f"  ❌ 오류: {resp.error}")
            failed += 1
            continue

        issues = []

        for keyword in t["must_include"]:
            if keyword not in content:
                issues.append(f"'{keyword}' 누락")

        for keyword in t["must_not_include"]:
            if keyword in content:
                issues.append(f"'{keyword}' 할루시네이션 감지!")

        if issues:
            failed += 1
            print(f"  ❌ {', '.join(issues)}")
            print(f"  응답: {content[:200]}...")
        else:
            passed += 1
            print(f"  ✅ 통과")
            print(f"  응답: {content[:150]}...")

    print(f"\n  결과: {passed}/{passed+failed} 통과")
    return failed == 0


# ── 4. 속도 검증 ──

SPEED_TESTS = [
    {"q": "어떤 보험 있어?", "cat": "상품추천", "target": 6.0},
    {"q": "사망 보장 보험 추천해주세요", "cat": "상품추천", "target": 6.0},
    {"q": "암보험 면책기간이 얼마예요?", "cat": "약관", "target": 15.0},
    {"q": "종신보험이랑 정기보험 차이?", "cat": "비교", "target": 15.0},
]


def test_speed(agent):
    print("\n" + "=" * 60)
    print("4. 속도 검증")
    print("=" * 60)

    passed = 0
    failed = 0

    for t in SPEED_TESTS:
        agent.reset()
        t0 = time.time()
        resp = agent.chat(t["q"])
        elapsed = time.time() - t0

        target = t["target"]
        ok = elapsed <= target and not resp.error
        icon = "✅" if ok else "❌"

        if ok:
            passed += 1
        else:
            failed += 1

        tools = [tc.name for tc in resp.tool_calls]
        pre = "pre" if resp.pre_routed else "llm"
        print(f"  {icon} [{t['cat']}] {elapsed:.1f}초 (목표 {target}초) | {pre} | {tools}")
        if resp.error:
            print(f"      오류: {resp.error}")

    print(f"\n  결과: {passed}/{passed+failed} 통과")
    return failed == 0


# ── 메인 ──

def main():
    print("🔍 품질 검증 시작\n")

    # 1. 의도 분류 (LLM 불필요)
    intent_ok = test_intent_classification()

    # 2. 데이터 정확성 (LLM 불필요)
    data_ok = test_data_accuracy()

    # 3+4. LLM 필요
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("\n⚠️ API 키 없음 — LLM 테스트 스킵")
        return

    print("\nAgent 초기화 중...")
    agent = InsuranceAgent(api_key=api_key, load_models=True)
    print("준비 완료")

    halluc_ok = test_hallucination(agent)
    speed_ok = test_speed(agent)

    # 종합
    print("\n" + "=" * 60)
    print("📊 종합 결과")
    print("=" * 60)
    print(f"  의도 분류:    {'✅' if intent_ok else '❌'}")
    print(f"  데이터 정확성: {'✅' if data_ok else '❌'}")
    print(f"  할루시네이션:  {'✅' if halluc_ok else '❌'}")
    print(f"  속도:         {'✅' if speed_ok else '❌'}")

    all_ok = intent_ok and data_ok and halluc_ok and speed_ok
    print(f"\n  {'✅ 전체 통과' if all_ok else '❌ 일부 실패 — 수정 필요'}")


if __name__ == "__main__":
    main()
