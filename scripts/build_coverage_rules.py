"""
coverage_rules.json 구축 스크립트
coverage_rules_raw.json + 용어정의(term_definitions) + mandatory_disclosure 통합
"""
import json, os, re, glob

BASE = os.path.join(os.path.dirname(__file__), '..')
ENRICHED_DIR = os.path.join(BASE, 'data', '약관_enriched')
RAW_RULES = os.path.join(BASE, 'data', 'coverage_rules_raw.json')
OUTPUT = os.path.join(BASE, 'data', 'agent_data', 'coverage_rules.json')

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)


def extract_term_definitions(enriched_path):
    """용어정의 조항에서 주요 보험 용어 추출"""
    data = json.load(open(enriched_path, 'r', encoding='utf-8'))
    terms = {}

    for section in data['sections']:
        if '용어' not in section.get('title', '') or '정의' not in section.get('title', ''):
            continue

        text = section['text']
        sec_type = section['type']

        # 패턴: "가. 용어: 정의" 또는 "가. 용어 : 정의"
        # 또는 "암"이라 함은 ... 을 말합니다

        # 패턴1: 가/나/다. 용어: 정의
        for m in re.finditer(r'[가-힣]\.\s*([가-힣A-Za-z\s]+?):\s*(.+?)(?=\n[가-힣]\.|$)', text, re.DOTALL):
            term_name = m.group(1).strip()
            term_def = m.group(2).strip()[:200]
            if len(term_name) < 20:
                terms[term_name] = {
                    'definition': term_def,
                    'scope': sec_type,
                    'source': section['조']
                }

        # 패턴2: "XX"이라(라) 함은 ... 말합니다
        for m in re.finditer(r'"([^"]+)"\s*(?:이라|라)\s*함은\s*(.+?)말합니다', text, re.DOTALL):
            term_name = m.group(1).strip()
            term_def = m.group(2).strip()[:200]
            if len(term_name) < 30:
                terms[term_name] = {
                    'definition': term_def + '말합니다',
                    'scope': sec_type,
                    'source': section['조']
                }

    # 암 정의 조항 (제3조~제7조 등)
    for section in data['sections']:
        title = section.get('title', '')
        if '정의' in title and '진단' in title:
            for m in re.finditer(r'"([^"]+)"\s*(?:이라|라)\s*함은\s*(.+?)말합니다', section['text'], re.DOTALL):
                term_name = m.group(1).strip()
                term_def = m.group(2).strip()[:300]
                terms[term_name] = {
                    'definition': term_def + '말합니다',
                    'scope': section['type'],
                    'source': section['조']
                }

    return terms


def build_mandatory_disclosure(product_name, gap_alerts):
    """필수 고지사항 생성"""
    disclosures = []

    # 공통 면책 문구
    disclosures.append("본 정보는 참고용이며, 보험 가입은 전문 설계사와 상담하시기 바랍니다.")

    # 상품 특성별 추가 고지
    if '간편심사' in product_name:
        disclosures.append("간편심사형 상품은 일반심사형 대비 보험료가 높을 수 있습니다.")
    if '달러' in product_name:
        disclosures.append("달러 상품은 환율 변동에 따라 원화 환산 금액이 달라질 수 있습니다.")
    if '갱신형' in product_name:
        disclosures.append("갱신형 상품은 갱신 시 보험료가 인상될 수 있습니다.")
    if '해약환급금 미지급' in product_name:
        disclosures.append("해약환급금 미지급형 상품은 중도 해지 시 환급금이 없습니다.")
    if '해약환급금 일부지급' in product_name:
        disclosures.append("해약환급금 일부지급형은 납입기간 중 해지 시 환급금이 일반형 대비 적습니다.")

    return disclosures


def main():
    raw = json.load(open(RAW_RULES, 'r', encoding='utf-8'))
    enriched_files = sorted(glob.glob(os.path.join(ENRICHED_DIR, '*.json')))

    result = {}

    for ef in enriched_files:
        prod_code = os.path.basename(ef).replace('.json', '')
        enriched = json.load(open(ef, 'r', encoding='utf-8'))
        product_name = enriched['product']

        # 용어 정의 추출
        terms = extract_term_definitions(ef)

        # raw rules 가져오기
        raw_entry = raw.get(prod_code, {})

        # mandatory disclosure 생성
        gap_alerts = raw_entry.get('gap_alerts_critical', [])
        disclosures = build_mandatory_disclosure(product_name, gap_alerts)

        result[prod_code] = {
            'prodCode': prod_code,
            'product': product_name,
            'coverages': raw_entry.get('coverages', []),
            'gap_alerts': {
                'critical': gap_alerts,
                'contextual': []  # 추후 질문 키워드 매칭으로 채움
            },
            'mandatory_disclosure': disclosures,
            'term_definitions': terms,
        }

        print(f'  {prod_code}: 용어 {len(terms)}개, 면책고지 {len(disclosures)}개, 경고 {len(gap_alerts)}개')

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'\n→ {OUTPUT} 저장 완료')


if __name__ == '__main__':
    main()
