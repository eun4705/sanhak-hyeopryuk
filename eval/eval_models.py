"""
임베딩 모델 9개 비교 테스트
각 모델로 약관 검색 → Golden Set Hit Rate/MRR 측정
"""

import json
import os
import sys
import time
import traceback
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENRICHED_DIR = os.path.join(BASE_DIR, "data", "약관_enriched")
GOLDEN_PATH = os.path.join(BASE_DIR, "eval", "golden_set.json")
CHROMA_BASE = os.path.join(BASE_DIR, "data")

MODELS = [
    "dragonkue/BGE-m3-ko",
    "nlpai-lab/KURE-v1",
    "nlpai-lab/KoE5",
    "codefuse-ai/F2LLM-v2-8B",
    "Snowflake/snowflake-arctic-embed-l-v2.0",
    "jinaai/jina-embeddings-v3",
    "Qwen/Qwen3-Embedding-0.6B",
    "Qwen/Qwen3-Embedding-4B",
    "Qwen/Qwen3-Embedding-8B",
]


def load_golden_set():
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        return [q for q in json.load(f) if q["relevant_ids"]]


def load_sections():
    """enriched JSON에서 모든 조항 로드"""
    import glob
    sections = []
    for filepath in sorted(glob.glob(os.path.join(ENRICHED_DIR, "*.json"))):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        product = data["product"]
        prod_code = data["prodCode"]
        for i, sec in enumerate(data["sections"]):
            doc_id = f"{prod_code}_{sec['type']}_{sec['조']}_{i}"
            # 임베딩 텍스트 구성
            parts = [f"상품: {product}"]
            if sec.get("특약명"):
                parts.append(f"특약: {sec['특약명']}")
            parts.append(f"{sec['관']} {sec['조']} {sec.get('title', '')}")
            if sec.get("summary"):
                parts.append(sec["summary"])
            if sec.get("keywords"):
                parts.append("키워드: " + ", ".join(sec["keywords"]))
            text = sec.get("text", "")
            if len(text) > 1500:
                text = text[:1500]
            parts.append(text)

            sections.append({
                "id": doc_id,
                "text": "\n".join(parts),
                "metadata": {
                    "product": product,
                    "prodCode": prod_code,
                    "type": sec.get("type", ""),
                    "관": sec.get("관", ""),
                    "조": sec.get("조", ""),
                    "title": sec.get("title", ""),
                    "category": sec.get("category", ""),
                },
            })
    return sections


def embed_and_evaluate(model_name, sections, golden_set):
    """단일 모델로 임베딩 → ChromaDB 저장 → Hit Rate/MRR 측정"""
    safe_name = model_name.replace("/", "_").replace("-", "_")
    chroma_dir = os.path.join(CHROMA_BASE, f"chroma_test_{safe_name}")

    print(f"\n{'='*60}")
    print(f"  모델: {model_name}")
    print(f"{'='*60}")

    # 1. 모델 로드
    try:
        print(f"  모델 로드 중...")
        t0 = time.time()

        # Qwen3-Embedding은 trust_remote_code 필요할 수 있음
        model = SentenceTransformer(model_name, trust_remote_code=True)
        load_time = time.time() - t0
        print(f"  모델 로드: {load_time:.1f}초")
    except Exception as e:
        print(f"  [ERROR] 모델 로드 실패: {e}")
        return None

    # 2. 문서 임베딩
    try:
        print(f"  {len(sections)}개 문서 임베딩 중...")
        doc_texts = [s["text"] for s in sections]
        t1 = time.time()
        doc_embeddings = model.encode(
            doc_texts,
            batch_size=32,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        embed_time = time.time() - t1
        print(f"  문서 임베딩: {embed_time:.1f}초 ({len(sections)/embed_time:.1f} docs/sec)")
    except Exception as e:
        print(f"  [ERROR] 문서 임베딩 실패: {e}")
        traceback.print_exc()
        return None

    # 3. ChromaDB 저장
    try:
        os.makedirs(chroma_dir, exist_ok=True)
        client = chromadb.PersistentClient(path=chroma_dir)
        try:
            client.delete_collection("test")
        except:
            pass
        collection = client.create_collection(
            name="test",
            metadata={"hnsw:space": "cosine"},
        )

        batch_size = 500
        for start in range(0, len(sections), batch_size):
            end = min(start + batch_size, len(sections))
            collection.add(
                ids=[s["id"] for s in sections[start:end]],
                embeddings=doc_embeddings[start:end].tolist(),
                documents=[s["text"] for s in sections[start:end]],
                metadatas=[s["metadata"] for s in sections[start:end]],
            )
    except Exception as e:
        print(f"  [ERROR] ChromaDB 저장 실패: {e}")
        return None

    # 4. 쿼리 임베딩 + 검색 + 평가
    queries = [q["query"] for q in golden_set]
    query_embeddings = model.encode(queries, normalize_embeddings=True)

    k_values = [1, 3, 5, 10]
    results_dict = {}

    for k in k_values:
        hits = 0
        relaxed_hits = 0
        rrs = []
        relaxed_rrs = []

        search_results = collection.query(
            query_embeddings=query_embeddings.tolist(),
            n_results=k,
        )

        for i, q in enumerate(golden_set):
            relevant = set(q["relevant_ids"])
            retrieved_ids = search_results["ids"][i][:k]
            retrieved_metas = search_results["metadatas"][i][:k]

            # Strict
            s_hit = any(rid in relevant for rid in retrieved_ids)
            if s_hit:
                hits += 1
            s_rr = 0
            for rank, rid in enumerate(retrieved_ids, 1):
                if rid in relevant:
                    s_rr = 1.0 / rank
                    break
            rrs.append(s_rr)

            # Relaxed (같은 제목이면 정답)
            r_hit = s_hit
            r_rr = s_rr
            if not r_hit:
                # 정답 문서의 제목 가져오기
                golden_titles = set()
                for rid in relevant:
                    for s in sections:
                        if s["id"] == rid:
                            golden_titles.add(s["metadata"]["title"].replace(" ", ""))
                            break
                for rank, meta in enumerate(retrieved_metas, 1):
                    ret_title = meta.get("title", "").replace(" ", "")
                    if ret_title in golden_titles:
                        r_hit = True
                        r_rr = 1.0 / rank
                        break
            if r_hit:
                relaxed_hits += 1
            relaxed_rrs.append(r_rr)

        n = len(golden_set)
        results_dict[k] = {
            "strict_hr": hits / n,
            "strict_mrr": sum(rrs) / n,
            "relaxed_hr": relaxed_hits / n,
            "relaxed_mrr": sum(relaxed_rrs) / n,
        }

    # 결과 출력
    print(f"\n  {'K':>3} | {'Strict HR':>10} {'MRR':>8} | {'Relaxed HR':>10} {'MRR':>8}")
    print(f"  {'-'*3}-+-{'-'*10}-{'-'*8}-+-{'-'*10}-{'-'*8}")
    for k in k_values:
        r = results_dict[k]
        print(f"  {k:>3} | {r['strict_hr']:>9.1%} {r['strict_mrr']:>8.4f} | {r['relaxed_hr']:>9.1%} {r['relaxed_mrr']:>8.4f}")

    # ChromaDB 유지 (최종 채택 모델 외 나중에 삭제)
    print(f"  ChromaDB 저장됨: {chroma_dir}")

    return {
        "model": model_name,
        "load_time": load_time,
        "embed_time": embed_time,
        "embed_speed": len(sections) / embed_time,
        "results": results_dict,
    }


def main():
    print("데이터 로드 중...")
    sections = load_sections()
    golden_set = load_golden_set()
    print(f"조항: {len(sections)}개, 테스트 쿼리: {len(golden_set)}개")

    all_results = []

    for model_name in MODELS:
        try:
            result = embed_and_evaluate(model_name, sections, golden_set)
            if result:
                all_results.append(result)
        except Exception as e:
            print(f"\n[SKIP] {model_name}: {e}")
            traceback.print_exc()
            continue

    # 최종 비교표
    print(f"\n\n{'#'*60}")
    print(f"  최종 비교 결과 (K=5 기준)")
    print(f"{'#'*60}")
    print(f"\n  {'모델':<45} {'S-HR@5':>8} {'S-MRR':>8} {'R-HR@5':>8} {'R-MRR':>8} {'속도':>10}")
    print(f"  {'-'*45} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")

    # Relaxed MRR 기준 정렬
    all_results.sort(key=lambda x: x["results"][5]["relaxed_mrr"], reverse=True)

    for r in all_results:
        k5 = r["results"][5]
        speed = f"{r['embed_speed']:.0f} d/s"
        name = r["model"][:44]
        print(f"  {name:<45} {k5['strict_hr']:>7.1%} {k5['strict_mrr']:>8.4f} {k5['relaxed_hr']:>7.1%} {k5['relaxed_mrr']:>8.4f} {speed:>10}")

    # 결과 JSON 저장
    output_path = os.path.join(BASE_DIR, "eval", "model_comparison_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
