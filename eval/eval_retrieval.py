"""
임베딩 품질 평가: Hit Rate@K, MRR, Precision@K
Golden Set 기반 retrieval 정확도 측정
"""

import json
import os
import time
from sentence_transformers import SentenceTransformer
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DIR = os.path.join(BASE_DIR, "data", "chroma_db")
GOLDEN_PATH = os.path.join(BASE_DIR, "eval", "golden_set.json")
MODEL_NAME = "dragonkue/BGE-m3-ko"


def load_golden_set():
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate(model, collection, golden_set, k_values=[1, 3, 5, 10]):
    # relevant_ids가 비어있는 항목 제외
    golden_set = [q for q in golden_set if q["relevant_ids"]]

    queries = [q["query"] for q in golden_set]
    print(f"쿼리 {len(queries)}개 임베딩 중...")
    query_embeddings = model.encode(queries, normalize_embeddings=True)

    max_k = max(k_values)
    results = collection.query(
        query_embeddings=query_embeddings.tolist(),
        n_results=max_k,
    )

    # 각 K에 대해 지표 계산
    for k in k_values:
        hits = 0
        reciprocal_ranks = []
        precisions = []

        for i, q in enumerate(golden_set):
            relevant = set(q["relevant_ids"])
            retrieved = results["ids"][i][:k]

            # Hit Rate: top-K에 정답이 하나라도 있는지
            hit = any(rid in relevant for rid in retrieved)
            if hit:
                hits += 1

            # MRR: 첫 번째 정답의 역수
            rr = 0
            for rank, rid in enumerate(retrieved, 1):
                if rid in relevant:
                    rr = 1.0 / rank
                    break
            reciprocal_ranks.append(rr)

            # Precision@K: top-K 중 정답 비율
            correct = sum(1 for rid in retrieved if rid in relevant)
            precisions.append(correct / k)

        hit_rate = hits / len(golden_set)
        mrr = sum(reciprocal_ranks) / len(golden_set)
        avg_precision = sum(precisions) / len(golden_set)

        print(f"\n{'='*50}")
        print(f"  K = {k}")
        print(f"{'='*50}")
        print(f"  Hit Rate@{k}:    {hit_rate:.1%} ({hits}/{len(golden_set)})")
        print(f"  MRR@{k}:         {mrr:.4f}")
        print(f"  Precision@{k}:   {avg_precision:.4f}")

    # 실패 분석 (top-5 기준)
    print(f"\n{'='*50}")
    print(f"  실패 분석 (Hit Rate@5 미스)")
    print(f"{'='*50}")
    miss_count = 0
    for i, q in enumerate(golden_set):
        relevant = set(q["relevant_ids"])
        retrieved = results["ids"][i][:5]
        if not any(rid in relevant for rid in retrieved):
            miss_count += 1
            print(f"\n  Q{q['id']}: {q['query']}")
            print(f"  정답: {q['relevant_ids']}")
            print(f"  검색결과:")
            for j, (rid, meta) in enumerate(
                zip(results["ids"][i][:5], results["metadatas"][i][:5])
            ):
                marker = "✓" if rid in relevant else "✗"
                print(f"    {j+1}. {marker} [{meta['prodCode']}] {meta['조']} {meta.get('title','')[:30]}")

    if miss_count == 0:
        print("  모든 쿼리가 top-5 안에 정답을 포함합니다!")

    return results


def main():
    print(f"모델 로드 중: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection("insurance_articles")
    print(f"ChromaDB: {collection.count()}개 문서")

    golden_set = load_golden_set()
    print(f"Golden Set: {len(golden_set)}개 쿼리")

    evaluate(model, collection, golden_set)


if __name__ == "__main__":
    main()
