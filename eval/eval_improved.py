"""
개선된 검색 파이프라인 평가
기존(벡터만) vs 개선(Hybrid+Reranker+쿼리확장) 비교
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scraper"))
from search_engine import SearchEngine, expand_query

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_PATH = os.path.join(BASE_DIR, "eval", "golden_set.json")


def load_golden_set():
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        return [q for q in json.load(f) if q["relevant_ids"]]


def evaluate_engine(engine, golden_set, label, k_values=[1, 3, 5, 10], **search_kwargs):
    print(f"\n{'#'*60}")
    print(f"  {label}")
    print(f"{'#'*60}")

    all_results = {}
    for q in golden_set:
        results = engine.search(q["query"], top_k=max(k_values), **search_kwargs)
        all_results[q["id"]] = [r["id"] for r in results]

    for k in k_values:
        hits = 0
        reciprocal_ranks = []

        for q in golden_set:
            relevant = set(q["relevant_ids"])
            retrieved = all_results[q["id"]][:k]

            hit = any(rid in relevant for rid in retrieved)
            if hit:
                hits += 1

            rr = 0
            for rank, rid in enumerate(retrieved, 1):
                if rid in relevant:
                    rr = 1.0 / rank
                    break
            reciprocal_ranks.append(rr)

        hit_rate = hits / len(golden_set)
        mrr = sum(reciprocal_ranks) / len(golden_set)

        print(f"  K={k:>2}  |  Hit Rate: {hit_rate:>6.1%} ({hits:>2}/{len(golden_set)})  |  MRR: {mrr:.4f}")

    # 실패 분석 (top-5)
    print(f"\n  실패 분석 (Hit Rate@5 미스):")
    miss_count = 0
    for q in golden_set:
        relevant = set(q["relevant_ids"])
        retrieved = all_results[q["id"]][:5]
        if not any(rid in relevant for rid in retrieved):
            miss_count += 1
            results = engine.search(q["query"], top_k=5, **search_kwargs)
            print(f"\n  Q{q['id']}: {q['query']}")
            print(f"  정답: {q['relevant_ids']}")
            for i, r in enumerate(results[:3]):
                meta = r["metadata"]
                marker = "✓" if r["id"] in relevant else "✗"
                print(f"    {i+1}. {marker} [{meta['prodCode']}] {meta['조']} {meta.get('title','')[:35]}")

    if miss_count == 0:
        print("  모든 쿼리가 top-5 안에 정답을 포함합니다!")
    else:
        print(f"\n  미스: {miss_count}/{len(golden_set)}")

    return all_results


def run_domain_tests(engine, **search_kwargs):
    print(f"\n{'#'*60}")
    print(f"  도메인 특화 테스트 (개선)")
    print(f"{'#'*60}")

    tests = [
        ("동의어: 피보험자=보험대상자", "피보험자가 사망하면 보험금은?", "보험 대상자가 사망하면 보험금은?", "높을수록"),
        ("동의어: 해약환급금=해지환불금", "해약환급금이 얼마야?", "보험 해지하면 환불금 얼마야?", "높을수록"),
        ("동의어: 청구=신청", "보험금 청구 방법은?", "보험금 신청하려면 어떻게 해?", "높을수록"),
        ("부정문: 지급 vs 미지급", "보험금을 지급하는 사유는?", "보험금을 지급하지 않는 사유는?", "낮을수록"),
        ("구어체: 취소=청약철회", "보험 들었다가 취소하고 싶어", "청약의 철회", "높을수록"),
        ("구어체: 돈돌려받기=해약환급금", "보험 해지하면 돈 돌려받을 수 있어?", "해약환급금", "높을수록"),
    ]

    for name, q1, q2, expect in tests:
        r1 = engine.search(q1, top_k=5, **search_kwargs)
        r2 = engine.search(q2, top_k=5, **search_kwargs)
        ids1 = set(r["id"] for r in r1)
        ids2 = set(r["id"] for r in r2)
        overlap = len(ids1 & ids2)
        print(f"  {name}: 겹침 {overlap}/5 ({overlap/5:.0%}) [기대: 겹침률 {expect} 좋음]")


def main():
    engine = SearchEngine(verbose=True)
    golden = load_golden_set()

    # A. 기존 방식 (벡터만, 확장/reranker 없이)
    evaluate_engine(
        engine, golden, "A. 기존 (벡터만)",
        use_reranker=False, use_expansion=False,
        vector_weight=1.0, bm25_weight=0.0
    )

    # B. BM25만
    evaluate_engine(
        engine, golden, "B. BM25만",
        use_reranker=False, use_expansion=False,
        vector_weight=0.0, bm25_weight=1.0
    )

    # C. Hybrid (벡터+BM25)
    evaluate_engine(
        engine, golden, "C. Hybrid (벡터+BM25)",
        use_reranker=False, use_expansion=False,
        vector_weight=0.5, bm25_weight=0.5
    )

    # D. Hybrid + 쿼리확장
    evaluate_engine(
        engine, golden, "D. Hybrid + 쿼리확장",
        use_reranker=False, use_expansion=True,
        vector_weight=0.5, bm25_weight=0.5
    )

    # E. 풀 파이프라인 (Hybrid + 쿼리확장 + Reranker)
    evaluate_engine(
        engine, golden, "E. 풀 파이프라인 (Hybrid + 확장 + Reranker)",
        use_reranker=True, use_expansion=True,
        vector_weight=0.5, bm25_weight=0.5
    )

    # 도메인 테스트
    print(f"\n\n{'='*60}")
    print("  도메인 특화 테스트: 기존 vs 개선")
    print(f"{'='*60}")

    print("\n[기존: 벡터만]")
    run_domain_tests(engine, use_reranker=False, use_expansion=False, vector_weight=1.0, bm25_weight=0.0)

    print("\n[개선: 풀 파이프라인]")
    run_domain_tests(engine, use_reranker=True, use_expansion=True, vector_weight=0.5, bm25_weight=0.5)


if __name__ == "__main__":
    main()
