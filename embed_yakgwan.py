"""
약관 enriched JSON → BGE-m3-ko 임베딩 → ChromaDB 저장

입력: data/약관_enriched/*.json
출력: data/chroma_db/ (ChromaDB 영구 저장소)
"""

import json
import os
import glob
import time
from sentence_transformers import SentenceTransformer
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "data", "약관_enriched")
CHROMA_DIR = os.path.join(BASE_DIR, "data", "chroma_db")

MODEL_NAME = "dragonkue/BGE-m3-ko"
COLLECTION_NAME = "insurance_articles"


def build_embed_text(section: dict, product: str) -> str:
    """검색 최적화된 임베딩용 텍스트 생성.
    summary + keywords + title + text 앞부분을 조합하여
    벡터 검색과 키워드 검색 모두에 효과적인 텍스트를 만듦."""
    parts = []

    # 상품명
    parts.append(f"상품: {product}")

    # 특약명 (있으면)
    if section.get("특약명"):
        parts.append(f"특약: {section['특약명']}")

    # 관 + 조 + 제목
    parts.append(f"{section['관']} {section['조']} {section.get('title', '')}")

    # summary (가장 중요한 검색 단서)
    if section.get("summary"):
        parts.append(section["summary"])

    # keywords
    if section.get("keywords"):
        parts.append("키워드: " + ", ".join(section["keywords"]))

    # 본문 (앞부분, 너무 길면 잘라냄 - BGE-m3는 8192 토큰이지만 효율을 위해)
    text = section.get("text", "")
    if len(text) > 1500:
        text = text[:1500]
    parts.append(text)

    return "\n".join(parts)


def build_metadata(section: dict, product: str, prod_code: str) -> dict:
    """ChromaDB 메타데이터 (검색 필터용)"""
    meta = {
        "product": product,
        "prodCode": prod_code,
        "type": section.get("type", ""),
        "관": section.get("관", ""),
        "조": section.get("조", ""),
        "title": section.get("title", ""),
        "category": section.get("category", ""),
    }
    if section.get("특약명"):
        meta["특약명"] = section["특약명"]
    if section.get("summary"):
        meta["summary"] = section["summary"]
    if section.get("conditions"):
        meta["conditions"] = section["conditions"]
    return meta


def main():
    os.makedirs(CHROMA_DIR, exist_ok=True)

    # 모델 로드
    print(f"모델 로드 중: {MODEL_NAME}")
    t0 = time.time()
    model = SentenceTransformer(MODEL_NAME)
    print(f"모델 로드 완료: {time.time() - t0:.1f}초")

    # ChromaDB 초기화
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    # 기존 컬렉션 있으면 삭제 후 재생성
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    # enriched JSON 파일 로드
    files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.json")))
    if not files:
        print(f"입력 파일 없음: {INPUT_DIR}")
        return

    total_docs = 0
    for filepath in files:
        filename = os.path.basename(filepath)
        print(f"\n처리 중: {filename}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        product = data["product"]
        prod_code = data["prodCode"]
        sections = data["sections"]

        # 임베딩용 텍스트 생성
        ids = []
        documents = []
        metadatas = []

        for i, section in enumerate(sections):
            doc_id = f"{prod_code}_{section['type']}_{section['조']}_{i}"
            embed_text = build_embed_text(section, product)
            metadata = build_metadata(section, product, prod_code)

            ids.append(doc_id)
            documents.append(embed_text)
            metadatas.append(metadata)

        # 배치 임베딩
        print(f"  {len(documents)}개 조항 임베딩 중...")
        t1 = time.time()
        embeddings = model.encode(
            documents,
            batch_size=32,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        elapsed = time.time() - t1
        print(f"  임베딩 완료: {elapsed:.1f}초 ({len(documents)/elapsed:.1f} docs/sec)")

        # ChromaDB에 저장 (배치 단위)
        batch_size = 500
        for start in range(0, len(ids), batch_size):
            end = min(start + batch_size, len(ids))
            collection.add(
                ids=ids[start:end],
                embeddings=embeddings[start:end].tolist(),
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

        total_docs += len(documents)
        print(f"  → {prod_code}: {len(documents)}개 저장 완료")

    print(f"\n전체 완료: {total_docs}개 문서 임베딩 및 ChromaDB 저장")
    print(f"ChromaDB 경로: {CHROMA_DIR}")

    # 간단한 검색 테스트
    print("\n=== 검색 테스트 ===")
    test_queries = [
        "암에 걸리면 보험금 얼마 받아?",
        "입원하면 입원비 나와?",
        "보험 해지하면 환급금 얼마야?",
    ]
    for q in test_queries:
        results = collection.query(
            query_embeddings=model.encode([q], normalize_embeddings=True).tolist(),
            n_results=3,
        )
        print(f"\nQ: {q}")
        for j, (doc_id, meta) in enumerate(
            zip(results["ids"][0], results["metadatas"][0])
        ):
            print(
                f"  {j+1}. [{meta['prodCode']}] {meta['관']} {meta['조']} {meta.get('title','')} - {meta.get('summary','')[:50]}"
            )


if __name__ == "__main__":
    main()
