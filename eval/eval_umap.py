"""
임베딩 품질 평가: UMAP 시각화
카테고리별/상품별 클러스터 분포 확인
"""

import json
import os
import numpy as np
import chromadb
import umap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DIR = os.path.join(BASE_DIR, "data", "chroma_db")
OUTPUT_DIR = os.path.join(BASE_DIR, "eval", "plots")

# 한글 폰트 설정
font_path = "C:/Windows/Fonts/malgun.ttf"
if os.path.exists(font_path):
    font_manager.fontManager.addfont(font_path)
    plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_collection("insurance_articles")

    print("ChromaDB에서 임베딩 로드 중...")
    all_data = col.get(include=["embeddings", "metadatas"])
    embeddings = np.array(all_data["embeddings"])
    metadatas = all_data["metadatas"]
    print(f"총 {len(embeddings)}개 문서 로드 완료")

    # 주계약만 필터 (특약 포함 시 너무 많아서 시각화가 어려움)
    main_idx = [i for i, m in enumerate(metadatas) if m.get("type") == "주계약"]
    main_embeddings = embeddings[main_idx]
    main_metas = [metadatas[i] for i in main_idx]
    print(f"주계약만 필터: {len(main_embeddings)}개")

    # UMAP 차원 축소
    print("UMAP 차원 축소 중...")
    reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="cosine", random_state=42)
    umap_result = reducer.fit_transform(main_embeddings)
    print("UMAP 완료")

    # ── 1. 카테고리별 시각화 ──
    categories = [m.get("category", "기타") for m in main_metas]
    unique_cats = sorted(set(categories))
    cat_colors = plt.cm.tab10(np.linspace(0, 1, len(unique_cats)))
    cat_color_map = {cat: cat_colors[i] for i, cat in enumerate(unique_cats)}

    fig, ax = plt.subplots(figsize=(14, 10))
    for cat in unique_cats:
        mask = [i for i, c in enumerate(categories) if c == cat]
        ax.scatter(
            umap_result[mask, 0], umap_result[mask, 1],
            c=[cat_color_map[cat]], label=f"{cat} ({len(mask)})",
            s=15, alpha=0.6
        )
    ax.set_title("UMAP: 카테고리별 클러스터 분포 (주계약)", fontsize=14)
    ax.legend(loc="upper right", fontsize=8, markerscale=2)
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")
    plt.tight_layout()
    path1 = os.path.join(OUTPUT_DIR, "umap_category.png")
    plt.savefig(path1, dpi=150)
    plt.close()
    print(f"저장: {path1}")

    # ── 2. 상품별 시각화 ──
    products = [m.get("prodCode", "") for m in main_metas]
    unique_prods = sorted(set(products))
    prod_colors = plt.cm.tab20(np.linspace(0, 1, len(unique_prods)))
    prod_color_map = {p: prod_colors[i] for i, p in enumerate(unique_prods)}

    fig, ax = plt.subplots(figsize=(14, 10))
    for prod in unique_prods:
        mask = [i for i, p in enumerate(products) if p == prod]
        ax.scatter(
            umap_result[mask, 0], umap_result[mask, 1],
            c=[prod_color_map[prod]], label=f"{prod} ({len(mask)})",
            s=15, alpha=0.6
        )
    ax.set_title("UMAP: 상품별 클러스터 분포 (주계약)", fontsize=14)
    ax.legend(loc="upper right", fontsize=7, markerscale=2, ncol=2)
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")
    plt.tight_layout()
    path2 = os.path.join(OUTPUT_DIR, "umap_product.png")
    plt.savefig(path2, dpi=150)
    plt.close()
    print(f"저장: {path2}")

    # ── 3. 전체 (주계약+특약) 타입별 시각화 ──
    print("\n전체 데이터 UMAP 중 (주계약+특약)...")
    reducer2 = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="cosine", random_state=42)
    umap_all = reducer2.fit_transform(embeddings)

    types = [m.get("type", "기타") for m in metadatas]

    fig, ax = plt.subplots(figsize=(14, 10))
    for t in ["주계약", "특약"]:
        mask = [i for i, tp in enumerate(types) if tp == t]
        ax.scatter(
            umap_all[mask, 0], umap_all[mask, 1],
            label=f"{t} ({len(mask)})",
            s=8, alpha=0.4
        )
    ax.set_title("UMAP: 주계약 vs 특약 분포 (전체)", fontsize=14)
    ax.legend(fontsize=10, markerscale=3)
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")
    plt.tight_layout()
    path3 = os.path.join(OUTPUT_DIR, "umap_type.png")
    plt.savefig(path3, dpi=150)
    plt.close()
    print(f"저장: {path3}")

    print("\n시각화 완료!")


if __name__ == "__main__":
    main()
