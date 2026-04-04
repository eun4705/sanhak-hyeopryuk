"""
저장된 ChromaDB들로 Golden Set v3 평가
모델별 Hit Rate / MRR 비교
"""

import json
import os
import re
import glob
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_PATH = os.path.join(BASE_DIR, "eval", "golden_set_v3.json")

# 모델명 → ChromaDB 경로 매핑
MODEL_DIRS = {}
for d in glob.glob(os.path.join(BASE_DIR, "data", "chroma_*")):
    dirname = os.path.basename(d)
    if dirname in ("chroma_db", "chroma_db_v2"):
        continue
    # chroma_dragonkue_BGE_m3_ko → dragonkue/BGE-m3-ko
    model_part = dirname.replace("chroma_", "")
    MODEL_DIRS[dirname] = d


def load_golden():
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_model(model_name, chroma_dir, golden, model):
    """단일 모델 평가"""
    try:
        client = chromadb.PersistentClient(path=chroma_dir)
        col = client.get_collection("insurance_articles")
    except Exception as e:
        return None

    # 쿼리 임베딩
    queries = [q["query"] for q in golden]
    query_embs = model.encode(queries, normalize_embeddings=True)

    k_values = [1, 3, 5, 10]
    results = {}

    for k in k_values:
        search_results = col.query(
            query_embeddings=query_embs.tolist(),
            n_results=k,
        )

        hits = 0
        rrs = []

        for i, q in enumerate(golden):
            relevant = set(q["relevant_ids"])
            retrieved = search_results["ids"][i][:k]

            hit = any(rid in relevant for rid in retrieved)
            if hit:
                hits += 1

            rr = 0
            for rank, rid in enumerate(retrieved, 1):
                if rid in relevant:
                    rr = 1.0 / rank
                    break
            rrs.append(rr)

        n = len(golden)
        results[k] = {
            "hit_rate": hits / n,
            "mrr": sum(rrs) / n,
            "hits": hits,
            "total": n,
        }

    return results


# 모델명 복원 매핑
DIRNAME_TO_MODEL = {
    "chroma_dragonkue_BGE_m3_ko": "dragonkue/BGE-m3-ko",
    "chroma_nlpai_lab_KURE_v1": "nlpai-lab/KURE-v1",
    "chroma_nlpai_lab_KoE5": "nlpai-lab/KoE5",
    "chroma_codefuse_ai_F2LLM_v2_8B": "codefuse-ai/F2LLM-v2-8B",
    "chroma_Snowflake_snowflake_arctic_embed_l_v2.0": "Snowflake/snowflake-arctic-embed-l-v2.0",
    "chroma_jinaai_jina_embeddings_v3": "jinaai/jina-embeddings-v3",
    "chroma_Qwen_Qwen3_Embedding_0.6B": "Qwen/Qwen3-Embedding-0.6B",
    "chroma_Qwen_Qwen3_Embedding_4B": "Qwen/Qwen3-Embedding-4B",
    "chroma_Qwen_Qwen3_Embedding_8B": "Qwen/Qwen3-Embedding-8B",
}


def main():
    golden = load_golden()
    print(f"Golden Set: {len(golden)}개 쿼리\n")

    all_results = []

    for dirname, chroma_dir in sorted(MODEL_DIRS.items()):
        model_name = DIRNAME_TO_MODEL.get(dirname)
        if not model_name:
            continue

        # 컬렉션 존재 확인
        try:
            client = chromadb.PersistentClient(path=chroma_dir)
            col = client.get_collection("insurance_articles")
            if col.count() < 5000:
                print(f"[SKIP] {model_name}: {col.count()}개 (불완전)")
                continue
        except:
            print(f"[SKIP] {model_name}: 컬렉션 없음")
            continue

        print(f"평가 중: {model_name}...")

        try:
            model = SentenceTransformer(model_name, trust_remote_code=True)
            results = evaluate_model(model_name, chroma_dir, golden, model)
            del model
            import gc; gc.collect()
            try:
                import torch; torch.cuda.empty_cache()
            except:
                pass
        except Exception as e:
            print(f"  [ERROR] {e}")
            continue

        if results:
            all_results.append({"model": model_name, "results": results})
            r5 = results[5]
            print(f"  HR@5: {r5['hit_rate']:.1%} ({r5['hits']}/{r5['total']})  MRR@5: {r5['mrr']:.4f}")

    # 최종 비교표
    print(f"\n\n{'#'*70}")
    print(f"  최종 비교 결과")
    print(f"{'#'*70}")
    print(f"\n  {'모델':<45} {'HR@1':>6} {'HR@3':>6} {'HR@5':>6} {'HR@10':>6} {'MRR@5':>8}")
    print(f"  {'-'*45} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")

    all_results.sort(key=lambda x: x["results"][5]["mrr"], reverse=True)

    for r in all_results:
        name = r["model"][:44]
        r1 = r["results"][1]
        r3 = r["results"][3]
        r5 = r["results"][5]
        r10 = r["results"][10]
        print(f"  {name:<45} {r1['hit_rate']:>5.1%} {r3['hit_rate']:>5.1%} {r5['hit_rate']:>5.1%} {r10['hit_rate']:>5.1%} {r5['mrr']:>8.4f}")

    # 결과 저장
    output_path = os.path.join(BASE_DIR, "eval", "model_comparison_v3.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
