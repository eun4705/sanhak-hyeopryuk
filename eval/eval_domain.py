"""
임베딩 품질 평가: 도메인 특화 테스트
1. 동의어 테스트: 같은 의미 다른 표현으로 검색 시 일관성
2. 부정문 구분 테스트: "보장하는" vs "보장하지 않는" 구분
3. 교차참조 테스트: "제X조에 따라" 참조 시 원본 조항 검색
"""

import json
import os
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DIR = os.path.join(BASE_DIR, "data", "chroma_db")
MODEL_NAME = "dragonkue/BGE-m3-ko"


def run_test(model, collection, test_name, test_pairs):
    print(f"\n{'='*60}")
    print(f"  {test_name}")
    print(f"{'='*60}")

    for pair in test_pairs:
        queries = pair["queries"]
        embeddings = model.encode(queries, normalize_embeddings=True)

        results_list = []
        for i, q in enumerate(queries):
            results = collection.query(
                query_embeddings=[embeddings[i].tolist()],
                n_results=5,
            )
            results_list.append(results)

        # 상위 5개 결과 비교
        print(f"\n  테스트: {pair['desc']}")
        for i, q in enumerate(queries):
            ids = results_list[i]["ids"][0]
            metas = results_list[i]["metadatas"][0]
            print(f"  Q: \"{q}\"")
            for j, (did, meta) in enumerate(zip(ids[:3], metas[:3])):
                print(f"    {j+1}. [{meta['prodCode']}] {meta['조']} {meta.get('title','')[:40]}")

        # 겹침률 계산
        if len(queries) == 2:
            set1 = set(results_list[0]["ids"][0][:5])
            set2 = set(results_list[1]["ids"][0][:5])
            overlap = len(set1 & set2)
            print(f"  → Top-5 겹침률: {overlap}/5 ({overlap/5:.0%})")

            if "expected" in pair:
                print(f"  → 기대: {pair['expected']}")


def main():
    print(f"모델 로드 중: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_collection("insurance_articles")

    # ── 1. 동의어 테스트 ──
    synonym_tests = [
        {
            "desc": "피보험자 = 보험 대상자",
            "queries": ["피보험자가 사망하면 보험금은?", "보험 대상자가 사망하면 보험금은?"],
            "expected": "동일한 결과가 나와야 함 (겹침률 높을수록 좋음)"
        },
        {
            "desc": "해약환급금 = 해지 환불금",
            "queries": ["해약환급금이 얼마야?", "보험 해지하면 환불금 얼마야?"],
            "expected": "동일한 결과가 나와야 함"
        },
        {
            "desc": "보험금 청구 = 보험금 신청 = 클레임",
            "queries": ["보험금 청구 방법은?", "보험금 신청하려면 어떻게 해?"],
            "expected": "동일한 결과가 나와야 함"
        },
        {
            "desc": "보험료 납입 = 보험료 납부 = 보험료 지불",
            "queries": ["보험료 납입 방법은?", "보험료를 어떻게 내나요?"],
            "expected": "동일한 결과가 나와야 함"
        },
        {
            "desc": "재해 = 사고",
            "queries": ["재해로 인한 사망 보장은?", "사고로 죽으면 보험금 나와?"],
            "expected": "유사한 결과가 나와야 함"
        },
    ]
    run_test(model, col, "1. 동의어 테스트", synonym_tests)

    # ── 2. 부정문 구분 테스트 ──
    negation_tests = [
        {
            "desc": "보장하는 사유 vs 보장하지 않는 사유",
            "queries": ["보험금을 지급하는 사유는?", "보험금을 지급하지 않는 사유는?"],
            "expected": "서로 다른 조항이 나와야 함 (겹침률 낮을수록 좋음)"
        },
        {
            "desc": "계약 성립 vs 계약 무효",
            "queries": ["보험계약이 성립하는 조건은?", "보험계약이 무효가 되는 경우는?"],
            "expected": "서로 다른 조항이 나와야 함"
        },
        {
            "desc": "보험료 납입 vs 보험료 미납",
            "queries": ["보험료를 정상 납입하면?", "보험료를 안 내면 어떻게 되나요?"],
            "expected": "서로 다른 조항이 나와야 함"
        },
    ]
    run_test(model, col, "2. 부정문 구분 테스트", negation_tests)

    # ── 3. 구어체 vs 약관 용어 테스트 ──
    colloquial_tests = [
        {
            "desc": "구어체 vs 약관 용어",
            "queries": ["보험 들었다가 취소하고 싶어", "청약의 철회"],
            "expected": "동일한 결과가 나와야 함"
        },
        {
            "desc": "구어체 vs 약관 용어 2",
            "queries": ["보험 해지하면 돈 돌려받을 수 있어?", "해약환급금"],
            "expected": "동일한 결과가 나와야 함"
        },
        {
            "desc": "구어체 vs 약관 용어 3",
            "queries": ["나이 먹으면 보험료가 올라?", "보험나이 및 보험료 갱신"],
            "expected": "유사한 결과가 나와야 함"
        },
    ]
    run_test(model, col, "3. 구어체 vs 약관 용어 테스트", colloquial_tests)

    print(f"\n{'='*60}")
    print("  도메인 특화 테스트 완료")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
