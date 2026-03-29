"""
금융감독원 보험다모아 정기보험 스크래퍼
http://203.229.168.79/tempIns/tempInsList.knia

Playwright로 세션 획득 후, HTTP 직접 요청으로 10건씩 병렬 엑셀 다운로드.

사용법:
    python scrape_temp_ins.py [--age-start 20] [--age-end 64] [--batch 10] [--output data/temp_ins]
"""

import asyncio
import argparse
import os
import time
import urllib.parse
from pathlib import Path

import aiohttp
from playwright.async_api import async_playwright

URL = "http://203.229.168.79/tempIns/tempInsList.knia"
DOWNLOAD_URL = "http://203.229.168.79/spreadsheet/download.knia"

GENDERS = [
    {"sex": "M", "sexNm": "GRNT_ENTR_AMT_M", "sexType": "M", "name": "남"},
    {"sex": "F", "sexNm": "GRNT_ENTR_AMT_F", "sexType": "F", "name": "여"},
]

# 엑셀 다운로드 POST에 필요한 고정 파라미터 (캡처에서 추출)
HEADER_HTML = (
    "<thead><tr>"
    "<th>번호</th><th>회사명</th><th>상품명</th><th>보장명</th>"
    "<th>보장금액</th><th>보험료(원)</th><th>가입연령(세)</th>"
    "<th>비고</th><th>가입형태</th><th>URL</th><th>전화번호</th>"
    "</tr></thead>"
)

BODY_HTML = (
    "<tbody><tr>"
    '<td data-name="RNK01"></td>'
    '<td data-name="INSR_CMPY_NM"></td>'
    '<td data-name="PRDT_NM"></td>'
    '<td data-name="SCRT_NM"></td>'
    '<td data-name="GRNT_ENTR_AMT"></td>'
    '<td data-name="PREM_AMT"></td>'
    '<td data-name="ENTR_PSBL_AGE"></td>'
    '<td data-name="RMK"></td>'
    '<td data-name="ENTR_TYPE_NM"></td>'
    '<td data-name="URL"></td>'
    '<td data-name="TEL_NO"></td>'
    "</tr></tbody>"
)

MERGE_KEY = "RNK01,INSR_CMPY_NM,PRDT_NM"
MERGE_COL = "RNK01,INSR_CMPY_NM,PRDT_NM,SCRT_NM,GRNT_ENTR_AMT,PREM_AMT,ENTR_PSBL_AGE,RMK,ENTR_TYPE_NM,URL,TEL_NO"


def get_filename(age, gender_name):
    return f"temp_{age}세_{gender_name}.xls"


def build_download_params(age, gender):
    """엑셀 다운로드 POST 파라미터 생성"""
    birthday = f"{2026 - age}0101"
    conditions = f"보험료구분: 낮은보험료순|성별: {'남자' if gender['sex'] == 'M' else '여자'}|보험나이: {age}"

    return {
        "filename": urllib.parse.quote("정기보험", encoding="utf-8"),
        "queryId": "tempIns.selectTempInsExcelList",
        "conditions": urllib.parse.quote(conditions, encoding="utf-8"),
        "header": urllib.parse.quote(HEADER_HTML, encoding="utf-8"),
        "body": urllib.parse.quote(BODY_HTML, encoding="utf-8"),
        "readable": "false",
        "prdtCd": "",
        "prdtNm": "",
        "sex": gender["sex"],
        "sexNm": gender["sexNm"],
        "insrCmpyNm": "",
        "enterType": "A",
        "page": "1",
        "sexDiv": "",
        "sexType": gender["sexType"],
        "birthday": birthday,
        "age": str(age),
        "ordering": "ASC",
        "renewalCd": "",
        "mergeKey": MERGE_KEY,
        "mergeCol": MERGE_COL,
    }


async def get_session_cookies(p):
    """Playwright로 사이트 접속하여 세션 쿠키 획득"""
    print("[*] 세션 쿠키 획득 중...")
    browser = await p.chromium.launch(headless=False, channel="chrome")
    context = await browser.new_context(viewport={"width": 1400, "height": 900})

    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
    )

    page = await context.new_page()

    # MBuster 차단
    async def block_mbuster(route):
        url = route.request.url
        if "Mbuster_T.jsp" in url:
            await route.fulfill(status=200, content_type="text/html", body="<!-- blocked -->")
        elif "MBusterAPI" in url:
            await route.fulfill(
                status=200,
                content_type="application/json",
                body='{"result":"OK","code":"0000"}',
            )
        else:
            await route.continue_()

    await page.route("**/mbuster/**", block_mbuster)
    await page.route("**/MBusterAPI/**", block_mbuster)

    await page.goto(URL, timeout=60000)
    await page.wait_for_load_state("networkidle", timeout=30000)
    await asyncio.sleep(2)

    # 쿠키 추출
    cookies = await context.cookies()
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    # 페이지가 정상 로드됐는지 확인
    content = await page.content()
    if "searchForm" not in content and len(content) < 5000:
        print("[!] 페이지 로드 실패 — 차단됐을 수 있습니다.")
        await browser.close()
        return None, None

    print(f"[+] 세션 쿠키 획득 완료 ({len(cookies)}개)")
    await browser.close()
    return cookie_str, {c["name"]: c["value"] for c in cookies}


async def download_one(session, age, gender, output_dir, cookie_str, semaphore):
    """단일 조합 엑셀 다운로드"""
    filename = get_filename(age, gender["name"])
    filepath = output_dir / filename

    if filepath.exists() and filepath.stat().st_size > 0:
        return age, gender["name"], "skip"

    params = build_download_params(age, gender)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookie_str,
        "Origin": "http://203.229.168.79",
        "Referer": "http://203.229.168.79/tempIns/tempInsList.knia",
    }

    async with semaphore:
        try:
            async with session.post(DOWNLOAD_URL, data=params, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return age, gender["name"], f"error_status_{resp.status}"

                data = await resp.read()
                if len(data) < 100:
                    return age, gender["name"], f"empty ({len(data)}B)"

                filepath.write_bytes(data)
                return age, gender["name"], f"ok ({len(data)}B)"
        except Exception as e:
            return age, gender["name"], f"error: {str(e)[:80]}"


async def main():
    parser = argparse.ArgumentParser(description="금감원 보험다모아 정기보험 스크래퍼")
    parser.add_argument("--age-start", type=int, default=20, help="시작 나이 (기본: 20)")
    parser.add_argument("--age-end", type=int, default=64, help="끝 나이 (기본: 64)")
    parser.add_argument("--batch", type=int, default=10, help="동시 다운로드 수 (기본: 10)")
    parser.add_argument("--output", type=str, default="data/temp_ins", help="저장 폴더")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1단계: Playwright로 세션 쿠키 획득
    async with async_playwright() as p:
        cookie_str, cookie_dict = await get_session_cookies(p)
        if not cookie_str:
            return

    # 2단계: aiohttp로 병렬 다운로드
    start_time = time.time()
    semaphore = asyncio.Semaphore(args.batch)

    # 작업 목록 생성
    tasks_list = []
    for gender in GENDERS:
        for age in range(args.age_start, args.age_end + 1):
            tasks_list.append((age, gender))

    total = len(tasks_list)
    print(f"\n[*] 총 {total}건 다운로드 시작 (동시 {args.batch}건)")
    print(f"    나이: {args.age_start}~{args.age_end}세, 성별: 남/여")
    print(f"    저장: {output_dir}/\n")

    success, skipped, errors = 0, 0, 0

    async with aiohttp.ClientSession() as session:
        tasks = [
            download_one(session, age, gender, output_dir, cookie_str, semaphore)
            for age, gender in tasks_list
        ]

        for i, coro in enumerate(asyncio.as_completed(tasks)):
            age, gender_name, result = await coro
            label = f"[{i+1}/{total}] {age}세 {gender_name}"

            if result.startswith("ok"):
                success += 1
                print(f"{label} → 다운로드 완료 {result}")
            elif result == "skip":
                skipped += 1
                print(f"{label} → 이미 있음")
            else:
                errors += 1
                print(f"{label} → {result}")

    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"완료! 소요시간: {elapsed:.1f}초")
    print(f"  성공: {success}건")
    print(f"  스킵: {skipped}건")
    print(f"  에러: {errors}건")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())
