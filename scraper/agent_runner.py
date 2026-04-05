"""
AI 보험 설계 Agent — OpenRouter LLM 연동 + Function Calling 오케스트레이션

최적화 적용:
  1. Pre-routing: 규칙 기반 의도 분류 → LLM 왕복 1회로 감소
  2. 카탈로그 캐싱: 반복 호출 제거
  3. Connection pooling: HTTP 연결 재사용
  4. 응답 길이 제한: max_tokens
  5. Tool 스키마 선택적 전송
"""

import json
import os
import re
import requests
from dataclasses import dataclass, field
from typing import Optional

from agent_tools import (
    AgentDataStore,
    tool_search_yakgwan,
    tool_lookup_premium,
    tool_compare_products,
    tool_get_product_catalog,
    tool_design_plan,
)
from agent_prompt import SYSTEM_PROMPT

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-haiku-4-5"
MAX_TOOL_ROUNDS = 3

# Pre-route용 최소 프롬프트 (풀 시스템 프롬프트 대신 사용)
MINI_SEARCH_PROMPT = """당신은 KB라이프 보험 약관 전문 AI입니다. 아래 약관 검색 결과를 바탕으로 사용자 질문에 간결하게 3~5문장으로 답변하세요.
반드시 약관 조항을 인용하세요 (예: "약관 제5조에 따르면..."). "다만", "단서", "예외" 조항이 있으면 반드시 함께 안내하세요.
검색 결과에 없는 정보는 절대 추측하거나 지어내지 마세요.
답변 말미에 "본 정보는 참고용이며, 보험 가입은 전문 설계사와 상담하시기 바랍니다."를 포함하세요."""

MINI_SYSTEM_PROMPT = """당신은 KB라이프 보험 안내 AI입니다. 아래 상품 데이터를 바탕으로 사용자 질문에 간결하게 3~5문장으로 답변하세요.
주계약(main_coverage)뿐 아니라 특약(available_riders)도 반드시 확인하세요. 특약으로 보장되는 상품도 빠짐없이 안내하세요.
데이터에 없는 정보는 절대 추측하거나 지어내지 마세요. available_riders가 비어있으면 특약이 없는 상품입니다.
답변 말미에 "본 정보는 참고용이며, 보험 가입은 전문 설계사와 상담하시기 바랍니다."를 포함하세요."""


# ── 의도 분류 (Pre-routing) ──

INTENT_PATTERNS = {
    # search를 먼저 체크 (보장/면책/해지 질문이 premium/catalog보다 우선)
    "search": [
        r"약관", r"보장.*내용", r"면책", r"제외", r"해지", r"해약", r"환급",
        r"청약.*철회", r"납입.*유예", r"보험금.*지급", r"보험금.*청구",
        r"부활", r"대출", r"감액", r"수익자", r"계약.*변경",
        r"재해", r"장해", r"질병", r"암.*진단",
        r"면책기간", r"감액기간", r"보장.*개시",
        r"안.*내면", r"미납", r"연체",
        r"지급.*안", r"안.*되는.*경우",
        r"사망.*조건", r"사망.*보험금",
        r"특약", r"부가.*보장", r"추가.*보장",
    ],
    "compare": [
        r"차이", r"비교", r"다른.*점", r"뭐가.*달라", r"vs",
        r"일반심사.*간편심사", r"간편.*일반",
    ],
    "premium": [
        r"보험료.*얼마", r"보험료.*알려", r"월.*보험료",
        r"보험.*가격", r"보험료.*조회",
        r"\d+세.*(남|여).*보험료", r"보험료.*\d+세",
    ],
    "catalog": [
        r"어떤.*(보험|상품)", r"상품.*목록", r"뭐.*있", r"종류",
        r"보험.*찾", r"보험.*추천", r"보험.*알려",
        r"가입.*할.*수.*있는",
        r"간편심사.*상품", r"달러.*보험", r"갱신형", r"보험.*드는",
        r"보험.*처음", r"보험.*시작", r"보장.*받고.*싶",
        r"보험.*들어야", r"보험.*가입", r"보험.*좋아",
        r"보험.*뭐가", r"보험.*어떤", r"보험.*봐야",
        r"보험.*필요", r"보험.*해야",
        r"\d+대.*보험", r"\d+세.*보험",
    ],
}


def classify_intent(query: str) -> str:
    """규칙 기반 의도 분류. 매칭 안 되면 search (보험 챗봇이므로 약관 검색이 기본)."""
    query_lower = query.lower().strip()
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query_lower):
                return intent
    return "search"


# ── Tool 스키마 (전체 + 의도별 서브셋) ──

SCHEMA_CATALOG = {
    "type": "function",
    "function": {
        "name": "get_product_catalog",
        "description": "KB라이프 18개 보험 상품 목록과 기본 정보를 반환합니다.",
        "parameters": {"type": "object", "properties": {}},
    },
}

SCHEMA_PREMIUM = {
    "type": "function",
    "function": {
        "name": "lookup_premium",
        "description": "보험료를 정확히 조회합니다. prod_code(상품코드)로 조회하는 것을 권장합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "prod_code": {"type": "string", "description": "상품 코드 (예: 'KL0420')"},
                "product": {"type": "string", "description": "상품명 (fallback용)"},
                "age": {"type": "integer", "description": "나이"},
                "gender": {"type": "string", "enum": ["남", "여"], "description": "성별"},
                "insurance_term": {"type": "string", "description": "보험기간"},
                "payment_term": {"type": "string", "description": "납입기간"},
            },
            "required": [],
        },
    },
}

SCHEMA_COMPARE = {
    "type": "function",
    "function": {
        "name": "compare_products",
        "description": "2~4개 보험 상품을 비교합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_codes": {
                    "type": "array", "items": {"type": "string"},
                    "description": "비교할 상품 코드 (2~4개)",
                },
                "user_age": {"type": "integer", "description": "사용자 나이"},
                "user_gender": {"type": "string", "enum": ["남", "여"], "description": "성별"},
            },
            "required": ["product_codes"],
        },
    },
}

SCHEMA_SEARCH = {
    "type": "function",
    "function": {
        "name": "search_yakgwan",
        "description": "약관 텍스트에서 관련 조항을 검색합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색할 내용"},
                "product_codes": {
                    "type": "array", "items": {"type": "string"},
                    "description": "상품 코드 필터",
                },
                "top_k": {"type": "integer", "description": "반환 수 (기본 5)"},
            },
            "required": ["query"],
        },
    },
}

SCHEMA_DESIGN = {
    "type": "function",
    "function": {
        "name": "design_plan",
        "description": "사용자 조건에 맞는 상품 정보를 정리합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_age": {"type": "integer", "description": "나이"},
                "user_gender": {"type": "string", "enum": ["남", "여"], "description": "성별"},
                "coverage_needs": {
                    "type": "array", "items": {"type": "string"},
                    "description": "필요한 보장",
                },
                "budget": {"type": "integer", "description": "월 예산 (원)"},
            },
            "required": ["user_age", "user_gender", "coverage_needs"],
        },
    },
}

ALL_SCHEMAS = [SCHEMA_SEARCH, SCHEMA_PREMIUM, SCHEMA_COMPARE, SCHEMA_CATALOG, SCHEMA_DESIGN]

# 의도별 필요한 스키마만
INTENT_SCHEMAS = {
    "catalog": [SCHEMA_CATALOG, SCHEMA_DESIGN],
    "premium": [SCHEMA_PREMIUM, SCHEMA_CATALOG],
    "compare": [SCHEMA_COMPARE, SCHEMA_CATALOG],
    "search":  [SCHEMA_SEARCH],
}


# ── 응답 데이터 클래스 ──

@dataclass
class ToolCall:
    name: str
    arguments: dict
    result: dict


@dataclass
class AgentResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    total_rounds: int = 0
    error: Optional[str] = None
    pre_routed: bool = False


# ── Agent 본체 ──

class InsuranceAgent:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        data_store: AgentDataStore = None,
        search_engine=None,
        load_models: bool = True,
    ):
        self.api_key = api_key
        self.model = model
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        self.data_store = data_store or AgentDataStore()

        # 카탈로그 캐시
        self._catalog_cache = None

        # Connection pooling
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "KB Insurance Agent",
        })

        if search_engine is not None:
            self.search_engine = search_engine
        elif load_models:
            from search_engine import SearchEngine
            self.search_engine = SearchEngine(verbose=True)
        else:
            self.search_engine = None

    def chat(self, user_message: str) -> AgentResponse:
        msg_count_before = len(self.messages)
        self.messages.append({"role": "user", "content": user_message})

        # Pre-routing: 의도 분류 → Tool 미리 실행
        intent = classify_intent(user_message)
        pre_routed_tool = None
        pre_routed_result = None

        if intent == "catalog":
            pre_routed_tool = "get_product_catalog"
            pre_routed_result = self._execute_tool("get_product_catalog", {})
        elif intent == "search" and self.search_engine is not None:
            pre_routed_tool = "search_yakgwan"
            pre_routed_result = self._execute_tool("search_yakgwan", {
                "query": user_message, "top_k": 5,
            })

        # Pre-route된 경우: 미니 프롬프트 + Tool 결과 주입 → LLM 1회 호출
        if pre_routed_result is not None:
            tool_result_str = json.dumps(pre_routed_result, ensure_ascii=False, default=str)
            if len(tool_result_str) > 8000:
                tool_result_str = self._truncate_result(tool_result_str)

            tc = ToolCall(name=pre_routed_tool, arguments={}, result=pre_routed_result)

            # 의도에 따라 프롬프트 선택
            if pre_routed_tool == "search_yakgwan":
                system_msg = MINI_SEARCH_PROMPT
                user_content = f"[약관 검색 결과]\n{tool_result_str}\n\n[질문]\n{user_message}"
            else:
                system_msg = MINI_SYSTEM_PROMPT
                user_content = f"[상품 데이터]\n{tool_result_str}\n\n[질문]\n{user_message}"

            mini_messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_content},
            ]

            # LLM 1회 호출 — Tool 스키마 없이, 짧은 응답
            result = self._call_llm_direct(mini_messages, max_tokens=400)

            if result is None:
                self.messages = self.messages[:msg_count_before]
                return AgentResponse(
                    content="API 호출 중 오류가 발생했습니다.",
                    tool_calls=[tc], total_rounds=1,
                    error="LLM API call failed", pre_routed=True,
                )

            content = result["choices"][0]["message"].get("content") or ""
            self.messages.append({"role": "assistant", "content": content})
            return AgentResponse(
                content=content, tool_calls=[tc],
                total_rounds=1, pre_routed=True,
            )

        # 일반 경로: LLM이 Tool 선택 (기존 방식, 의도별 스키마 축소)
        schemas = INTENT_SCHEMAS.get(intent, ALL_SCHEMAS)
        all_tool_calls = []
        rounds = 0

        while rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            result = self._call_llm(tools=schemas, max_tokens=1000)

            if result is None:
                self.messages = self.messages[:msg_count_before]
                return AgentResponse(
                    content="API 호출 중 오류가 발생했습니다.",
                    tool_calls=all_tool_calls, total_rounds=rounds,
                    error="LLM API call failed",
                )

            message = result["choices"][0]["message"]

            if not message.get("tool_calls"):
                content = message.get("content") or ""
                self.messages.append({"role": "assistant", "content": content})
                return AgentResponse(
                    content=content, tool_calls=all_tool_calls,
                    total_rounds=rounds,
                )

            if message.get("content") is None:
                message["content"] = ""
            self.messages.append(message)

            new_calls = self._handle_tool_calls(message["tool_calls"], msg_count_before)
            all_tool_calls.extend(new_calls)

            # 이후 라운드에서는 전체 스키마 (추가 Tool 필요할 수 있으므로)
            schemas = ALL_SCHEMAS

        self.messages = self.messages[:msg_count_before]
        return AgentResponse(
            content="처리 중 Tool 호출 횟수가 초과되었습니다.",
            tool_calls=all_tool_calls, total_rounds=rounds,
            error="Max tool rounds exceeded",
        )

    def _handle_tool_calls(self, tool_calls: list, msg_count_before: int) -> list[ToolCall]:
        """Tool call 목록 실행 후 결과를 messages에 추가"""
        results = []
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}

            tool_result = self._execute_tool(fn_name, fn_args)
            tool_result_str = json.dumps(tool_result, ensure_ascii=False, default=str)

            if len(tool_result_str) > 8000:
                tool_result_str = self._truncate_result(tool_result_str)

            results.append(ToolCall(name=fn_name, arguments=fn_args, result=tool_result))

            self.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result_str,
            })
        return results

    def _truncate_result(self, result_str: str) -> str:
        """JSON 구조 보존 truncation"""
        try:
            truncated = json.loads(result_str)
            if isinstance(truncated, dict) and "results" in truncated:
                truncated["results"] = truncated["results"][:3]
                truncated["_truncated"] = True
            return json.dumps(truncated, ensure_ascii=False, default=str)
        except (json.JSONDecodeError, TypeError):
            return result_str[:8000] + "\n...(truncated)"

    def reset(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._catalog_cache = None

    def _call_llm(self, tools=None, max_tokens=1000) -> Optional[dict]:
        """OpenRouter API 호출 (Tool 포함)"""
        if tools is None:
            tools = ALL_SCHEMAS
        try:
            resp = self._session.post(
                OPENROUTER_URL,
                json={
                    "model": self.model,
                    "messages": self.messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "max_tokens": max_tokens,
                },
                timeout=120,
            )
            if resp.status_code != 200:
                print(f"[ERROR] OpenRouter {resp.status_code}: {resp.text[:300]}")
                return None
            return resp.json()
        except Exception as e:
            print(f"[ERROR] API 호출 실패: {e}")
            return None

    def _call_llm_direct(self, messages: list, max_tokens=400) -> Optional[dict]:
        """OpenRouter API 호출 — Tool 없이 직접 (pre-route용, 최소 토큰)"""
        try:
            resp = self._session.post(
                OPENROUTER_URL,
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                print(f"[ERROR] OpenRouter {resp.status_code}: {resp.text[:300]}")
                return None
            return resp.json()
        except Exception as e:
            print(f"[ERROR] API 호출 실패: {e}")
            return None

    def _execute_tool(self, name: str, args: dict) -> dict:
        try:
            if name == "search_yakgwan":
                if self.search_engine is None:
                    return {"error": "검색 엔진이 로드되지 않았습니다."}
                return tool_search_yakgwan(
                    query=args["query"],
                    search_engine=self.search_engine,
                    data_store=self.data_store,
                    product_codes=args.get("product_codes"),
                    top_k=args.get("top_k", 5),
                )
            elif name == "lookup_premium":
                return tool_lookup_premium(
                    data_store=self.data_store,
                    product=args.get("product"),
                    prod_code=args.get("prod_code"),
                    age=args.get("age"),
                    gender=args.get("gender"),
                    insurance_term=args.get("insurance_term"),
                    payment_term=args.get("payment_term"),
                )
            elif name == "compare_products":
                return tool_compare_products(
                    data_store=self.data_store,
                    product_codes=args["product_codes"],
                    user_age=args.get("user_age"),
                    user_gender=args.get("user_gender"),
                )
            elif name == "get_product_catalog":
                if self._catalog_cache is None:
                    self._catalog_cache = tool_get_product_catalog(self.data_store)
                return self._catalog_cache
            elif name == "design_plan":
                return tool_design_plan(
                    data_store=self.data_store,
                    user_age=args["user_age"],
                    user_gender=args["user_gender"],
                    coverage_needs=args["coverage_needs"],
                    budget=args.get("budget"),
                )
            else:
                return {"error": f"알 수 없는 Tool: {name}"}
        except Exception as e:
            return {"error": f"Tool 실행 오류: {str(e)}"}
