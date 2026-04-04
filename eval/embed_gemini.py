"""
Google Gemini Embedding 모델로 임베딩 + 평가
gemini-embedding-001, gemini-embedding-2-preview 둘 다
"""

import json
import os
import glob
import time
import numpy as np
from google import genai
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENRICHED_DIR = os.path.join(BASE_DIR, "data", "약관_enriched")
GOLDEN_PATH = os.path.join(BASE_DIR, "eval", "golden_set_v3.json")
API_KEY = "AIzaSyDTvi9U2-jFNEVGuSwdPT8XJDxrvl6pHgs"

MODELS = [
    "gemini-embedding-001",
    "gemini-embedding-2-preview",
]


def load_sections():
    sections = []
    for filepath in sorted(glob.glob(os.path.join(ENRICHED_DIR, "*.json"))):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        product = data["product"]
        prod_code = data["prodCode"]
        for i, sec in enumerate(data["sections"]):
            doc_id = f"{prod_code}_{sec['type']}_{sec['조']}_{i}"
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


def embed_batch_gemini(client, model_name, texts, batch_size=20):
    """Gemini API로 배치 임베딩 (rate limit: 분당 100 요청)"""
    all_embeddings = []
    for start in range(0, len(texts), batch_size):
        end = min(start + batch_size, len(texts))
        batch = texts[start:end]

        for attempt in range(5):
            try:
                result = client.models.embed_content(
                    model=model_name,
                    contents=batch,
                )
                for emb in result.embeddings:
                    all_embeddings.append(emb.values)
                break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = 10 * (attempt + 1)
                    print(f"    Rate limit, {wait}초 대기...")
                    time.sleep(wait)
                else:
                    raise

        if start % 200 == 0 and start > 0:
            print(f"    {start}/{len(texts)} 완료...")

        # 분당 100 요청 제한 → 20개 배치 * 5 = 100, 매 배치 후 대기
        if end < len(texts):
            time.sleep(1.5)

    return np.array(all_embeddings)


def embed_and_evaluate(model_name, sections, golden):
    safe_name = model_name.replace("-", "_").replace("/", "_")
    chroma_dir = os.path.join(BASE_DIR, "data", f"chroma_{safe_name}")

    print(f"\n{'='*60}")
    print(f"  모델: {model_name}")
    print(f"{'='*60}")

    client = genai.Client(api_key=API_KEY)

    # 이미 완료된 경우 스킵
    if os.path.exists(chroma_dir):
        try:
            c = chromadb.PersistentClient(path=chroma_dir)
            col = c.get_collection("insurance_articles")
            if col.count() >= len(sections) * 0.9:
                print(f"  [SKIP] 이미 완료 ({col.count()}개)")
                # 평가만 수행
                queries = [q["query"] for q in golden]
                print(f"  쿼리 {len(queries)}개 임베딩 중...")
                query_embs = embed_batch_gemini(client, model_name, queries)
                return evaluate(col, query_embs, golden, model_name, chroma_dir)
        except:
            pass

    # 1. 문서 임베딩
    doc_texts = [s["text"] for s in sections]
    print(f"  {len(doc_texts)}개 문서 임베딩 중...")
    t1 = time.time()
    doc_embeddings = embed_batch_gemini(client, model_name, doc_texts)
    embed_time = time.time() - t1
    print(f"  임베딩 완료: {embed_time:.1f}초 ({len(doc_texts)/embed_time:.1f} docs/sec)")

    # 2. ChromaDB 저장
    os.makedirs(chroma_dir, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=chroma_dir)
    try:
        chroma_client.delete_collection("insurance_articles")
    except:
        pass
    collection = chroma_client.create_collection(
        name="insurance_articles",
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
    print(f"  ChromaDB 저장: {chroma_dir} ({collection.count()}개)")

    # 3. 쿼리 임베딩 + 평가
    queries = [q["query"] for q in golden]
    print(f"  쿼리 {len(queries)}개 임베딩 중...")
    query_embs = embed_batch_gemini(client, model_name, queries)

    return evaluate(collection, query_embs, golden, model_name, chroma_dir)


def evaluate(collection, query_embs, golden, model_name, chroma_dir):
    k_values = [1, 3, 5, 10]
    results = {}

    for k in k_values:
        search_results = collection.query(
            query_embeddings=query_embs.tolist(),
            n_results=k,
        )
        hits = 0
        rrs = []
        for i, q in enumerate(golden):
            relevant = set(q["relevant_ids"])
            retrieved = search_results["ids"][i][:k]
            hit = any(r in relevant for r in retrieved)
            if hit:
                hits += 1
            rr = 0
            for rank, r in enumerate(retrieved, 1):
                if r in relevant:
                    rr = 1.0 / rank
                    break
            rrs.append(rr)
        n = len(golden)
        results[k] = {"hit_rate": hits / n, "mrr": sum(rrs) / n, "hits": hits}

    print(f"\n  {'K':>3} | {'HR':>8} | {'MRR':>8}")
    print(f"  {'-'*3}-+-{'-'*8}-+-{'-'*8}")
    for k in k_values:
        r = results[k]
        print(f"  {k:>3} | {r['hit_rate']:>7.1%} | {r['mrr']:>8.4f}")

    return {"model": model_name, "results": results, "chroma_dir": chroma_dir}


def main():
    print("데이터 로드 중...")
    sections = load_sections()
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        golden = json.load(f)
    print(f"조항: {len(sections)}개, 쿼리: {len(golden)}개\n")

    all_results = []
    for model_name in MODELS:
        try:
            result = embed_and_evaluate(model_name, sections, golden)
            if result:
                all_results.append(result)
        except Exception as e:
            print(f"  [ERROR] {model_name}: {e}")
            import traceback
            traceback.print_exc()

    # 요약
    print(f"\n\n{'#'*60}")
    print(f"  Gemini Embedding 결과")
    print(f"{'#'*60}")
    for r in all_results:
        r5 = r["results"][5]
        print(f"  {r['model']}: HR@5={r5['hit_rate']:.1%}  MRR={r5['mrr']:.4f}")


if __name__ == "__main__":
    main()
