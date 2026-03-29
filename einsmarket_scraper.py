"""
금융감독원 보험다모아(e-insmarket.or.kr) 암보험 스크래퍼

Playwright 기반. MBuster 봇 감지 우회 포함.
수집 방식: 갱신구분 x 성별 x 나이 조합별로 폼 제출 → 엑셀 다운로드

사용법:
    python einsmarket_scraper.py [--age-start 20] [--age-end 64] [--delay 2] [--output data/einsmarket]

주의:
    - headless=False 필수 (headless 감지됨)
    - 첫 로드 전에 MBuster intercept 설정하면 페이지 깨짐
    - 같은 IP에서 브라우저 반복 실행하면 누적 차단 → VPN/핫스팟으로 IP 변경
    - F12(DevTools) 절대 열지 말 것
"""

import asyncio
import argparse
import os
import re
import time
from pathlib import Path
from playwright.async_api import async_playwright

URL = "https://e-insmarket.or.kr/cancerIns/cancerInsList.knia"

RENEW_TYPES = [
    {"id": "renewTypeA", "value": "C1", "name": "비갱신형"},
    {"id": "renewTypeB", "value": "C2", "name": "갱신형"},
]

GENDERS = [
    {"id": "sexM", "value": "1", "name": "남"},
    {"id": "sexL", "value": "2", "name": "여"},
]


def get_filename(age, gender_name, renew_name):
    return f"cancer_{age}세_{gender_name}_{renew_name}.xls"


def parse_total_count(html):
    """총 <strong>12</strong> 건 형태에서 건수 파싱"""
    m = re.search(r'총\s*(?:<[^>]+>)?\s*(\d+)\s*(?:<[^>]+>)?\s*건', html)
    return int(m.group(1)) if m else -1


async def setup_browser(p):
    """브라우저 시작 + webdriver 제거 + 첫 로드(MBuster 자연 통과)"""
    browser = await p.chromium.launch(headless=False, channel="chrome")
    context = await browser.new_context(viewport={"width": 1400, "height": 900})

    # navigator.webdriver 제거 — MBuster selenium 감지 우회
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
    )

    page = await context.new_page()

    # 첫 로드: MBuster가 정상 동작하여 세션 인증
    print("[*] 페이지 로드 중 (MBuster 자연 통과)...")
    await page.goto(URL, timeout=60000)
    await page.wait_for_load_state("networkidle", timeout=60000)
    await asyncio.sleep(3)

    # 차단 감지: searchForm이 없으면 IP 차단된 것
    has_form = await page.query_selector("#searchForm")
    if not has_form:
        content = await page.content()
        print(f"[!] 차단 감지 — 페이지 크기: {len(content)} bytes")
        print("[!] VPN이나 모바일 핫스팟으로 IP를 변경한 뒤 다시 시도하세요.")
        await browser.close()
        return None, None, None

    # 이후 폼 제출 시 MBuster API 가로채기
    async def handle_mbuster(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body='{"result":"OK","code":"0000"}',
        )

    await page.route("**/MBusterAPI/**", handle_mbuster)
    print("[+] MBuster intercept 설정 완료")

    return browser, context, page


async def scrape_one(page, age, gender, renew_type, output_dir, delay):
    """단일 조합 스크래핑: 폼 세팅 → 제출 → 엑셀 다운로드"""
    gender_name = gender["name"]
    renew_name = renew_type["name"]
    filename = get_filename(age, gender_name, renew_name)
    filepath = output_dir / filename

    # 이미 받은 파일 스킵
    if filepath.exists() and filepath.stat().st_size > 0:
        return "skip"

    birthday = f"{2026 - age}0101"

    # 폼 필드 세팅 (JS evaluate)
    await page.evaluate(f"""() => {{
        // 생년월일 + 나이
        document.querySelector('#insStartDtPicker').value = '{2026 - age}-01-01';
        document.querySelector('#age').value = '{age}';

        // 성별 체크박스
        const sexM = document.querySelector('#sexM');
        const sexL = document.querySelector('#sexL');
        sexM.checked = {'true' if gender["value"] == "1" else 'false'};
        sexL.checked = {'true' if gender["value"] == "2" else 'false'};

        // 갱신구분 체크박스
        const renewA = document.querySelector('#renewTypeA');
        const renewB = document.querySelector('#renewTypeB');
        renewA.checked = {'true' if renew_type["id"] == "renewTypeA" else 'false'};
        renewB.checked = {'true' if renew_type["id"] == "renewTypeB" else 'false'};
    }}""")

    # "상품비교하기" 클릭
    try:
        await page.click("button.btn_type04")
        await page.wait_for_load_state("networkidle", timeout=30000)
        await asyncio.sleep(2)
    except Exception as e:
        return f"error_click: {e}"

    # 총 건수 파싱
    content = await page.content()
    total = parse_total_count(content)

    if total == 0:
        return "no_data"
    elif total < 0:
        # 결과 파싱 실패 — 차단 또는 페이지 오류
        debug_path = output_dir / f"debug_{age}_{gender_name}_{renew_name}.html"
        debug_path.write_text(content, encoding="utf-8")
        return "parse_error"

    # 엑셀 다운로드: exceldown() 호출 → 다운로드 이벤트 캡처
    try:
        async with page.expect_download(timeout=15000) as download_info:
            await page.evaluate("exceldown()")
        download = await download_info.value
        await download.save_as(str(filepath))
    except Exception as e:
        return f"error_download: {e}"

    await asyncio.sleep(delay)
    return "ok"


async def main():
    parser = argparse.ArgumentParser(description="금감원 보험다모아 암보험 스크래퍼")
    parser.add_argument("--age-start", type=int, default=20, help="시작 나이 (기본: 20)")
    parser.add_argument("--age-end", type=int, default=64, help="끝 나이 (기본: 64)")
    parser.add_argument("--delay", type=float, default=2, help="요청 간 대기 초 (기본: 2)")
    parser.add_argument("--output", type=str, default="data/einsmarket", help="저장 폴더")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    success, skipped, errors, no_data = 0, 0, 0, 0

    async with async_playwright() as p:
        browser, context, page = await setup_browser(p)
        if not page:
            return

        total_combos = len(RENEW_TYPES) * len(GENDERS) * (args.age_end - args.age_start + 1)
        done = 0

        try:
            for renew_type in RENEW_TYPES:
                for gender in GENDERS:
                    for age in range(args.age_start, args.age_end + 1):
                        done += 1
                        label = f"{age}세 {gender['name']} {renew_type['name']}"
                        print(f"[{done}/{total_combos}] {label}", end=" → ")

                        try:
                            result = await scrape_one(page, age, gender, renew_type, output_dir, args.delay)
                        except Exception as e:
                            err_str = str(e)
                            # 연결 끊김 → 브라우저 재시작
                            if "Target closed" in err_str or "closed" in err_str.lower():
                                print(f"연결 끊김! 브라우저 재시작...")
                                try:
                                    await browser.close()
                                except Exception:
                                    pass
                                browser, context, page = await setup_browser(p)
                                if not page:
                                    print("[!] 재시작 실패. 종료합니다.")
                                    return
                                result = "error_reconnect"
                            else:
                                # 기타 에러 → go_back으로 복구 시도
                                try:
                                    await page.go_back(timeout=10000)
                                    await asyncio.sleep(2)
                                except Exception:
                                    pass
                                result = f"error: {err_str[:80]}"

                        if result == "ok":
                            success += 1
                            print(f"다운로드 완료")
                        elif result == "skip":
                            skipped += 1
                            print(f"이미 있음 (스킵)")
                        elif result == "no_data":
                            no_data += 1
                            print(f"결과 0건")
                        else:
                            errors += 1
                            print(f"{result}")

        finally:
            elapsed = time.time() - start_time
            print(f"\n{'='*50}")
            print(f"완료! 소요시간: {elapsed:.0f}초")
            print(f"  성공: {success}건")
            print(f"  스킵: {skipped}건")
            print(f"  0건:  {no_data}건")
            print(f"  에러: {errors}건")
            print(f"{'='*50}")

            try:
                await browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
