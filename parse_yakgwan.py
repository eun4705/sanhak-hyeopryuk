"""
약관 PDF 텍스트 → 조(article) 단위 분할 파이프라인 (1단계)

입력: data/약관_텍스트/*.txt
출력: data/약관_parsed/<상품코드>.json
"""

import json
import os
import re
import glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "data", "약관_텍스트")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "약관_parsed")

# 상품코드-이름 매핑
PRODUCT_MAP = {
    "KL0420": "KB 착한암보험 무배당",
    "KL0490": "KB 하이파이브평생연금보험 무배당",
    "KL1041": "KB 지켜주는 대중교통안심보험 무배당",
    "KL1042": "KB 지켜주는 교통안심보험 무배당",
    "KL1611": "KB 착한정기보험II 무배당",
    "KLT028": "KB 딱좋은 e-건강보험 무배당(갱신형)(일반심사형)(해약환급금 미지급형)",
    "KLT029": "KB 딱좋은 e-건강보험 무배당(갱신형)(간편심사형)(해약환급금 미지급형)",
}

# 제X관 패턴 - 공백/붙어있는 버전 모두
RE_GWAN = re.compile(r'^제\s*(\d+)\s*관\s*(.+)$')
# 제X조 패턴 - 공백 있는 버전
RE_JO_SPACED = re.compile(r'^제(\d+)조\s+(.+)$')
# 제X조 패턴 - 괄호 버전: 제1조(목적) 또는 제1조(목적및용어의정의)
RE_JO_PAREN = re.compile(r'^제(\d+)\s*조\((.+?)\)(.*)$')
# 제X조 패턴 - 대괄호 버전: 제1조[목적] (특약 본문에서 사용)
RE_JO_BRACKET = re.compile(r'^제(\d+)\s*조\[(.+?)\](.*)$')
# 제X조 패턴 - 완전히 붙어있는 버전: 제1조목적
RE_JO_NOSPACE = re.compile(r'^제(\d+)조([가-힣].{1,30})$')
# 특약/특별약관 본문 시작 패턴
RE_TEUKAK_START = re.compile(r'^(.+?(?:특약|특별약관))\s*약관?\s*$')
# 특별약관 개별 본문 시작: 특별약관명 뒤에 바로 제1조가 나오는 패턴
RE_TEUKBYUL_HEADER = re.compile(r'^(.+특별약관)\s*$')
# 주계약 시작 패턴 (공백/붙어있는 버전 모두)
RE_MAIN_START = re.compile(r'^제\s*1\s*관\s*목적\s*(및|과)\s*용어의\s*정의$')


def extract_prod_code(filename: str) -> str:
    """파일명에서 상품코드 추출"""
    match = re.match(r'^(KL\w?\d+)', filename)
    return match.group(1) if match else filename.split("_")[0]


def clean_text(text: str) -> str:
    """PAGE_BREAK 제거, 페이지 번호 라인 제거"""
    text = text.replace("---PAGE_BREAK---", "\n")
    # '현재【X/Y】페이지 입니다.' 패턴 제거
    text = re.sub(r'현재【\d+/\d+】페이지\s*입니다\.?', '', text)
    return text


def find_main_contract_start(lines: list[str]) -> int | None:
    """주계약 본문의 시작 라인 번호 찾기.
    제1관 뒤에 제1조가 나오고, 그 뒤 5줄 내에 30자 이상 본문 문장이 나오는 첫 위치."""
    for i, line in enumerate(lines):
        if not RE_MAIN_START.match(line.strip()):
            continue
        # 다음 10줄 내에 제1조 찾기
        for j in range(i + 1, min(i + 10, len(lines))):
            t = lines[j].strip()
            if re.match(r'^제\s*1\s*조', t):
                # 제1조 다음 5줄 내에 30자 이상 한글 문장?
                for k in range(j + 1, min(j + 6, len(lines))):
                    u = lines[k].strip()
                    if len(u) > 30 and re.search(r'[가-힣]{10,}', u):
                        return i
                    if u.isdigit():  # 페이지 번호 → 목차
                        break
                break
    return None


def find_teukak_sections(lines: list[str], main_end: int) -> list[dict]:
    """특약/특별약관 본문 시작 위치와 이름 찾기"""
    sections = []
    i = main_end
    while i < len(lines):
        s = lines[i].strip()

        # 패턴1: XX특약약관 (기존 특약)
        m = RE_TEUKAK_START.match(s)
        if m:
            name = m.group(1).strip()
            if name not in ("특약", "특별약관"):
                sections.append({"name": name, "start": i})
                i += 1
                continue

        # 패턴2: XX 특별약관 (e-건강보험 등)
        # 특별약관명 다음 5줄 내에 제1조가 나오면 본문 시작
        m2 = RE_TEUKBYUL_HEADER.match(s)
        if m2:
            name = m2.group(1).strip()
            if name not in ("특약", "특별약관") and len(name) > 5:
                for j in range(i + 1, min(i + 6, len(lines))):
                    t = lines[j].strip()
                    if re.match(r'^제\s*1\s*조', t):
                        sections.append({"name": name, "start": i})
                        break
        i += 1

    # 중복 제거 (같은 start)
    seen = set()
    unique = []
    for sec in sections:
        if sec["start"] not in seen:
            seen.add(sec["start"])
            unique.append(sec)
    sections = unique

    # 각 특약의 끝 = 다음 특약의 시작 (또는 파일 끝)
    for j in range(len(sections)):
        if j + 1 < len(sections):
            sections[j]["end"] = sections[j + 1]["start"]
        else:
            sections[j]["end"] = len(lines)

    return sections


def parse_articles(lines: list[str], start: int, end: int) -> list[dict]:
    """주어진 범위에서 관/조 단위로 분할"""
    articles = []
    current_gwan = ""
    current_jo = None
    current_title = ""
    current_text_lines = []

    def flush():
        if current_jo is not None:
            text = "\n".join(current_text_lines).strip()
            if text:
                articles.append({
                    "관": current_gwan,
                    "조": f"제{current_jo}조",
                    "title": current_title,
                    "text": text,
                })

    for i in range(start, min(end, len(lines))):
        s = lines[i].strip()
        if not s:
            current_text_lines.append("")
            continue

        # 제X관 매칭
        m_gwan = RE_GWAN.match(s)
        if m_gwan:
            current_gwan = f"제{m_gwan.group(1)}관 {m_gwan.group(2).strip()}"
            continue

        # 제X조 매칭 - 여러 패턴 시도
        m_jo = (
            RE_JO_SPACED.match(s)
            or RE_JO_BRACKET.match(s)
            or RE_JO_PAREN.match(s)
            or RE_JO_NOSPACE.match(s)
        )
        if m_jo:
            flush()
            current_jo = int(m_jo.group(1))
            current_title = m_jo.group(2).strip()
            current_text_lines = []
            # 3번째 그룹이 있으면 (괄호/대괄호 뒤 텍스트) 본문으로
            if m_jo.lastindex and m_jo.lastindex >= 3:
                rest = m_jo.group(3).strip()
                if rest:
                    current_text_lines.append(rest)
            continue

        # 일반 텍스트 → 현재 조의 본문
        current_text_lines.append(s)

    flush()
    return articles


def parse_yakgwan(filepath: str) -> dict:
    """약관 텍스트 파일 하나를 파싱"""
    filename = os.path.basename(filepath).replace(".txt", "")
    prod_code = extract_prod_code(filename)
    prod_name = PRODUCT_MAP.get(prod_code, filename)

    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    text = clean_text(text)
    lines = text.split("\n")

    # 1) 주계약 본문 시작점
    main_start = find_main_contract_start(lines)
    if main_start is None:
        print(f"  [WARN] 주계약 시작점 못 찾음: {filename}")
        return {"product": prod_name, "prodCode": prod_code, "sections": []}

    # 2) 주계약 끝 찾기
    # 전략: 제7관 시작 후 조항 번호가 증가하다가 제1조가 다시 나오면 끊기
    # 또는 <별표>, 특약 약관, 특별약관 헤더를 만나면 끊기
    main_end = len(lines)
    in_gwan7 = False
    last_main_jo = main_start
    prev_jo_num = 0
    for i in range(main_start + 1, len(lines)):
        s = lines[i].strip()
        m_gwan = RE_GWAN.match(s)
        if m_gwan and m_gwan.group(1) == "7":
            in_gwan7 = True
            continue

        if in_gwan7:
            m_jo = (RE_JO_SPACED.match(s) or RE_JO_BRACKET.match(s)
                    or RE_JO_PAREN.match(s) or RE_JO_NOSPACE.match(s))
            if m_jo:
                jo_num = int(m_jo.group(1))
                # 조번호가 급격히 떨어지면 (예: 44→1) 특별약관 시작
                if jo_num < prev_jo_num - 5:
                    main_end = last_main_jo + 1
                    # main_end를 조 본문 끝까지 확장
                    for k in range(last_main_jo + 1, min(last_main_jo + 100, len(lines))):
                        t = lines[k].strip()
                        if t.startswith("<별표") or t.startswith("<붙임"):
                            main_end = k
                            break
                        if re.match(r'^특약\s*약관\s*$', t):
                            main_end = k
                            break
                        if "특별약관목차" in t:
                            main_end = k
                            break
                        m3 = RE_TEUKBYUL_HEADER.match(t)
                        if m3 and len(m3.group(1).strip()) > 5:
                            main_end = k
                            break
                    break
                prev_jo_num = jo_num
                last_main_jo = i

            # 별표/특약 등을 만나면 바로 끊기
            if s.startswith("<별표") or s.startswith("<붙임"):
                main_end = i
                break
            if re.match(r'^특약\s*약관\s*$', s):
                main_end = i
                break
            if "특별약관목차" in s:
                main_end = i
                break

    # 3) 주계약 조 단위 파싱
    main_articles = parse_articles(lines, main_start, main_end)
    for art in main_articles:
        art["type"] = "주계약"

    # 4) 특약 파싱
    teukak_sections = find_teukak_sections(lines, main_end)
    teukak_articles = []
    for sec in teukak_sections:
        arts = parse_articles(lines, sec["start"], sec["end"])
        for art in arts:
            art["type"] = "특약"
            art["특약명"] = sec["name"]
        teukak_articles.extend(arts)

    all_sections = main_articles + teukak_articles

    return {
        "product": prod_name,
        "prodCode": prod_code,
        "totalArticles": len(all_sections),
        "sections": all_sections,
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.txt")))
    if not files:
        print(f"입력 파일 없음: {INPUT_DIR}")
        return

    for filepath in files:
        filename = os.path.basename(filepath)
        print(f"파싱 중: {filename}")
        result = parse_yakgwan(filepath)

        prod_code = result["prodCode"]
        outpath = os.path.join(OUTPUT_DIR, f"{prod_code}.json")
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # 통계
        main_count = sum(1 for s in result["sections"] if s["type"] == "주계약")
        teukak_count = sum(1 for s in result["sections"] if s["type"] == "특약")
        teukak_names = set(s.get("특약명", "") for s in result["sections"] if s["type"] == "특약")
        print(f"  → {prod_code}: 주계약 {main_count}조 + 특약 {teukak_count}조 ({len(teukak_names)}개 특약)")
        print(f"  → 저장: {outpath}")
    print("\n완료!")


if __name__ == "__main__":
    main()
