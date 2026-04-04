"""
AI 보험 설계 Agent — 5개 Tool 구현

Tool A: search_yakgwan    — 약관 검색 (Hybrid+Reranker+상품필터+2차조회)
Tool B: lookup_premium    — 보험료 정확 조회
Tool C: compare_products  — 상품 비교 (Comparison Index + 보험료)
Tool D: get_product_catalog — 상품 카탈로그
Tool E: design_plan       — 설계안 정보 정리
"""

import json
import os
import re
import glob
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_DATA_DIR = os.path.join(BASE_DIR, "data", "agent_data")
PREMIUMS_DIR = os.path.join(BASE_DIR, "data", "premiums")
APPENDIX_DIR = os.path.join(BASE_DIR, "data", "별표_parsed")


# ── 데이터 로드 (앱 시작 시 1회) ──

def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class AgentDataStore:
    """Agent가 사용하는 모든 구조화 데이터를 메모리에 로드"""

    def __init__(self):
        self.coverage_rules = _load_json(
            os.path.join(AGENT_DATA_DIR, "coverage_rules.json")
        )
        self.comparison_matrix = _load_json(
            os.path.join(AGENT_DATA_DIR, "comparison_matrix.json")
        )
        self.related_articles = _load_json(
            os.path.join(AGENT_DATA_DIR, "related_articles.json")
        )
        self.comparison_notes = _load_json(
            os.path.join(AGENT_DATA_DIR, "comparison_notes.json")
        )

        # 별표 데이터
        self.appendices = {}
        for f in glob.glob(os.path.join(APPENDIX_DIR, "*.json")):
            code = os.path.basename(f).replace(".json", "")
            self.appendices[code] = _load_json(f)

        # 보험료 데이터 인덱싱
        self._premium_index = {}
        self._load_premiums()

    def _load_premiums(self):
        """보험료 JSONL을 product별로 인덱싱"""
        for f in glob.glob(os.path.join(PREMIUMS_DIR, "*.jsonl")):
            with open(f, "r", encoding="utf-8") as fp:
                for line in fp:
                    record = json.loads(line)
                    product = record["product"]
                    if product not in self._premium_index:
                        self._premium_index[product] = []
                    self._premium_index[product].append(record)

    def get_product_list(self):
        """전체 상품 목록"""
        return list(self.comparison_matrix.get("products", {}).keys())


# ── Tool A: 약관 검색 ──

def tool_search_yakgwan(
    query: str,
    search_engine,
    data_store: AgentDataStore,
    product_codes: list[str] = None,
    top_k: int = 5,
) -> dict:
    """
    약관 검색 + related_articles 2차 조회 + gap_alerts 주입

    Returns:
        {
            "results": [...],           # 검색 결과
            "related_lookups": [...],    # 2차 조회 결과
            "gap_alerts": {...},         # 해당 상품 경고
            "mandatory_disclosure": [...] # 필수 고지
        }
    """
    # 1. Hybrid Search (기존 search_engine 활용)
    # product_codes 필터는 search_engine.search에 전달
    search_kwargs = {
        "top_k": top_k,
        "use_reranker": True,
        "use_expansion": True,
    }

    results = search_engine.search(query, **search_kwargs)

    # product_codes 필터 적용 (search_engine에 where 필터가 없으면 후처리)
    if product_codes:
        results = [
            r for r in results
            if r["metadata"].get("prodCode") in product_codes
        ][:top_k]

    # 2. 관련 조항 2차 조회 (related_articles 그래프)
    related_lookups = []
    seen_articles = set()
    for r in results:
        prod_code = r["metadata"].get("prodCode", "")
        article = r["metadata"].get("조", "")

        if prod_code in data_store.related_articles:
            prod_articles = data_store.related_articles[prod_code]
            if article in prod_articles:
                refs = prod_articles[article].get("references_to", [])
                for ref in refs:
                    ref_key = f"{prod_code}:{ref}"
                    if ref_key not in seen_articles and ref in prod_articles:
                        seen_articles.add(ref_key)
                        ref_info = prod_articles[ref]
                        related_lookups.append({
                            "prodCode": prod_code,
                            "article": ref,
                            "title": ref_info.get("title", ""),
                            "type": ref_info.get("type", ""),
                        })

    # 3. 해당 상품들의 gap_alerts + mandatory_disclosure 수집
    mentioned_products = set()
    if product_codes:
        mentioned_products.update(product_codes)
    for r in results:
        pc = r["metadata"].get("prodCode", "")
        if pc:
            mentioned_products.add(pc)

    gap_alerts = {}
    mandatory_disclosures = []
    for pc in mentioned_products:
        if pc in data_store.coverage_rules:
            rules = data_store.coverage_rules[pc]
            alerts = rules.get("gap_alerts", {})
            if alerts:
                gap_alerts[pc] = alerts
            md = rules.get("mandatory_disclosure", [])
            if md:
                mandatory_disclosures.extend(md)

    # 4. "다만/불구하고" 절 표시
    for r in results:
        text = r.get("text", "")
        has_exception = bool(re.search(r"다만|불구하고|제외|예외", text))
        r["has_exception_clause"] = has_exception

    return {
        "results": results,
        "related_lookups": related_lookups[:10],
        "gap_alerts": gap_alerts,
        "mandatory_disclosure": list(set(mandatory_disclosures)),
    }


# ── Tool B: 보험료 조회 ──

def tool_lookup_premium(
    data_store: AgentDataStore,
    product: str,
    age: int = None,
    gender: str = None,
    insurance_term: str = None,
    payment_term: str = None,
) -> dict:
    """
    보험료 정확 조회. 벡터 검색 절대 안 씀.

    Returns:
        {
            "product": str,
            "matching_records": [...],  # 조건에 맞는 레코드들
            "total_found": int,
            "filters_applied": {...}
        }
    """
    records = data_store._premium_index.get(product, [])

    if not records:
        # 부분 매칭 시도
        for key in data_store._premium_index:
            if product in key or key in product:
                records = data_store._premium_index[key]
                product = key
                break

    if not records:
        return {
            "product": product,
            "matching_records": [],
            "total_found": 0,
            "filters_applied": {},
            "error": f"'{product}' 상품을 찾을 수 없습니다. 가능한 상품: {list(data_store._premium_index.keys())}",
        }

    # 필터 적용
    filtered = records
    filters = {}

    if age is not None:
        filtered = [r for r in filtered if r.get("age") == age]
        filters["age"] = age

    if gender is not None:
        filtered = [r for r in filtered if r.get("gender") == gender]
        filters["gender"] = gender

    if insurance_term is not None:
        filtered = [
            r for r in filtered
            if str(r.get("insuranceTerm", "")) == str(insurance_term)
        ]
        filters["insuranceTerm"] = insurance_term

    if payment_term is not None:
        filtered = [
            r for r in filtered
            if str(r.get("paymentTerm", "")) == str(payment_term)
        ]
        filters["paymentTerm"] = payment_term

    # 결과 정리 (최대 10개)
    results = []
    for r in filtered[:10]:
        result = {
            "age": r.get("age"),
            "gender": r.get("gender"),
            "insuranceTerm": r.get("insuranceTerm"),
            "paymentTerm": r.get("paymentTerm"),
            "paymentCycle": r.get("paymentCycle"),
            "productType": r.get("productType"),
            "variants": r.get("variants", []),
        }
        # 연금 상품 추가 정보
        if r.get("productType") == "연금":
            result["annuityStartAge"] = r.get("annuityStartAge")
            result["accumulation"] = r.get("accumulation")
            result["totalPaid"] = r.get("totalPaid")
            result["annuities"] = r.get("annuities", [])
        results.append(result)

    return {
        "product": product,
        "matching_records": results,
        "total_found": len(filtered),
        "filters_applied": filters,
    }


# ── Tool C: 상품 비교 ──

def tool_compare_products(
    data_store: AgentDataStore,
    product_codes: list[str],
    user_age: int = None,
    user_gender: str = None,
) -> dict:
    """
    상품 비교: Comparison Index + 보험료 + comparison_notes + term_definitions

    Returns:
        {
            "products": {...},         # 각 상품 비교 데이터
            "comparison_notes": {...},  # 해당 쌍의 차이 설명
            "term_conflicts": [...],    # 용어 정의 차이
            "constraints": [...],       # 비교 제약사항
            "premium_comparison": {...} # 보험료 비교 (나이/성별 제공 시)
        }
    """
    products_data = data_store.comparison_matrix.get("products", {})

    # 1. Comparison Matrix에서 비교 데이터 수집
    comparison = {}
    for code in product_codes:
        if code in products_data:
            comparison[code] = products_data[code]

    # 2. comparison_notes에서 해당 쌍 찾기
    notes = {}
    pairs = data_store.comparison_notes.get("pairs", [])
    for pair in pairs:
        pair_products = set(pair.get("products", []))
        if pair_products.issubset(set(product_codes)):
            pair_key = " vs ".join(pair["products"])
            notes[pair_key] = {
                "label": pair.get("pair_label", ""),
                "key_differences": pair.get("key_differences", []),
                "suitable_for": pair.get("suitable_for", {}),
                "cautions": pair.get("cautions", []),
            }

    # 3. 용어 정의 충돌 감지
    term_conflicts = []
    all_terms = {}
    for code in product_codes:
        if code in data_store.coverage_rules:
            terms = data_store.coverage_rules[code].get("term_definitions", {})
            for term, info in terms.items():
                if term in all_terms:
                    prev_code, prev_info = all_terms[term]
                    if info.get("scope") != prev_info.get("scope"):
                        term_conflicts.append({
                            "term": term,
                            "products": {
                                prev_code: prev_info,
                                code: info,
                            },
                        })
                else:
                    all_terms[term] = (code, info)

    # 4. 비교 제약사항 확인
    constraints = []
    comp_constraints = data_store.comparison_notes.get("comparison_constraints", [])
    if isinstance(comp_constraints, list):
        for c in comp_constraints:
            prods = set(c.get("products", []))
            if prods.issubset(set(product_codes)):
                constraints.append(c)
    elif isinstance(comp_constraints, dict):
        for key, val in comp_constraints.items():
            constraints.append({"key": key, "detail": val})

    # 5. 보험료 비교 (나이/성별 제공 시)
    premium_comparison = {}
    if user_age and user_gender:
        for code in product_codes:
            if code in products_data:
                product_name = products_data[code].get("short_name", "")
                premium_result = tool_lookup_premium(
                    data_store, product_name,
                    age=user_age, gender=user_gender,
                )
                if premium_result["matching_records"]:
                    premium_comparison[code] = premium_result["matching_records"][0]

    return {
        "products": comparison,
        "comparison_notes": notes,
        "term_conflicts": term_conflicts,
        "constraints": constraints,
        "premium_comparison": premium_comparison,
    }


# ── Tool D: 상품 카탈로그 ──

def tool_get_product_catalog(data_store: AgentDataStore) -> dict:
    """
    18개 상품 기본 정보 반환.
    Agent가 어떤 상품을 검색/비교할지 결정하는 데 사용.

    Returns:
        {
            "products": [
                {
                    "prodCode": "KL0420",
                    "name": "KB 착한암보험 무배당",
                    "type": "암보험",
                    "main_coverage": "암 진단금",
                    ...
                },
                ...
            ],
            "product_count": 18,
            "categories": {...}
        }
    """
    products_data = data_store.comparison_matrix.get("products", {})
    catalog = []
    categories = {}

    for code, info in products_data.items():
        product_type = info.get("product_type", "기타")

        entry = {
            "prodCode": code,
            "name": info.get("product_name", ""),
            "short_name": info.get("short_name", ""),
            "product_type": product_type,
            "underwriting_type": info.get("underwriting_type", ""),
            "main_coverage": info.get("main_coverage", ""),
            "insurance_period": info.get("insurance_period", ""),
            "entry_age_range": info.get("entry_age_range", ""),
            "renewable": info.get("renewable", False),
            "currency": info.get("currency", "KRW"),
            "rider_count": info.get("rider_count", 0),
            "critical_alerts": info.get("critical_alerts", []),
        }
        catalog.append(entry)

        if product_type not in categories:
            categories[product_type] = []
        categories[product_type].append(code)

    return {
        "products": catalog,
        "product_count": len(catalog),
        "categories": categories,
    }


# ── Tool E: 설계안 정보 정리 ──

def tool_design_plan(
    data_store: AgentDataStore,
    user_age: int,
    user_gender: str,
    coverage_needs: list[str],
    budget: int = None,
) -> dict:
    """
    사용자 조건에 맞는 상품 + 특약 조합 정보 정리.
    "추천"이 아닌 "조건별 상품 정보 정리".

    Args:
        user_age: 사용자 나이
        user_gender: "남" / "여"
        coverage_needs: ["사망", "암", "입원"] 등
        budget: 월 예산 (원), None이면 제한 없음

    Returns:
        {
            "user_profile": {...},
            "candidate_products": [...],
            "plan_options": [...],
            "disclaimer": str
        }
    """
    products_data = data_store.comparison_matrix.get("products", {})

    # 1. 니즈에 맞는 상품 필터링
    candidates = []
    for code, info in products_data.items():
        main_cov = str(info.get("main_coverage", "")).lower()
        product_type = str(info.get("product_type", "")).lower()

        # 나이 범위 체크
        age_range = info.get("entry_age_range", "")
        if age_range:
            match = re.findall(r"\d+", str(age_range))
            if len(match) >= 2:
                min_age, max_age = int(match[0]), int(match[1])
                if user_age < min_age or user_age > max_age:
                    continue

        # 니즈 매칭
        relevance = 0
        for need in coverage_needs:
            need_lower = need.lower()
            if need_lower in main_cov or need_lower in product_type:
                relevance += 1

        if relevance > 0:
            candidates.append({
                "prodCode": code,
                "product_name": info.get("product_name", ""),
                "product_type": info.get("product_type", ""),
                "main_coverage": info.get("main_coverage", ""),
                "relevance": relevance,
            })

    candidates.sort(key=lambda x: x["relevance"], reverse=True)

    # 2. 후보 상품별 보험료 조회
    plan_options = []
    for candidate in candidates[:5]:
        code = candidate["prodCode"]
        short_name = products_data[code].get("short_name", "")

        premium = tool_lookup_premium(
            data_store, short_name,
            age=user_age, gender=user_gender,
        )

        if premium["matching_records"]:
            record = premium["matching_records"][0]
            variants = record.get("variants", [])

            for variant in variants[:2]:
                total = variant.get("totalPremium", 0)

                # 예산 필터
                if budget and total > budget:
                    continue

                plan_options.append({
                    "prodCode": code,
                    "product_name": candidate["product_name"],
                    "variant_name": variant.get("name", "기본"),
                    "mainAmount": variant.get("mainAmount", 0),
                    "mainPremium": variant.get("mainPremium", 0),
                    "totalPremium": total,
                    "riders": variant.get("riders", []),
                    "insuranceTerm": record.get("insuranceTerm"),
                    "paymentTerm": record.get("paymentTerm"),
                })

    # 3. 해당 상품들의 critical alerts 수집
    alerts = {}
    for p in plan_options:
        code = p["prodCode"]
        if code in data_store.coverage_rules:
            rules = data_store.coverage_rules[code]
            critical = rules.get("gap_alerts", {}).get("critical", [])
            if critical:
                alerts[code] = critical

    return {
        "user_profile": {
            "age": user_age,
            "gender": user_gender,
            "coverage_needs": coverage_needs,
            "budget": budget,
        },
        "candidate_products": candidates[:5],
        "plan_options": plan_options,
        "critical_alerts": alerts,
        "disclaimer": "본 정보는 참고용이며, 보험 가입은 전문 설계사와 상담하시기 바랍니다.",
    }


# ── 테스트 ──

if __name__ == "__main__":
    print("데이터 로드 중...")
    store = AgentDataStore()
    print(f"상품 수: {len(store.get_product_list())}")
    print(f"보험료 상품: {list(store._premium_index.keys())}")

    # Tool D 테스트
    print("\n=== Tool D: 카탈로그 ===")
    catalog = tool_get_product_catalog(store)
    print(f"상품 {catalog['product_count']}개, 카테고리: {list(catalog['categories'].keys())}")
    for p in catalog["products"][:3]:
        print(f"  {p['prodCode']}: {p['name']} ({p['product_type']})")

    # Tool B 테스트
    print("\n=== Tool B: 보험료 조회 ===")
    result = tool_lookup_premium(store, "착한암보험", age=30, gender="남")
    print(f"검색 결과: {result['total_found']}건")
    if result["matching_records"]:
        r = result["matching_records"][0]
        for v in r["variants"]:
            print(f"  {v['name']}: 월 {v['totalPremium']:,}원 (가입금액 {v['mainAmount']:,}원)")

    # Tool C 테스트
    print("\n=== Tool C: 상품 비교 ===")
    comp = tool_compare_products(store, ["KL1609", "KL1608"])
    print(f"비교 상품: {list(comp['products'].keys())}")
    for key, note in comp["comparison_notes"].items():
        print(f"  {note['label']}:")
        for diff in note["key_differences"][:3]:
            print(f"    - {diff}")

    # Tool E 테스트
    print("\n=== Tool E: 설계안 ===")
    plan = tool_design_plan(store, user_age=30, user_gender="남", coverage_needs=["사망"], budget=100000)
    print(f"후보 상품: {len(plan['candidate_products'])}개")
    for opt in plan["plan_options"][:3]:
        print(f"  {opt['product_name']} ({opt['variant_name']}): 월 {opt['totalPremium']:,}원")
    print(f"면책: {plan['disclaimer']}")
