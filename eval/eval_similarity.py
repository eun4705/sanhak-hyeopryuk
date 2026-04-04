"""
임베딩 품질 평가: Cosine Similarity 분포 분석
관련 쌍 vs 비관련 쌍의 유사도 분리도 확인
"""

import json
import os
import numpy as np
import chromadb
from sentence_transformers import SentenceTransformer
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DIR = os.path.join(BASE_DIR, "data", "chroma_db")
GOLDEN_PATH = os.path.join(BASE_DIR, "eval", "golden_set.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "eval", "plots")
MODEL_NAME = "dragonkue/BGE-m3-ko"

font_path = "C:/Windows/Fonts/malgun.ttf"
if os.path.exists(font_path):
    font_manager.fontManager.addfont(font_path)
    plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False


def cosine_sim(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"모델 로드 중: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_collection("insurance_articles")

    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        golden = [q for q in json.load(f) if q["relevant_ids"]]

    # 쿼리 임베딩
    queries = [q["query"] for q in golden]
    print(f"{len(queries)}개 쿼리 임베딩 중...")
    query_embs = model.encode(queries, normalize_embeddings=True)

    # 정답 문서 임베딩 가져오기
    all_relevant_ids = list(set(rid for q in golden for rid in q["relevant_ids"]))
    relevant_data = col.get(ids=all_relevant_ids, include=["embeddings"])
    id_to_emb = {did: emb for did, emb in zip(relevant_data["ids"], relevant_data["embeddings"])}

    # 랜덤 비관련 문서 임베딩 가져오기
    all_ids = col.get(include=[])["ids"]
    relevant_set = set(all_relevant_ids)
    non_relevant_ids = [i for i in all_ids if i not in relevant_set]
    np.random.seed(42)
    sample_non_relevant = np.random.choice(non_relevant_ids, size=min(500, len(non_relevant_ids)), replace=False)
    non_rel_data = col.get(ids=sample_non_relevant.tolist(), include=["embeddings"])
    non_rel_embs = np.array(non_rel_data["embeddings"])

    # ── 관련 쌍 유사도 ──
    related_sims = []
    for i, q in enumerate(golden):
        for rid in q["relevant_ids"]:
            if rid in id_to_emb:
                sim = cosine_sim(query_embs[i], id_to_emb[rid])
                related_sims.append(sim)

    # ── 비관련 쌍 유사도 ──
    unrelated_sims = []
    for i in range(len(query_embs)):
        # 각 쿼리에 대해 랜덤 비관련 문서 10개와 유사도 계산
        sample_idx = np.random.choice(len(non_rel_embs), size=10, replace=False)
        for j in sample_idx:
            sim = cosine_sim(query_embs[i], non_rel_embs[j])
            unrelated_sims.append(sim)

    related_sims = np.array(related_sims)
    unrelated_sims = np.array(unrelated_sims)

    print(f"\n관련 쌍 유사도:   평균={related_sims.mean():.4f}, 중앙값={np.median(related_sims):.4f}, 표준편차={related_sims.std():.4f}")
    print(f"비관련 쌍 유사도: 평균={unrelated_sims.mean():.4f}, 중앙값={np.median(unrelated_sims):.4f}, 표준편차={unrelated_sims.std():.4f}")
    print(f"분리도 (평균 차이): {related_sims.mean() - unrelated_sims.mean():.4f}")

    # ── 히스토그램 ──
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(unrelated_sims, bins=50, alpha=0.6, label=f"비관련 쌍 (n={len(unrelated_sims)}, avg={unrelated_sims.mean():.3f})", color="steelblue")
    ax.hist(related_sims, bins=30, alpha=0.7, label=f"관련 쌍 (n={len(related_sims)}, avg={related_sims.mean():.3f})", color="coral")
    ax.axvline(related_sims.mean(), color="red", linestyle="--", linewidth=1, label=f"관련 평균: {related_sims.mean():.3f}")
    ax.axvline(unrelated_sims.mean(), color="blue", linestyle="--", linewidth=1, label=f"비관련 평균: {unrelated_sims.mean():.3f}")
    ax.set_xlabel("Cosine Similarity", fontsize=12)
    ax.set_ylabel("빈도", fontsize=12)
    ax.set_title("관련 쌍 vs 비관련 쌍 Cosine Similarity 분포", fontsize=14)
    ax.legend(fontsize=9)
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "similarity_distribution.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"\n저장: {path}")

    # ── 쿼리별 관련 유사도 bar chart ──
    fig, ax = plt.subplots(figsize=(14, 6))
    query_sims = []
    query_labels = []
    for i, q in enumerate(golden):
        sims = []
        for rid in q["relevant_ids"]:
            if rid in id_to_emb:
                sims.append(cosine_sim(query_embs[i], id_to_emb[rid]))
        if sims:
            query_sims.append(max(sims))
            label = q["query"][:15] + "..." if len(q["query"]) > 15 else q["query"]
            query_labels.append(f"Q{q['id']}")

    colors = ["coral" if s < 0.5 else "gold" if s < 0.7 else "mediumseagreen" for s in query_sims]
    bars = ax.bar(range(len(query_sims)), query_sims, color=colors, edgecolor="gray", linewidth=0.5)
    ax.set_xticks(range(len(query_labels)))
    ax.set_xticklabels(query_labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Max Cosine Similarity", fontsize=11)
    ax.set_title("쿼리별 정답 문서와의 최대 유사도", fontsize=13)
    ax.axhline(0.5, color="red", linestyle=":", alpha=0.5, label="0.5 기준선")
    ax.axhline(0.7, color="orange", linestyle=":", alpha=0.5, label="0.7 기준선")
    ax.legend(fontsize=9)
    plt.tight_layout()
    path2 = os.path.join(OUTPUT_DIR, "query_similarity_bars.png")
    plt.savefig(path2, dpi=150)
    plt.close()
    print(f"저장: {path2}")


if __name__ == "__main__":
    main()
