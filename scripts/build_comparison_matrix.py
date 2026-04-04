#!/usr/bin/env python3
"""
Build comparison_matrix.json — 18 KB라이프 보험상품 비교 매트릭스.

데이터 소스:
  - data/약관_enriched/*.json          (주계약 보장, 특약 수, 제3조/제8조 등)
  - data/premiums/*.jsonl              (보험기간, 납입기간, 가입연령)
  - data/coverage_rules_raw.json       (면책기간, 감액정보, gap_alerts)
  - data/별표_parsed/*.json            (주요 별표 목록)

출력:
  - data/agent_data/comparison_matrix.json
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
ENRICHED = DATA / "약관_enriched"
PREMIUMS = DATA / "premiums"
COVERAGE = DATA / "coverage_rules_raw.json"
APPENDIX = DATA / "별표_parsed"
OUTPUT   = DATA / "agent_data" / "comparison_matrix.json"

# ── 상품 코드 ↔ 보험료 파일 매핑 ──────────────────────────────────
PREMIUM_FILE_MAP = {
    "KL0420": "착한암보험_전체.jsonl",
    "KL0490": "하이파이브연금_전체.jsonl",
    "KL0810": "KB골든라이프_치매_전체.jsonl",
    "KL1041": "대중교통안심보험_전체.jsonl",
    "KL1042": "지켜주는교통안심보험_전체.jsonl",
    "KL1044": "KB골든라이프_상해_전체.jsonl",
    "KL1060": "KB세번의약속e연금_미보증_전체.jsonl",  # 미보증+보증 둘 다 참조
    "KL1602": "KB달러평생보장_간편_전체.jsonl",
    "KL1603": "KB달러평생보장_일반_전체.jsonl",
    "KL1606": "KB소득보장보험_전체.jsonl",
    "KL1607": "KB정기보험_전체.jsonl",
    "KL1608": "KB종신보험_간편심사_전체.jsonl",
    "KL1609": "KB종신보험_일반심사_전체.jsonl",
    "KL1611": "착한정기보험II_전체.jsonl",
    "KL1616": "KB약속플러스종신_일반_전체.jsonl",
    "KL1617": "KB약속플러스종신_간편_전체.jsonl",
    "KLT028": "e건강보험_일반심사_전체.jsonl",
    "KLT029": "e건강보험_간편심사355_전체.jsonl",
}

# KL1060 보증형도 병합
KL1060_EXTRA = "KB세번의약속e연금_보증_전체.jsonl"

# ── 상품명 매핑 ──────────────────────────────────────────────────
PROD_NAMES = {
    "KL0420": "착한암보험",
    "KL0490": "하이파이브연금",
    "KL0810": "골든라이프치매",
    "KL1041": "대중교통안심",
    "KL1042": "교통안심",
    "KL1044": "골든라이프상해",
    "KL1060": "세번의약속연금",
    "KL1602": "달러평생보장간편",
    "KL1603": "달러평생보장일반",
    "KL1606": "소득보장",
    "KL1607": "정기보험",
    "KL1608": "종신간편",
    "KL1609": "종신일반",
    "KL1611": "착한정기II",
    "KL1616": "약속플러스종신일반",
    "KL1617": "약속플러스종신간편",
    "KLT028": "e건강일반",
    "KLT029": "e건강간편",
}

# ── 1. product_type 분류 ──────────────────────────────────────────
def classify_product_type(code: str, name: str) -> str:
    n = name + PROD_NAMES.get(code, "")
    if "종신" in n:
        return "종신"
    if "정기" in n:
        return "정기"
    if "암" in n:
        return "암"
    if "건강" in n:
        return "건강"
    if "연금" in n:
        return "연금"
    if "치매" in n:
        return "건강"
    if "상해" in n or "교통" in n or "안심" in n:
        return "상해"
    if "소득" in n:
        return "소득보장"
    if "달러" in n:
        return "종신"
    return "기타"


# ── 2. underwriting_type ────────────────────────────────────────
def classify_underwriting(code: str, name: str) -> str:
    n = name + PROD_NAMES.get(code, "")
    if "간편" in n:
        return "간편심사"
    if "무심사" in n:
        return "무심사"
    return "일반심사"


# ── 3. currency ──────────────────────────────────────────────────
def classify_currency(code: str, name: str, premium_sample: dict | None) -> str:
    if premium_sample and premium_sample.get("currency") == "USD":
        return "USD"
    if "달러" in name or "달러" in PROD_NAMES.get(code, ""):
        return "USD"
    return "KRW"


# ── 4-6. premium 기반 축 추출 ────────────────────────────────────
def extract_premium_axes(code: str) -> dict:
    """
    Returns:
      insurance_period, payment_period_options, entry_age_range
    """
    fname = PREMIUM_FILE_MAP.get(code)
    if not fname:
        return {"insurance_period": "N/A", "payment_period_options": [], "entry_age_range": {"min": None, "max": None}}

    fpath = PREMIUMS / fname
    ages = set()
    ins_terms = set()
    pay_terms = set()
    sample = None

    def _read(p):
        nonlocal sample
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if sample is None:
                    sample = rec
                ages.add(rec.get("age"))
                it = rec.get("insuranceTerm")
                if it is not None:
                    ins_terms.add(str(it))
                pt = rec.get("paymentTerm")
                if pt is not None:
                    pay_terms.add(str(pt))

    if fpath.exists():
        _read(fpath)

    # KL1060: merge 보증형
    if code == "KL1060":
        extra = PREMIUMS / KL1060_EXTRA
        if extra.exists():
            _read(extra)

    # Normalize insurance_period
    def _norm_term(t: str) -> str:
        if t == "종신":
            return "종신"
        # Pure numeric → N년만기
        if t.isdigit():
            return f"{t}년만기"
        # Already has 세 or 년 suffix
        if t.endswith("세") or t.endswith("년"):
            return f"{t}만기"
        return t

    if ins_terms:
        normed = sorted(set(_norm_term(t) for t in ins_terms))
        insurance_period = "/".join(normed)
    else:
        # 연금 등 insuranceTerm이 null인 경우
        product_name = sample.get("product", "") if sample else ""
        if "연금" in product_name:
            insurance_period = "연금지급형(종신/확정)"
        else:
            insurance_period = "N/A"

    # Normalize payment terms
    def _norm_pay(t: str) -> str:
        if t.isdigit():
            return f"{t}년납"
        return t

    pay_list = sorted(set(_norm_pay(t) for t in pay_terms),
                      key=lambda x: (not x.endswith("년납"), x))

    valid_ages = sorted(a for a in ages if a is not None)
    age_range = {"min": valid_ages[0], "max": valid_ages[-1]} if valid_ages else {"min": None, "max": None}

    return {
        "insurance_period": insurance_period,
        "payment_period_options": pay_list,
        "entry_age_range": age_range,
        "_sample": sample,
    }


# ── 7-8. renewable / has_refund ──────────────────────────────────
def derive_renewable_refund(code: str, enriched: dict, premium_sample: dict | None) -> tuple[bool, bool]:
    full_name = enriched.get("product", "") + " " + PROD_NAMES.get(code, "")

    renewable = "갱신" in full_name
    # Also check premium variants for 갱신
    if premium_sample:
        for v in premium_sample.get("variants", []):
            if "갱신" in v.get("name", ""):
                renewable = True

    # has_refund: 대부분 true, 미지급형이 있으면 false (일부지급형은 있음)
    has_refund = True
    if "미지급형" in full_name:
        has_refund = False  # 해약환급금 미지급형
    # Check variants for 미지급형
    if premium_sample:
        variant_names = [v.get("name", "") for v in premium_sample.get("variants", [])]
        # If there are ONLY 미지급형 variants, has_refund = False
        # If mixed, note it but has_refund = True (standard exists)
        pass

    return renewable, has_refund


# ── 9. main_coverage ─────────────────────────────────────────────
def extract_main_coverage(enriched: dict) -> str:
    """제8조(보험금의 지급사유) 또는 제3조(보장내용) 요약 추출."""
    candidates = []
    for s in enriched.get("sections", []):
        if s.get("type") != "주계약":
            continue
        title = s.get("title", "")
        jo = str(s.get("조", ""))
        summary = s.get("summary", "")
        # 보험금 지급사유 우선
        if "보험금" in title and ("지급사유" in title or "지급에" in title):
            candidates.append((0, summary))
        elif "보장내용" in title:
            candidates.append((1, summary))
        elif jo == "제8조":
            candidates.append((2, summary))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1][:200]

    # Fallback: first 주계약 section with 보험금 in summary
    for s in enriched.get("sections", []):
        if s.get("type") != "주계약":
            continue
        summary = s.get("summary", "")
        if "보험금" in summary or "지급" in summary:
            return summary[:200]

    return "정보 없음"


# ── 10. rider_count ──────────────────────────────────────────────
def count_riders(enriched: dict) -> int:
    """특약 type section에서 distinct 관 값 수로 추정."""
    rider_kwans = set()
    for s in enriched.get("sections", []):
        if s.get("type") == "특약":
            kwan = s.get("관", "")
            # '관' that contain '특약' indicate distinct riders
            rider_kwans.add(kwan)

    # If no 관 distinction, count by looking at 제1조 titles in 특약
    if not rider_kwans or rider_kwans == {""}:
        rider_titles = set()
        for s in enriched.get("sections", []):
            if s.get("type") == "특약":
                jo = str(s.get("조", ""))
                if "제1조" in jo or "목적" in s.get("title", ""):
                    rider_titles.add(s.get("title", ""))
        return max(len(rider_titles), 1) if any(s.get("type") == "특약" for s in enriched.get("sections", [])) else 0

    return len(rider_kwans)


# ── 11-12. immunity_period, reduction_info ───────────────────────
def extract_immunity_reduction(coverage_rules: dict, code: str) -> tuple[str, str]:
    entry = coverage_rules.get(code, {})
    coverages = entry.get("coverages", [])

    immunity_parts = []
    reduction_parts = []

    for cov in coverages:
        ctype = cov.get("type", "")
        for ip in cov.get("immunity_periods", []):
            cond = ip.get("condition", "")
            period = ip.get("period", "")
            immunity_parts.append(f"{ctype} {cond}: {period}")

        for rd in cov.get("reductions", []):
            cond = rd.get("condition", "")
            ratio = rd.get("ratio", "")
            period = rd.get("period", "")
            reduction_parts.append(f"{ctype} {cond} → {ratio}")

    immunity_summary = "; ".join(immunity_parts) if immunity_parts else "없음"
    reduction_summary = "; ".join(reduction_parts[:5]) if reduction_parts else "없음"
    if len(reduction_parts) > 5:
        reduction_summary += f" 외 {len(reduction_parts)-5}건"

    return immunity_summary, reduction_summary


# ── 13. key_appendices ───────────────────────────────────────────
def extract_appendices(code: str) -> list[str]:
    fpath = APPENDIX / f"{code}.json"
    if not fpath.exists():
        return []
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = []
    for ap in data.get("appendices", []):
        aid = ap.get("appendix_id", "")
        title = ap.get("title", "")
        result.append(f"{aid}: {title}")
    return result


# ── 14. target_audience ──────────────────────────────────────────
def infer_target_audience(code: str, product_type: str, uw_type: str,
                          currency: str, age_range: dict, name: str) -> str:
    parts = []

    if age_range.get("min") and age_range.get("max"):
        parts.append(f"{age_range['min']}~{age_range['max']}세")

    if uw_type == "간편심사":
        parts.append("유병자/고령자 (간편심사)")
    elif uw_type == "일반심사":
        parts.append("건강한 일반 가입자")

    if currency == "USD":
        parts.append("달러자산 선호 고객")

    type_map = {
        "종신": "사망보장 필요 고객, 상속 준비",
        "정기": "일정기간 사망보장 필요 고객 (가장 경제활동기)",
        "암": "암 보장 집중 필요 고객",
        "건강": "질병/건강 종합보장 필요 고객",
        "연금": "노후 연금 준비 고객",
        "상해": "상해/교통사고 보장 필요 고객",
        "소득보장": "소득 상실 리스크 대비 고객",
    }
    if product_type in type_map:
        parts.append(type_map[product_type])

    if "치매" in name:
        parts.append("치매 보장 필요 고령층")
    if "교통" in name or "대중교통" in name:
        parts.append("대중교통 이용 빈도 높은 고객")

    return ", ".join(parts)


# ── 15. critical_alerts ──────────────────────────────────────────
def extract_critical_alerts(coverage_rules: dict, code: str) -> list[str]:
    entry = coverage_rules.get(code, {})
    return entry.get("gap_alerts_critical", [])


# ══════════════════════════════════════════════════════════════════
#                          MAIN
# ══════════════════════════════════════════════════════════════════
def main():
    # Load shared data
    with open(COVERAGE, "r", encoding="utf-8") as f:
        coverage_rules = json.load(f)

    products = sorted(PROD_NAMES.keys())
    matrix = {"_meta": {
        "description": "18개 KB라이프 보험상품 비교 매트릭스",
        "axes_count": 15,
        "product_count": len(products),
        "generated_by": "scripts/build_comparison_matrix.py",
    }, "products": {}}

    for code in products:
        short_name = PROD_NAMES[code]
        print(f"  Processing {code} ({short_name})...")

        # Load enriched
        enriched_path = ENRICHED / f"{code}.json"
        with open(enriched_path, "r", encoding="utf-8") as f:
            enriched = json.load(f)

        full_name = enriched.get("product", short_name)

        # Premium axes
        pax = extract_premium_axes(code)
        premium_sample = pax.pop("_sample", None)

        # Derive axes
        product_type = classify_product_type(code, full_name)
        uw_type = classify_underwriting(code, full_name)
        currency = classify_currency(code, full_name, premium_sample)
        renewable, has_refund = derive_renewable_refund(code, enriched, premium_sample)
        main_cov = extract_main_coverage(enriched)
        rider_cnt = count_riders(enriched)
        immunity, reduction = extract_immunity_reduction(coverage_rules, code)
        appendices = extract_appendices(code)
        alerts = extract_critical_alerts(coverage_rules, code)
        target = infer_target_audience(code, product_type, uw_type, currency,
                                       pax["entry_age_range"], full_name)

        matrix["products"][code] = {
            "prodCode": code,
            "product_name": full_name,
            "short_name": short_name,
            "product_type": product_type,
            "underwriting_type": uw_type,
            "currency": currency,
            "insurance_period": pax["insurance_period"],
            "payment_period_options": pax["payment_period_options"],
            "entry_age_range": pax["entry_age_range"],
            "renewable": renewable,
            "has_refund": has_refund,
            "main_coverage": main_cov,
            "rider_count": rider_cnt,
            "immunity_period": immunity,
            "reduction_info": reduction,
            "key_appendices": appendices,
            "target_audience": target,
            "critical_alerts": alerts,
        }

    # Write output
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(matrix, f, ensure_ascii=False, indent=2)

    print(f"\n  ✓ Written {OUTPUT}")
    print(f"    {len(matrix['products'])} products × 15 axes")


if __name__ == "__main__":
    main()
