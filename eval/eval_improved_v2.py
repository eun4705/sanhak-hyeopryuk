"""
개선된 평가 v2: 제목 기반 매칭 (상품 무관하게 같은 조항이면 정답)
"""

import json
import os
import sys
import re

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scraper"))
from search_engine import SearchEngine

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_PATH = os.path.join(BASE_DIR, "eval", "golden_set.json")


def load_golden_set():
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        return [q for q in json.load(f) if q["relevant_ids"]]


def title_match(retrieved_meta, golden_ids, collection):
    """정답 문서와 같은 제목의 조항이면 정답으로 인정"""
    # 정답 문서들의 제목 가져오기
    golden_data = collection.get(ids=golden_ids, include=["metadatas"])
    golden_titles = set()
    for meta in golden_data["metadatas"]:
        t = re.sub(r"\s+", "", meta.get("title", ""))
        if t:
            golden_titles.add(t)

    # 검색 결과의 제목과 비교
    ret_title = re.sub(r"\s+", "", retrieved_meta.get("title", ""))
    return ret_title in golden_titles


def evaluate(engine, golden_set, label, collection, **search_kwargs):
    print(f"\n{'#'*60}")
    print(f"  {label}")
    print(f"{'#'*60}")

    k_values = [1, 3, 5, 10]

    for k in k_values:
        strict_hits = 0  # ID 정확 매칭
        relaxed_hits = 0  # 제목 매칭 (상품 무관)
        strict_rrs = []
        relaxed_rrs = []

        for q in golden_set:
            relevant = set(q["relevant_ids"])
            results = engine.search(q["query"], top_k=k, **search_kwargs)
            retrieved_ids = [r["id"] for r in results]
            retrieved_metas = [r["metadata"] for r in results]

            # Strict: ID 정확 매칭
            s_hit = any(rid in relevant for rid in retrieved_ids)
            if s_hit:
                strict_hits += 1
            s_rr = 0
            for rank, rid in enumerate(retrieved_ids, 1):
                if rid in relevant:
                    s_rr = 1.0 / rank
                    break
            strict_rrs.append(s_rr)

            # Relaxed: 같은 제목이면 OK
            r_hit = s_hit  # strict가 맞으면 relaxed도 맞음
            r_rr = s_rr
            if not r_hit:
                for rank, meta in enumerate(retrieved_metas, 1):
                    if title_match(meta, list(relevant), collection):
                        r_hit = True
                        r_rr = 1.0 / rank
                        break
            if r_hit:
                relaxed_hits += 1
            relaxed_rrs.append(r_rr)

        n = len(golden_set)
        print(f"  K={k:>2}  |  Strict HR: {strict_hits/n:>6.1%} ({strict_hits:>2}/{n})  MRR: {sum(strict_rrs)/n:.4f}  |  Relaxed HR: {relaxed_hits/n:>6.1%} ({relaxed_hits:>2}/{n})  MRR: {sum(relaxed_rrs)/n:.4f}")


def run_domain_tests(engine, label, **kw):
    print(f"\n  [{label}]")
    tests = [
        ("동의어: 피보험자=보험대상자", "피보험자가 사망하면 보험금은?", "보험 대상자가 사망하면 보험금은?", "높을수록"),
        ("동의어: 해약환급금=해지환불금", "해약환급금이 얼마야?", "보험 해지하면 환불금 얼마야?", "높을수록"),
        ("동의어: 청구=신청", "보험금 청구 방법은?", "보험금 신청하려면 어떻게 해?", "높을수록"),
        ("부정문: 지급 vs 미지급", "보험금을 지급하는 사유는?", "보험금을 지급하지 않는 사유는?", "낮을수록"),
        ("구어체: 취소=청약철회", "보험 들었다가 취소하고 싶어", "청약의 철회", "높을수록"),
        ("구어체: 돈돌려받기=해약환급금", "보험 해지하면 돈 돌려받을 수 있어?", "해약환급금", "높을수록"),
    ]
    for name, q1, q2, expect in tests:
        r1 = set(r["id"] for r in engine.search(q1, top_k=5, **kw))
        r2 = set(r["id"] for r in engine.search(q2, top_k=5, **kw))
        overlap = len(r1 & r2)
        print(f"  {name}: 겹침 {overlap}/5 ({overlap/5:.0%}) [기대: {expect}]")


def main():
    engine = SearchEngine(verbose=True)
    golden = load_golden_set()
    col = engine.collection

    configs = [
        ("A. 기존 (벡터만)", dict(use_reranker=False, use_expansion=False, vector_weight=1.0, bm25_weight=0.0)),
        ("B. Hybrid (벡터+BM25)", dict(use_reranker=False, use_expansion=False, vector_weight=0.5, bm25_weight=0.5)),
        ("C. Hybrid + 쿼리확장", dict(use_reranker=False, use_expansion=True, vector_weight=0.5, bm25_weight=0.5)),
        ("D. 풀 파이프라인", dict(use_reranker=True, use_expansion=True, vector_weight=0.5, bm25_weight=0.5)),
    ]

    for label, kw in configs:
        evaluate(engine, golden, label, col, **kw)

    print(f"\n\n{'#'*60}")
    print("  도메인 특화 테스트 비교")
    print(f"{'#'*60}")
    run_domain_tests(engine, "기존: 벡터만", use_reranker=False, use_expansion=False, vector_weight=1.0, bm25_weight=0.0)
    run_domain_tests(engine, "개선: 풀 파이프라인", use_reranker=True, use_expansion=True, vector_weight=0.5, bm25_weight=0.5)


if __name__ == "__main__":
    main()
