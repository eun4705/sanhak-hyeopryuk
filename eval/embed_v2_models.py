"""
v2 청킹 + 텍스트 강화 기준으로 상위 3개 모델 재임베딩
"""

import json
import os
import sys
import glob
import time
import re
import gc
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scraper"))
from embed_v2 import load_agent_data, split_long_text, build_embed_text_v2, build_metadata_v2, ENRICHED_DIR, CHUNK_MAX

MODELS = [
    "Qwen/Qwen3-Embedding-0.6B",
    "Qwen/Qwen3-Embedding-4B",
    "nlpai-lab/KURE-v1",
]


def load_v2_sections():
    """v2 청킹 + 텍스트 강화 적용된 섹션 로드"""
    coverage_rules = load_agent_data()
    sections = []

    for filepath in sorted(glob.glob(os.path.join(ENRICHED_DIR, "*.json"))):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        product = data["product"]
        prod_code = data["prodCode"]

        for i, sec in enumerate(data["sections"]):
            text = sec.get("text", "")
            sec["_prodCode"] = prod_code

            if len(text) > CHUNK_MAX:
                chunks = split_long_text(text)
                for ci, chunk_text in enumerate(chunks):
                    chunk_sec = dict(sec)
                    chunk_sec["text"] = chunk_text
                    chunk_sec["_chunk_index"] = ci
                    doc_id = f"{prod_code}_{sec['type']}_{sec['조']}_{i}_c{ci}"
                    embed_text = build_embed_text_v2(chunk_sec, product, coverage_rules)
                    metadata = build_metadata_v2(chunk_sec, product, prod_code)
                    sections.append({"id": doc_id, "text": embed_text, "metadata": metadata})

            elif len(text) < 50:
                sec["_chunk_index"] = 0
                enriched_text = f"{sec.get('title', '')} {sec.get('summary', '')} {text}"
                sec_copy = dict(sec)
                sec_copy["text"] = enriched_text
                doc_id = f"{prod_code}_{sec['type']}_{sec['조']}_{i}"
                embed_text = build_embed_text_v2(sec_copy, product, coverage_rules)
                metadata = build_metadata_v2(sec_copy, product, prod_code)
                sections.append({"id": doc_id, "text": embed_text, "metadata": metadata})

            else:
                sec["_chunk_index"] = 0
                doc_id = f"{prod_code}_{sec['type']}_{sec['조']}_{i}"
                embed_text = build_embed_text_v2(sec, product, coverage_rules)
                metadata = build_metadata_v2(sec, product, prod_code)
                sections.append({"id": doc_id, "text": embed_text, "metadata": metadata})

    return sections


def embed_and_store(model_name, sections):
    safe_name = model_name.replace("/", "_").replace("-", "_")
    chroma_dir = os.path.join(BASE_DIR, "data", f"chroma_v2_{safe_name}")

    if os.path.exists(chroma_dir):
        try:
            c = chromadb.PersistentClient(path=chroma_dir)
            col = c.get_collection("insurance_articles")
            if col.count() >= len(sections) * 0.9:
                print(f"  [SKIP] 이미 완료 ({col.count()}개)")
                return chroma_dir
        except:
            pass

    print(f"\n{'='*60}")
    print(f"  모델: {model_name} (v2 청킹)")
    print(f"{'='*60}")

    model = SentenceTransformer(model_name, trust_remote_code=True)

    doc_texts = [s["text"] for s in sections]
    print(f"  {len(doc_texts)}개 청크 임베딩 중...")
    t1 = time.time()
    doc_embs = model.encode(doc_texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True)
    print(f"  임베딩: {time.time()-t1:.1f}초")

    os.makedirs(chroma_dir, exist_ok=True)
    client = chromadb.PersistentClient(path=chroma_dir)
    try:
        client.delete_collection("insurance_articles")
    except:
        pass
    col = client.create_collection(name="insurance_articles", metadata={"hnsw:space": "cosine"})

    batch_size = 500
    for start in range(0, len(sections), batch_size):
        end = min(start + batch_size, len(sections))
        col.add(
            ids=[s["id"] for s in sections[start:end]],
            embeddings=doc_embs[start:end].tolist(),
            documents=[s["text"] for s in sections[start:end]],
            metadatas=[s["metadata"] for s in sections[start:end]],
        )

    print(f"  저장: {chroma_dir} ({col.count()}개)")

    del model, doc_embs
    gc.collect()
    try:
        import torch; torch.cuda.empty_cache()
    except:
        pass

    return chroma_dir


def evaluate(model_name, chroma_dir, golden):
    print(f"\n  평가: {model_name}")
    model = SentenceTransformer(model_name, trust_remote_code=True)
    queries = [q["query"] for q in golden]
    query_embs = model.encode(queries, normalize_embeddings=True)

    client = chromadb.PersistentClient(path=chroma_dir)
    col = client.get_collection("insurance_articles")

    for label, use_filter in [("필터없음", False), ("필터적용", True)]:
        print(f"\n  [{label}]")
        for k in [1, 3, 5, 10]:
            hits = 0
            rrs = []
            for i, q in enumerate(golden):
                relevant = set(q["relevant_ids"])
                prod_code = q.get("product", "")
                if use_filter and prod_code:
                    search = col.query(query_embeddings=[query_embs[i].tolist()], n_results=k, where={"prodCode": prod_code})
                else:
                    search = col.query(query_embeddings=[query_embs[i].tolist()], n_results=k)
                retrieved = search["ids"][0][:k]
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
            print(f"    HR@{k}: {hits/n:.1%} ({hits}/{n})  MRR: {sum(rrs)/n:.4f}")

    del model, query_embs
    gc.collect()
    try:
        import torch; torch.cuda.empty_cache()
    except:
        pass


def main():
    print("v2 섹션 로드 중...")
    sections = load_v2_sections()
    print(f"v2 청크: {len(sections)}개\n")

    with open(os.path.join(BASE_DIR, "eval", "golden_set_v3.json"), "r", encoding="utf-8") as f:
        golden = json.load(f)
    print(f"Golden Set: {len(golden)}개\n")

    for model_name in MODELS:
        chroma_dir = embed_and_store(model_name, sections)
        evaluate(model_name, chroma_dir, golden)


if __name__ == "__main__":
    main()
