"""
KB라이프 AI Agent — 평가 데이터셋 자동화 테스트

순차 실행 (1개씩), 진행도 표시, 결과 JSONL로 저장.
사용법: python eval/run_eval.py
"""

import csv
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from agent_runner import InsuranceAgent

# ── 설정 ──
EVAL_CSV = os.path.normpath(os.path.expanduser("~/Downloads/insurance_eval_dataset.csv"))
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"eval_{TIMESTAMP}.jsonl")
SUMMARY_FILE = os.path.join(OUTPUT_DIR, f"eval_{TIMESTAMP}_summary.json")


def load_questions(csv_path: str) -> list[dict]:
    """CSV에서 질문 로드 (주석 행 스킵)"""
    questions = []
    with open(csv_path, "r", encoding="utf-8") as f:
        # 주석 행 스킵
        lines = [line for line in f if not line.startswith("#")]

    reader = csv.DictReader(lines)
    for row in reader:
        if row.get("question", "").strip():
            questions.append({
                "category": row.get("category", "").strip(),
                "question": row.get("question", "").strip(),
                "style": row.get("style", "").strip(),
                "expected_products": [
                    p.strip() for p in row.get("product", "").split("|") if p.strip()
                ],
                "expected_clause": row.get("clause", "").strip(),
            })
    return questions


def print_progress(current, total, category, elapsed, errors):
    """진행도 바 출력"""
    pct = current / total * 100
    bar_len = 30
    filled = int(bar_len * current / total)
    bar = "█" * filled + "░" * (bar_len - filled)

    avg_time = elapsed / current if current > 0 else 0
    remaining = avg_time * (total - current)

    mins_left = int(remaining // 60)
    secs_left = int(remaining % 60)

    print(f"\r  [{bar}] {current}/{total} ({pct:.0f}%) | "
          f"{category:<8} | "
          f"오류 {errors}건 | "
          f"남은 시간 ~{mins_left}분{secs_left:02d}초", end="", flush=True)


def run_eval():
    # 1. 질문 로드
    print(f"📂 데이터셋 로드: {EVAL_CSV}")
    questions = load_questions(EVAL_CSV)
    total = len(questions)
    print(f"   {total}개 질문 로드 완료\n")

    # 카테고리별 통계
    cats = {}
    for q in questions:
        cats[q["category"]] = cats.get(q["category"], 0) + 1
    for cat, cnt in cats.items():
        print(f"   {cat}: {cnt}개")
    print()

    # 2. Agent 초기화
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("❌ OPENROUTER_API_KEY가 설정되지 않았습니다.")
        sys.exit(1)

    print("🔧 Agent 초기화 중 (검색엔진 포함)...")
    t0 = time.time()
    agent = InsuranceAgent(api_key=api_key, load_models=True)
    print(f"   초기화 완료: {time.time() - t0:.1f}초\n")

    # 3. 순차 실행
    print(f"🚀 평가 시작 — 결과 저장: {OUTPUT_FILE}\n")

    results = []
    errors = 0
    start_time = time.time()

    output_fp = open(OUTPUT_FILE, "w", encoding="utf-8")

    for i, q in enumerate(questions):
        agent.reset()

        # 진행도 표시
        elapsed = time.time() - start_time
        print_progress(i, total, q["category"], elapsed, errors)

        # Agent 호출
        try:
            t_start = time.time()
            response = agent.chat(q["question"])
            t_elapsed = time.time() - t_start

            result = {
                "id": i + 1,
                "category": q["category"],
                "style": q["style"],
                "question": q["question"],
                "expected_products": q["expected_products"],
                "expected_clause": q["expected_clause"],
                "response": response.content,
                "tools_called": [tc.name for tc in response.tool_calls],
                "tool_args": [tc.arguments for tc in response.tool_calls],
                "error": response.error,
                "elapsed_sec": round(t_elapsed, 1),
            }

            if response.error:
                errors += 1

        except Exception as e:
            errors += 1
            result = {
                "id": i + 1,
                "category": q["category"],
                "style": q["style"],
                "question": q["question"],
                "expected_products": q["expected_products"],
                "expected_clause": q["expected_clause"],
                "response": "",
                "tools_called": [],
                "tool_args": [],
                "error": str(e),
                "elapsed_sec": 0,
            }

        results.append(result)

        # JSONL에 즉시 기록 (중간에 중단돼도 결과 보존)
        output_fp.write(json.dumps(result, ensure_ascii=False) + "\n")
        output_fp.flush()

    output_fp.close()

    # 최종 진행도
    elapsed = time.time() - start_time
    print_progress(total, total, "완료", elapsed, errors)
    print("\n")

    # 4. 요약 통계
    total_time = time.time() - start_time

    cat_stats = {}
    for r in results:
        cat = r["category"]
        if cat not in cat_stats:
            cat_stats[cat] = {"total": 0, "errors": 0, "tools_used": {}, "avg_time": []}
        cat_stats[cat]["total"] += 1
        if r["error"]:
            cat_stats[cat]["errors"] += 1
        cat_stats[cat]["avg_time"].append(r["elapsed_sec"])
        for tool in r["tools_called"]:
            cat_stats[cat]["tools_used"][tool] = cat_stats[cat]["tools_used"].get(tool, 0) + 1

    # 평균 시간 계산
    for cat in cat_stats:
        times = cat_stats[cat]["avg_time"]
        cat_stats[cat]["avg_time"] = round(sum(times) / len(times), 1) if times else 0

    summary = {
        "timestamp": TIMESTAMP,
        "total_questions": total,
        "total_errors": errors,
        "total_time_sec": round(total_time, 1),
        "avg_time_per_question": round(total_time / total, 1) if total > 0 else 0,
        "category_stats": cat_stats,
    }

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # 5. 결과 출력
    print("=" * 60)
    print("📊 평가 결과 요약")
    print("=" * 60)
    print(f"  총 질문: {total}개")
    print(f"  오류: {errors}건 ({errors/total*100:.1f}%)")
    print(f"  총 소요: {int(total_time//60)}분 {int(total_time%60)}초")
    print(f"  평균 응답: {total_time/total:.1f}초/질문")
    print()

    print("  카테고리별:")
    for cat, stats in cat_stats.items():
        err_pct = stats['errors'] / stats['total'] * 100 if stats['total'] > 0 else 0
        print(f"    {cat:<10} {stats['total']:>3}개 | "
              f"오류 {stats['errors']}건 ({err_pct:.0f}%) | "
              f"평균 {stats['avg_time']}초 | "
              f"Tools: {dict(stats['tools_used'])}")

    print(f"\n  결과: {OUTPUT_FILE}")
    print(f"  요약: {SUMMARY_FILE}")


if __name__ == "__main__":
    run_eval()
