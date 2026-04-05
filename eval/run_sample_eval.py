"""
분야별 2~3건 샘플 테스트 — 속도 + 품질 확인용
"""

import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from agent_runner import InsuranceAgent, classify_intent

SAMPLES = [
    # 상품추천 (catalog pre-route 대상)
    {"cat": "상품추천", "q": "KB라이프에 어떤 보험 상품이 있어?"},
    {"cat": "상품추천", "q": "사망 보장 되는 보험 추천해주세요"},
    {"cat": "상품추천", "q": "간편심사로 가입할 수 있는 거 있어요?"},

    # 보장/약관 (search)
    {"cat": "보장/지급", "q": "암보험 가입 후 바로 암 진단받으면 보험금 나와?"},
    {"cat": "보장/지급", "q": "종신보험 사망보험금 지급 조건이 뭐야?"},

    # 면책/제외 (search)
    {"cat": "면책/제외", "q": "암보험 면책기간이 얼마예요?"},
    {"cat": "면책/제외", "q": "보험금 지급 안 되는 경우는?"},

    # 보험료 (premium)
    {"cat": "보험료", "q": "30세 남성 착한암보험 보험료 알려줘"},
    {"cat": "보험료", "q": "40세 여성 종신보험 일반심사형 보험료는?"},

    # 상품비교 (compare)
    {"cat": "비교", "q": "종신보험 일반심사형이랑 간편심사형 차이가 뭐야?"},
    {"cat": "비교", "q": "종신보험이랑 정기보험 뭐가 달라?"},

    # 해지/변경 (search)
    {"cat": "해지/변경", "q": "청약 철회는 언제까지 가능한가요?"},
    {"cat": "해지/변경", "q": "보험료 안 내면 어떻게 돼?"},
]


def run():
    api_key = os.getenv("OPENROUTER_API_KEY")
    print("Agent 초기화 중...")
    agent = InsuranceAgent(api_key=api_key, load_models=True)
    print("준비 완료\n")

    results = []

    for i, s in enumerate(SAMPLES):
        agent.reset()
        intent = classify_intent(s["q"])

        print(f"[{i+1}/{len(SAMPLES)}] [{s['cat']}] {s['q']}")
        print(f"  의도: {intent} | pre-route: {'catalog' == intent}")

        t0 = time.time()
        resp = agent.chat(s["q"])
        elapsed = time.time() - t0

        tools = [tc.name for tc in resp.tool_calls]
        has_error = resp.error is not None
        pre = resp.pre_routed

        status = "❌ ERR" if has_error else "⚠️ NO_TOOL" if not tools else "✅"
        print(f"  {status} | {elapsed:.1f}초 | Tools: {tools} | pre_routed: {pre}")
        if has_error:
            print(f"  오류: {resp.error}")
        print(f"  응답: {resp.content[:150]}...")
        print()

        results.append({
            "cat": s["cat"], "q": s["q"], "intent": intent,
            "elapsed": round(elapsed, 1), "tools": tools,
            "pre_routed": pre, "error": resp.error,
            "no_tool": len(tools) == 0 and not has_error,
        })

    # 요약
    print("=" * 60)
    print("📊 요약")
    print("=" * 60)

    cats = {}
    for r in results:
        c = r["cat"]
        if c not in cats:
            cats[c] = {"times": [], "errors": 0, "no_tool": 0, "pre_routed": 0}
        cats[c]["times"].append(r["elapsed"])
        if r["error"]: cats[c]["errors"] += 1
        if r["no_tool"]: cats[c]["no_tool"] += 1
        if r["pre_routed"]: cats[c]["pre_routed"] += 1

    for c, s in cats.items():
        avg = sum(s["times"]) / len(s["times"])
        print(f"  {c:<10} 평균 {avg:.1f}초 | 오류 {s['errors']} | "
              f"Tool미사용 {s['no_tool']} | pre-route {s['pre_routed']}")

    all_times = [r["elapsed"] for r in results if not r["error"]]
    if all_times:
        print(f"\n  전체 평균: {sum(all_times)/len(all_times):.1f}초")
        print(f"  pre-route 평균: {sum(r['elapsed'] for r in results if r['pre_routed'] and not r['error']) / max(1, sum(1 for r in results if r['pre_routed'] and not r['error'])):.1f}초")
        normal = [r['elapsed'] for r in results if not r['pre_routed'] and not r['error']]
        if normal:
            print(f"  일반 경로 평균: {sum(normal)/len(normal):.1f}초")


if __name__ == "__main__":
    run()
