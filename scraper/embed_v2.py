"""
벡터 임베딩 v2: 청킹 개선 + 임베딩 텍스트 강화 + 모델 비교

개선 사항:
1. 청킹: 너무 긴 조항(>1500자) 분할, 너무 짧은 조항(<50자) 병합
2. 임베딩 텍스트: gap_alerts, 면책/감액, 별표 참조 정보 추가
3. 메타데이터: category, has_exception_clause 등 강화
"""

import json
import os
import re
import glob
import time
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENRICHED_DIR = os.path.join(BASE_DIR, "data", "약관_enriched")
AGENT_DATA_DIR = os.path.join(BASE_DIR, "data", "agent_data")
APPENDIX_DIR = os.path.join(BASE_DIR, "data", "별표_parsed")
CHROMA_V2_DIR = os.path.join(BASE_DIR, "data", "chroma_db_v2")

CHUNK_MAX = 1500  # 최대 청크 크기 (자)
CHUNK_MIN = 50    # 최소 청크 크기 (자)
CHUNK_OVERLAP = 200  # 분할 시 오버랩


def load_agent_data():
    """coverage_rules, gap_alerts 등 로드"""
    coverage_rules = {}
    path = os.path.join(AGENT_DATA_DIR, "coverage_rules.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            coverage_rules = json.load(f)
    return coverage_rules


def split_long_text(text, max_len=CHUNK_MAX, overlap=CHUNK_OVERLAP):
    """긴 텍스트를 의미 단위로 분할 (문단/번호 기준)"""
    if len(text) <= max_len:
        return [text]

    # 1차: 번호 패턴으로 분할 (①②③, 1. 2. 3., 가. 나. 다.)
    split_patterns = [
        r'\n(?=[①②③④⑤⑥⑦⑧⑨⑩])',
        r'\n(?=\d+\.\s)',
        r'\n(?=[가나다라마바사아자차카타파하]\.\s)',
        r'\n\n+',
    ]

    chunks = [text]
    for pattern in split_patterns:
        new_chunks = []
        for chunk in chunks:
            if len(chunk) <= max_len:
                new_chunks.append(chunk)
            else:
                parts = re.split(pattern, chunk)
                current = ""
                for part in parts:
                    if len(current) + len(part) <= max_len:
                        current += part
                    else:
                        if current:
                            new_chunks.append(current)
                        current = part
                if current:
                    new_chunks.append(current)
        chunks = new_chunks

    # 2차: 여전히 큰 청크는 강제 분할 (overlap 포함)
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= max_len:
            final_chunks.append(chunk)
        else:
            for i in range(0, len(chunk), max_len - overlap):
                final_chunks.append(chunk[i:i + max_len])

    return final_chunks


def build_embed_text_v2(section, product, coverage_rules):
    """v2: 검색 최적화 임베딩 텍스트 (gap_alerts, 면책/감액 추가)"""
    parts = []
    prod_code = section.get("_prodCode", "")

    # 상품명
    parts.append(f"상품: {product}")

    # 특약명
    if section.get("특약명"):
        parts.append(f"특약: {section['특약명']}")

    # 관 + 조 + 제목
    parts.append(f"{section['관']} {section['조']} {section.get('title', '')}")

    # summary
    if section.get("summary"):
        parts.append(section["summary"])

    # keywords
    if section.get("keywords"):
        parts.append("키워드: " + ", ".join(section["keywords"]))

    # 카테고리
    if section.get("category"):
        parts.append(f"분류: {section['category']}")

    # 면책/감액 조건 (coverage_rules에서 가져오기)
    if prod_code in coverage_rules:
        rules = coverage_rules[prod_code]

        # 해당 조항과 관련된 gap_alerts 추가
        gap_alerts = rules.get("gap_alerts", {})
        critical = gap_alerts.get("critical", [])
        if critical:
            # 조항 제목과 관련된 critical alert 매칭
            title = section.get("title", "").replace(" ", "")
            relevant_alerts = []
            for alert in critical:
                alert_clean = alert.replace(" ", "")
                # 제목의 핵심 키워드가 alert에 포함되면 관련
                title_words = re.findall(r'[가-힣]{2,}', title)
                for word in title_words:
                    if word in alert_clean:
                        relevant_alerts.append(alert)
                        break
            if relevant_alerts:
                parts.append("주의사항: " + " / ".join(relevant_alerts[:3]))

    # conditions (기존 enrichment)
    if section.get("conditions"):
        parts.append(f"조건: {section['conditions']}")

    # 본문
    text = section.get("text", "")
    if len(text) > CHUNK_MAX:
        text = text[:CHUNK_MAX]
    parts.append(text)

    return "\n".join(parts)


def build_metadata_v2(section, product, prod_code):
    """v2: 강화된 메타데이터"""
    text = section.get("text", "")

    meta = {
        "product": product,
        "prodCode": prod_code,
        "type": section.get("type", ""),
        "관": section.get("관", ""),
        "조": section.get("조", ""),
        "title": section.get("title", ""),
        "category": section.get("category", ""),
        "chunk_index": section.get("_chunk_index", 0),
        "has_exception": bool(re.search(r"다만|불구하고|제외|예외", text)),
        "has_appendix_ref": bool(re.search(r"별표\s*\d+", text)),
        "text_length": len(text),
    }
    if section.get("특약명"):
        meta["특약명"] = section["특약명"]
    if section.get("summary"):
        meta["summary"] = section["summary"]
    if section.get("conditions"):
        meta["conditions"] = section["conditions"]

    return meta


def process_enriched_files(model_name):
    """enriched JSON 파일을 청킹 개선 + 임베딩 강화하여 ChromaDB에 저장"""
    os.makedirs(CHROMA_V2_DIR, exist_ok=True)

    # 데이터 로드
    coverage_rules = load_agent_data()

    # 모델 로드
    print(f"모델 로드 중: {model_name}")
    t0 = time.time()
    model = SentenceTransformer(model_name)
    print(f"모델 로드 완료: {time.time() - t0:.1f}초")

    # ChromaDB 초기화
    client = chromadb.PersistentClient(path=CHROMA_V2_DIR)
    collection_name = f"insurance_v2"
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # enriched JSON 처리
    files = sorted(glob.glob(os.path.join(ENRICHED_DIR, "*.json")))
    total_docs = 0
    total_chunks = 0
    split_count = 0
    merge_count = 0

    for filepath in files:
        filename = os.path.basename(filepath)
        print(f"\n처리 중: {filename}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        product = data["product"]
        prod_code = data["prodCode"]
        sections = data["sections"]

        ids = []
        documents = []
        metadatas = []

        for i, section in enumerate(sections):
            text = section.get("text", "")
            section["_prodCode"] = prod_code

            # 청킹 처리
            if len(text) > CHUNK_MAX:
                # 긴 조항 분할
                chunks = split_long_text(text)
                split_count += 1
                for ci, chunk_text in enumerate(chunks):
                    chunk_section = dict(section)
                    chunk_section["text"] = chunk_text
                    chunk_section["_chunk_index"] = ci

                    doc_id = f"{prod_code}_{section['type']}_{section['조']}_{i}_c{ci}"
                    embed_text = build_embed_text_v2(chunk_section, product, coverage_rules)
                    metadata = build_metadata_v2(chunk_section, product, prod_code)

                    ids.append(doc_id)
                    documents.append(embed_text)
                    metadatas.append(metadata)
                    total_chunks += 1

            elif len(text) < CHUNK_MIN and i + 1 < len(sections):
                # 너무 짧은 조항 — 다음 조항과 병합은 하지 않음 (조항 경계 유지)
                # 대신 제목+summary를 텍스트에 추가하여 의미 보강
                section["_chunk_index"] = 0
                enriched_text = f"{section.get('title', '')} {section.get('summary', '')} {text}"
                section_copy = dict(section)
                section_copy["text"] = enriched_text

                doc_id = f"{prod_code}_{section['type']}_{section['조']}_{i}"
                embed_text = build_embed_text_v2(section_copy, product, coverage_rules)
                metadata = build_metadata_v2(section_copy, product, prod_code)

                ids.append(doc_id)
                documents.append(embed_text)
                metadatas.append(metadata)
                merge_count += 1

            else:
                # 정상 크기
                section["_chunk_index"] = 0
                doc_id = f"{prod_code}_{section['type']}_{section['조']}_{i}"
                embed_text = build_embed_text_v2(section, product, coverage_rules)
                metadata = build_metadata_v2(section, product, prod_code)

                ids.append(doc_id)
                documents.append(embed_text)
                metadatas.append(metadata)

        # 배치 임베딩
        print(f"  {len(documents)}개 청크 임베딩 중...")
        t1 = time.time()
        embeddings = model.encode(
            documents,
            batch_size=32,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        elapsed = time.time() - t1
        print(f"  임베딩 완료: {elapsed:.1f}초 ({len(documents) / elapsed:.1f} docs/sec)")

        # ChromaDB 저장 (배치)
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

    print(f"\n{'='*50}")
    print(f"전체 완료: {total_docs}개 문서")
    print(f"  분할된 조항: {split_count}개")
    print(f"  보강된 짧은 조항: {merge_count}개")
    print(f"  총 청크: {total_docs}개 (기존 5505개)")
    print(f"ChromaDB 경로: {CHROMA_V2_DIR}")

    return collection, model


def test_search(collection, model):
    """간단한 검색 테스트"""
    print("\n=== 검색 테스트 ===")
    test_queries = [
        "암에 걸리면 보험금 얼마 받아?",
        "입원하면 입원비 나와?",
        "보험 해지하면 환급금 얼마야?",
        "갑상선암도 보장되나요?",
        "보험 들었다가 취소하고 싶어",
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
            exc = "⚠" if meta.get("has_exception") else ""
            print(
                f"  {j + 1}. [{meta['prodCode']}] {meta['조']} {meta.get('title', '')[:35]} {exc}"
            )


if __name__ == "__main__":
    MODEL_NAME = "dragonkue/BGE-m3-ko"
    collection, model = process_enriched_files(MODEL_NAME)
    test_search(collection, model)
