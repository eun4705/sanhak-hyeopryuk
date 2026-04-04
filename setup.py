"""
KB라이프 AI 보험 설계 Agent — 환경 설정 스크립트

실행: python setup.py
"""

import subprocess
import sys
import os


def run(cmd, desc):
    print(f"\n{'='*50}")
    print(f"  {desc}")
    print(f"{'='*50}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"  [실패] {desc}")
        return False
    print(f"  [완료] {desc}")
    return True


def main():
    print("=" * 50)
    print("  KB라이프 AI 보험 설계 Agent 환경 설정")
    print("=" * 50)

    # 1. pip 업그레이드
    run(f"{sys.executable} -m pip install --upgrade pip", "pip 업그레이드")

    # 2. 패키지 설치
    req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if not run(f"{sys.executable} -m pip install -r {req_path}", "패키지 설치"):
        print("\n패키지 설치 실패. 수동으로 설치해주세요:")
        print("  pip install -r requirements.txt")
        sys.exit(1)

    # 3. 모델 다운로드 (첫 실행 시 자동 다운로드되도록 미리 로드)
    print(f"\n{'='*50}")
    print("  임베딩 모델 다운로드 (~1.2GB)")
    print("  (첫 실행 시에만 다운로드됩니다)")
    print(f"{'='*50}")
    try:
        from sentence_transformers import SentenceTransformer, CrossEncoder

        print("  Qwen/Qwen3-Embedding-0.6B 다운로드 중...")
        SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
        print("  [완료] 임베딩 모델")

        print("  Dongjin-kr/ko-reranker 다운로드 중...")
        CrossEncoder("Dongjin-kr/ko-reranker")
        print("  [완료] Reranker 모델")
    except Exception as e:
        print(f"  [경고] 모델 다운로드 실패: {e}")
        print("  검색 엔진 첫 실행 시 자동으로 다운로드됩니다.")

    # 4. 데이터 확인
    print(f"\n{'='*50}")
    print("  데이터 파일 확인")
    print(f"{'='*50}")
    base = os.path.dirname(__file__)
    checks = [
        ("data/chroma_v2_Qwen_Qwen3_Embedding_0.6B/chroma.sqlite3", "벡터DB"),
        ("data/agent_data/coverage_rules.json", "보장 규칙"),
        ("data/agent_data/comparison_matrix.json", "비교 매트릭스"),
        ("data/premiums", "보험료 데이터"),
    ]
    all_ok = True
    for path, name in checks:
        full = os.path.join(base, path)
        exists = os.path.exists(full)
        status = "OK" if exists else "없음"
        print(f"  [{status}] {name}: {path}")
        if not exists:
            all_ok = False

    # 5. 테스트
    if all_ok:
        print(f"\n{'='*50}")
        print("  검색 엔진 테스트")
        print(f"{'='*50}")
        try:
            sys.path.insert(0, os.path.join(base, "scraper"))
            from search_engine import SearchEngine

            engine = SearchEngine()
            results = engine.search("암보험 보장 내용", top_k=3)
            print(f"\n  테스트 쿼리: '암보험 보장 내용'")
            for i, r in enumerate(results):
                meta = r["metadata"]
                print(f"  {i+1}. [{meta['prodCode']}] {meta['조']} (score: {r['score']:.4f})")
            print("\n  [성공] 검색 엔진 정상 동작!")
        except Exception as e:
            print(f"  [실패] 검색 테스트: {e}")
    else:
        print("\n  일부 데이터 파일이 없습니다. git pull을 확인해주세요.")

    print(f"\n{'='*50}")
    print("  설정 완료!")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
