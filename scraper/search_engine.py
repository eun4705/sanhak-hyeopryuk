"""
통합 검색 엔진: 쿼리 확장 → Hybrid Search (벡터 + BM25) → Reranker

사용법:
    engine = SearchEngine()
    results = engine.search("보험 해지하면 돈 돌려받을 수 있어?", top_k=5)
"""

import json
import os
import re
import glob
import numpy as np
from collections import defaultdict
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer, CrossEncoder
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DIR = os.path.join(BASE_DIR, "data", "chroma_v2_Qwen_Qwen3_Embedding_0.6B")
ENRICHED_DIR = os.path.join(BASE_DIR, "data", "약관_enriched")

EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
RERANKER_MODEL = "Dongjin-kr/ko-reranker"

# ── 1. 동의어 사전 (구어체 → 약관 용어) ──
SYNONYM_MAP = {
    # 계약 관련
    "취소": ["청약의 철회", "청약철회", "계약 해지"],
    "해지": ["계약의 해지", "해약", "계약 해지", "임의해지"],
    "환불": ["해약환급금", "환급금"],
    "환불금": ["해약환급금"],
    "돌려받": ["해약환급금", "환급금"],
    "취소하고 싶": ["청약의 철회", "청약철회"],
    # 보험금 관련
    "보험금 신청": ["보험금 청구", "보험금등의 청구"],
    "클레임": ["보험금 청구"],
    "돈 받": ["보험금 지급", "보험금의 지급사유"],
    "얼마 받": ["보험금의 지급사유", "보험금 지급"],
    "얼마나 나": ["보험금의 지급사유", "보험금 지급"],
    # 보험료 관련
    "보험료 내": ["보험료 납입", "보험료의 납입"],
    "보험료 납부": ["보험료 납입"],
    "보험료 지불": ["보험료 납입"],
    "안 내면": ["납입최고", "보험료의 납입이 연체", "계약의 해지"],
    "미납": ["납입최고", "보험료의 납입이 연체"],
    # 대상자 관련
    "보험 대상자": ["피보험자"],
    "가입자": ["계약자", "보험계약자"],
    # 사고/재해
    "사고": ["재해", "상해"],
    "죽으면": ["사망", "사망보험금"],
    "죽었을 때": ["사망", "사망보험금"],
    # 질병 관련
    "암": ["암 진단", "암의 정의", "진단확정"],
    "치매": ["치매상태", "치매보장", "경도치매", "중증치매"],
    # 계약 변경
    "바꾸": ["변경", "계약내용의 변경"],
    "변경하": ["계약내용의 변경"],
    # 기타
    "대출": ["보험계약대출", "보험계약 대출"],
    "빌리": ["보험계약대출"],
    "분쟁": ["분쟁의 조정", "관할법원"],
    "소송": ["관할법원", "분쟁의 조정"],
    "나이": ["보험나이"],
    "갱신": ["계약의 갱신", "특약의 갱신"],
    "무효": ["계약의 무효"],
    "사기": ["사기에 의한 계약"],
    "올라": ["갱신", "보험료 인상"],
}


def expand_query(query: str) -> str:
    """구어체 쿼리에 약관 용어를 추가하여 확장"""
    additions = set()
    for keyword, terms in SYNONYM_MAP.items():
        if keyword in query:
            additions.update(terms)

    if not additions:
        return query

    expanded = query + " " + " ".join(additions)
    return expanded


def tokenize_korean(text: str) -> list[str]:
    """간단한 한국어 토크나이저 (공백 + 2~4글자 n-gram)"""
    # 공백 기반 토큰
    text_clean = re.sub(r"[^\w가-힣]", " ", text)
    words = text_clean.split()

    # 2~4글자 한글 n-gram 추가 (형태소 분석기 없이 부분 매칭)
    ngrams = []
    for word in words:
        hangul = re.findall(r"[가-힣]+", word)
        for h in hangul:
            if len(h) >= 2:
                ngrams.append(h)
                # 긴 단어는 2-gram으로도 추가
                if len(h) >= 4:
                    for i in range(len(h) - 1):
                        ngrams.append(h[i : i + 2])

    return words + ngrams


class SearchEngine:
    def __init__(self, verbose=True):
        self.verbose = verbose

        if verbose:
            print(f"임베딩 모델 로드 중: {EMBED_MODEL}")
        self.embed_model = SentenceTransformer(EMBED_MODEL)

        if verbose:
            print(f"Reranker 모델 로드 중: {RERANKER_MODEL}")
        self.reranker = CrossEncoder(RERANKER_MODEL)

        # ChromaDB
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        self.collection = client.get_collection("insurance_articles")

        # BM25 인덱스 구축
        self._build_bm25_index()

        if verbose:
            print(f"검색 엔진 준비 완료 (문서: {len(self.doc_ids)}개)")

    def _build_bm25_index(self):
        """전체 문서로 BM25 인덱스 구축"""
        if self.verbose:
            print("BM25 인덱스 구축 중...")

        all_data = self.collection.get(include=["documents", "metadatas"])
        self.doc_ids = all_data["ids"]
        self.doc_texts = all_data["documents"]
        self.doc_metas = all_data["metadatas"]

        # ID → index 매핑
        self.id_to_idx = {did: i for i, did in enumerate(self.doc_ids)}

        # 토크나이즈 후 BM25 구축
        tokenized = [tokenize_korean(doc) for doc in self.doc_texts]
        self.bm25 = BM25Okapi(tokenized)

    def search(
        self,
        query: str,
        top_k: int = 5,
        vector_weight: float = 0.5,
        bm25_weight: float = 0.5,
        candidate_k: int = 30,
        use_reranker: bool = True,
        use_expansion: bool = True,
        text_limit: int = 800,
    ) -> list[dict]:
        """
        통합 검색: 쿼리확장 → Hybrid(벡터+BM25) → Reranker

        Args:
            query: 검색 쿼리
            top_k: 최종 반환 수
            vector_weight: 벡터 검색 가중치
            bm25_weight: BM25 가중치
            candidate_k: 1차 후보 수 (reranker 입력)
            use_reranker: reranker 사용 여부
            use_expansion: 쿼리 확장 사용 여부
        """
        # 1. 쿼리 확장 (BM25 전용)
        if use_expansion:
            expanded = expand_query(query)
        else:
            expanded = query

        # 2-A. 벡터 검색 (원본 쿼리로 — 구어체 혼합 방지)
        query_emb = self.embed_model.encode(
            [query], normalize_embeddings=True
        )
        vector_results = self.collection.query(
            query_embeddings=query_emb.tolist(),
            n_results=candidate_k,
        )
        vector_ids = vector_results["ids"][0]
        vector_distances = vector_results["distances"][0]

        # cosine similarity로 변환 (chroma는 cosine distance = 1 - similarity)
        vector_scores = {}
        for did, dist in zip(vector_ids, vector_distances):
            vector_scores[did] = 1 - dist  # cosine similarity

        # 2-B. BM25 검색 (확장 쿼리로 — 약관 용어 키워드 매칭)
        bm25_tokens = tokenize_korean(expanded)
        bm25_raw_scores = self.bm25.get_scores(bm25_tokens)
        bm25_top_idx = np.argsort(bm25_raw_scores)[::-1][:candidate_k]

        bm25_scores = {}
        for idx in bm25_top_idx:
            if bm25_raw_scores[idx] > 0:
                bm25_scores[self.doc_ids[idx]] = bm25_raw_scores[idx]

        # 3. 점수 정규화 후 결합
        all_candidate_ids = set(vector_scores.keys()) | set(bm25_scores.keys())

        # Min-Max 정규화
        if vector_scores:
            v_min, v_max = min(vector_scores.values()), max(vector_scores.values())
            v_range = v_max - v_min if v_max != v_min else 1
        if bm25_scores:
            b_min, b_max = min(bm25_scores.values()), max(bm25_scores.values())
            b_range = b_max - b_min if b_max != b_min else 1

        hybrid_scores = {}
        for did in all_candidate_ids:
            v_score = 0
            if did in vector_scores and vector_scores:
                v_score = (vector_scores[did] - v_min) / v_range

            b_score = 0
            if did in bm25_scores and bm25_scores:
                b_score = (bm25_scores[did] - b_min) / b_range

            hybrid_scores[did] = vector_weight * v_score + bm25_weight * b_score

        # 상위 candidate_k개 선택
        sorted_candidates = sorted(
            hybrid_scores.items(), key=lambda x: x[1], reverse=True
        )[:candidate_k]

        # 4. Reranker
        if use_reranker and sorted_candidates:
            candidate_ids = [c[0] for c in sorted_candidates]
            candidate_texts = []
            for did in candidate_ids:
                idx = self.id_to_idx[did]
                candidate_texts.append(self.doc_texts[idx])

            # cross-encoder 입력: (query, document) 쌍
            pairs = [[query, text] for text in candidate_texts]
            rerank_scores = self.reranker.predict(pairs)

            # reranker 점수로 재정렬
            reranked = sorted(
                zip(candidate_ids, rerank_scores),
                key=lambda x: x[1],
                reverse=True,
            )
            final_ids = [r[0] for r in reranked[:top_k]]
            final_scores = [float(r[1]) for r in reranked[:top_k]]
        else:
            final_ids = [c[0] for c in sorted_candidates[:top_k]]
            final_scores = [c[1] for c in sorted_candidates[:top_k]]

        # 5. 결과 구성
        results = []
        for did, score in zip(final_ids, final_scores):
            idx = self.id_to_idx[did]
            results.append(
                {
                    "id": did,
                    "score": score,
                    "metadata": self.doc_metas[idx],
                    "text": self.doc_texts[idx][:text_limit],
                }
            )

        return results


if __name__ == "__main__":
    engine = SearchEngine()

    test_queries = [
        "보험 해지하면 돈 돌려받을 수 있어?",
        "보험 들었다가 취소하고 싶어",
        "암에 걸리면 보험금 얼마 받아?",
        "보험료 안 내면 어떻게 돼?",
        "간편심사형이랑 일반심사형 차이가 뭐야?",
    ]

    for q in test_queries:
        print(f"\n{'='*60}")
        print(f"Q: {q}")
        expanded = expand_query(q)
        if expanded != q:
            print(f"확장: {expanded[:80]}...")
        results = engine.search(q, top_k=5)
        for i, r in enumerate(results):
            meta = r["metadata"]
            print(
                f"  {i+1}. [{meta['prodCode']}] {meta['조']} {meta.get('title','')[:40]} (score: {r['score']:.4f})"
            )
