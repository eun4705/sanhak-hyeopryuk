"""
9개 임베딩 모델로 각각 ChromaDB 저장
평가는 나중에 별도로.
"""

import json
import os
import sys
import glob
import time
import traceback
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENRICHED_DIR = os.path.join(BASE_DIR, "data", "약관_enriched")
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


def load_sections():
    """enriched JSON에서 모든 조항 로드"""
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


def safe_model_name(model_name):
    return model_name.replace("/", "_").replace("-", "_")


def embed_and_store(model_name, sections):
    """단일 모델로 임베딩 → ChromaDB 저장"""
    safe_name = safe_model_name(model_name)
    chroma_dir = os.path.join(CHROMA_BASE, f"chroma_{safe_name}")

    # 이미 완료된 모델은 스킵
    if os.path.exists(chroma_dir):
        try:
            client = chromadb.PersistentClient(path=chroma_dir)
            col = client.get_collection("insurance_articles")
            if col.count() >= len(sections) * 0.9:  # 90% 이상이면 완료로 간주
                print(f"\n[SKIP] {model_name} — 이미 완료 ({col.count()}개)")
                return {"model": model_name, "status": "skipped", "count": col.count()}
        except:
            pass

    print(f"\n{'='*60}")
    print(f"  모델: {model_name}")
    print(f"{'='*60}")

    # 1. 모델 로드
    try:
        print(f"  모델 로드 중...")
        t0 = time.time()
        model = SentenceTransformer(model_name, trust_remote_code=True)
        load_time = time.time() - t0
        print(f"  모델 로드: {load_time:.1f}초")
    except Exception as e:
        print(f"  [ERROR] 모델 로드 실패: {e}")
        traceback.print_exc()
        return {"model": model_name, "status": "failed", "error": str(e)}

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
        speed = len(sections) / embed_time
        print(f"  임베딩 완료: {embed_time:.1f}초 ({speed:.1f} docs/sec)")
    except Exception as e:
        print(f"  [ERROR] 임베딩 실패: {e}")
        traceback.print_exc()
        return {"model": model_name, "status": "failed", "error": str(e)}

    # 3. ChromaDB 저장
    try:
        os.makedirs(chroma_dir, exist_ok=True)
        client = chromadb.PersistentClient(path=chroma_dir)
        try:
            client.delete_collection("insurance_articles")
        except:
            pass
        collection = client.create_collection(
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
    except Exception as e:
        print(f"  [ERROR] ChromaDB 저장 실패: {e}")
        traceback.print_exc()
        return {"model": model_name, "status": "failed", "error": str(e)}

    # 모델 메모리 해제
    del model
    del doc_embeddings
    import gc
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except:
        pass

    return {
        "model": model_name,
        "status": "completed",
        "count": collection.count(),
        "load_time": load_time,
        "embed_time": embed_time,
        "embed_speed": speed,
        "chroma_dir": chroma_dir,
    }


def main():
    print("데이터 로드 중...")
    sections = load_sections()
    print(f"조항: {len(sections)}개\n")

    results = []
    for model_name in MODELS:
        try:
            result = embed_and_store(model_name, sections)
            results.append(result)
        except Exception as e:
            print(f"\n[FATAL] {model_name}: {e}")
            traceback.print_exc()
            results.append({"model": model_name, "status": "fatal", "error": str(e)})

    # 요약
    print(f"\n\n{'#'*60}")
    print(f"  임베딩 저장 결과 요약")
    print(f"{'#'*60}")
    for r in results:
        status = r["status"]
        if status == "completed":
            print(f"  ✅ {r['model']}: {r['count']}개, {r['embed_time']:.0f}초 ({r['embed_speed']:.0f} d/s)")
        elif status == "skipped":
            print(f"  ⏭️  {r['model']}: 이미 완료 ({r['count']}개)")
        else:
            print(f"  ❌ {r['model']}: {r.get('error', 'unknown')[:60]}")

    # 결과 저장
    output_path = os.path.join(BASE_DIR, "eval", "embed_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
