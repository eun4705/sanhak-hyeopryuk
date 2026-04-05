"""
터미널 채팅 — 수동 테스트용

사용법:
    python run_chat.py

환경변수:
    OPENROUTER_API_KEY: OpenRouter API 키 (.env 파일 또는 환경변수)
"""

import os
import sys

# scraper/ 모듈 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scraper"))

from dotenv import load_dotenv
load_dotenv()

from agent_runner import InsuranceAgent


def main():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY가 설정되지 않았습니다.")
        print(".env 파일에 OPENROUTER_API_KEY=sk-... 형태로 추가하세요.")
        sys.exit(1)

    print("모델 로딩 중... (첫 실행 시 시간이 걸릴 수 있습니다)")
    agent = InsuranceAgent(api_key=api_key)
    print("준비 완료! 'q' 입력 시 종료.\n")

    while True:
        try:
            user_input = input("사용자: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            break

        response = agent.chat(user_input)

        # Tool 호출 로그
        if response.tool_calls:
            print(f"\n  [Tool 호출 {len(response.tool_calls)}건]")
            for tc in response.tool_calls:
                args_short = json.dumps(tc.arguments, ensure_ascii=False)
                if len(args_short) > 80:
                    args_short = args_short[:80] + "..."
                print(f"    → {tc.name}({args_short})")

        print(f"\nAgent: {response.content}\n")

        if response.error:
            print(f"  [오류: {response.error}]")


if __name__ == "__main__":
    import json
    main()
