"""
메타데이터 필터 적용 재평가
Golden Set v3의 product 필드로 prodCode 필터링하여 검색
7개 모델 전부 평가
"""

import json
import os
import gc
import glob
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_PATH = os.path.join(BASE_DIR, "eval", "golden_set_v3.json")

MODELS = [
    ("dragonkue/BGE-m3-ko", "chroma_dragonkue_BGE_m3_ko"),
    ("nlpai-lab/KURE-v1", "chroma_nlpai_lab_KURE_v1"),
    ("nlpai-lab/KoE5", "chroma_nlpai_lab_KoE5"),
    ("Snowflake/snowflake-arctic-embed-l-v2.0", "chroma_Snowflake_snowflake_arctic_embed_l_v2.0"),
    ("Qwen/Qwen3-Embedding-0.6B", "chroma_Qwen_Qwen3_Embedding_0.6B"),
    ("Qwen/Qwen3-Embedding-4B", "chroma_Qwen_Qwen3_Embedding_4B"),
    ("codefuse-ai/F2LLM-v2-8B", "chroma_codefuse_ai_F2LLM_v2_8B"),
]


def load_golden():
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_model(model_name, chroma_dir, golden):
    print(f"\n평가: {model_name}")

    # 모델 로드
    try:
        model = SentenceTransformer(model_name, trust_remote_code=True)
    except Exception as e:
        print(f"  [ERROR] 모델 로드 실패: {e}")
        return None

    # ChromaDB 로드
    client = chromadb.PersistentClient(path=os.path.join(BASE_DIR, "data", chroma_dir))
    col = client.get_collection("insurance_articles")

    queries = [q["query"] for q in golden]
    query_embs = model.encode(queries, normalize_embeddings=True)

    k_values = [1, 3, 5, 10]

    # 필터 없는 결과
    no_filter_results = {}
    for k in k_values:
        search = col.query(query_embeddings=query_embs.tolist(), n_results=k)
        hits = 0
        rrs = []
        for i, q in enumerate(golden):
            relevant = set(q["relevant_ids"])
            retrieved = search["ids"][i][:k]
            hit = any(r in relevant for r in retrieved)
            if hit: hits += 1
            rr = 0
            for rank, r in enumerate(retrieved, 1):
                if r in relevant:
                    rr = 1.0 / rank
                    break
            rrs.append(rr)
        n = len(golden)
        no_filter_results[k] = {"hr": hits / n, "mrr": sum(rrs) / n, "hits": hits}

    # 필터 있는 결과 (product별 검색)
    filter_results = {}
    for k in k_values:
        hits = 0
        rrs = []
        for i, q in enumerate(golden):
            prod_code = q.get("product", "")
            relevant = set(q["relevant_ids"])

            # prodCode 필터 적용
            if prod_code:
                search = col.query(
                    query_embeddings=[query_embs[i].tolist()],
                    n_results=k,
                    where={"prodCode": prod_code},
                )
            else:
                search = col.query(
                    query_embeddings=[query_embs[i].tolist()],
                    n_results=k,
                )

            retrieved = search["ids"][0][:k]
            hit = any(r in relevant for r in retrieved)
            if hit: hits += 1
            rr = 0
            for rank, r in enumerate(retrieved, 1):
                if r in relevant:
                    rr = 1.0 / rank
                    break
            rrs.append(rr)
        n = len(golden)
        filter_results[k] = {"hr": hits / n, "mrr": sum(rrs) / n, "hits": hits}

    # 출력
    print(f"  {'':>5} | {'필터 없음':>18} | {'필터 적용':>18} | {'개선':>8}")
    print(f"  {'K':>5} | {'HR':>8} {'MRR':>8} | {'HR':>8} {'MRR':>8} | {'HR':>8}")
    print(f"  {'-'*5}-+-{'-'*8}-{'-'*8}-+-{'-'*8}-{'-'*8}-+-{'-'*8}")
    for k in k_values:
        nf = no_filter_results[k]
        f = filter_results[k]
        diff = f["hr"] - nf["hr"]
        print(f"  {k:>5} | {nf['hr']:>7.1%} {nf['mrr']:>8.4f} | {f['hr']:>7.1%} {f['mrr']:>8.4f} | {diff:>+7.1%}")

    # 메모리 해제
    del model, query_embs
    gc.collect()
    try:
        import torch; torch.cuda.empty_cache()
    except: pass

    return {
        "model": model_name,
        "no_filter": no_filter_results,
        "with_filter": filter_results,
    }


def main():
    golden = load_golden()
    print(f"Golden Set: {len(golden)}개 (상품 지정 질문)\n")

    all_results = []
    for model_name, chroma_dir in MODELS:
        result = evaluate_model(model_name, chroma_dir, golden)
        if result:
            all_results.append(result)

    # 최종 비교표
    print(f"\n\n{'#'*70}")
    print(f"  최종 비교 (K=5 기준)")
    print(f"{'#'*70}")
    print(f"\n  {'모델':<42} {'필터없음':>10} {'필터적용':>10} {'개선':>8} {'MRR(필터)':>10}")
    print(f"  {'-'*42} {'-'*10} {'-'*10} {'-'*8} {'-'*10}")

    all_results.sort(key=lambda x: x["with_filter"][5]["hr"], reverse=True)

    for r in all_results:
        name = r["model"][:41]
        nf = r["no_filter"][5]
        f = r["with_filter"][5]
        diff = f["hr"] - nf["hr"]
        print(f"  {name:<42} {nf['hr']:>9.1%} {f['hr']:>9.1%} {diff:>+7.1%} {f['mrr']:>10.4f}")

    # 저장
    output_path = os.path.join(BASE_DIR, "eval", "model_comparison_final.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
