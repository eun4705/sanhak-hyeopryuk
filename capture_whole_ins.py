"""
종합보험 사이트 네트워크 캡처 도구
http://203.229.168.79/wholeIns/wholeInsList.knia

모든 네트워크 요청/응답을 캡처하여 JSON으로 저장.
브라우저가 열리면 수동으로 사이트를 조작하고, 조작이 끝나면 브라우저를 닫으면 됨.

사용법:
    python capture_whole_ins.py [--output capture_whole_ins.json]
"""

import asyncio
import argparse
import json
import time
from playwright.async_api import async_playwright

URL = "http://203.229.168.79/wholeIns/wholeInsList.knia"


async def main():
    parser = argparse.ArgumentParser(description="종합보험 네트워크 캡처")
    parser.add_argument("--output", type=str, default="capture_whole_ins.json", help="저장 파일명")
    args = parser.parse_args()

    captured = []
    request_bodies = {}  # request uid → body 매핑

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context(viewport={"width": 1400, "height": 900})

        # webdriver 제거 (MBuster 대비)
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        page = await context.new_page()

        # === Mbuster_T.jsp 차단 (감지 결과 페이지 로드 방지) ===
        # checkWhite/checkBotIp는 자연 통과시키되, 감지 후 리다이렉트되는 T.jsp만 차단
        async def block_mbuster_t(route):
            url = route.request.url
            if "Mbuster_T.jsp" in url:
                print(f"[MBUSTER] Mbuster_T.jsp 차단됨")
                await route.fulfill(status=200, content_type="text/html", body="<!-- blocked -->")
            elif "MBusterAPI" in url:
                print(f"[MBUSTER] API 우회: {url}")
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"result":"OK","code":"0000"}',
                )
            else:
                await route.continue_()

        await page.route("**/mbuster/**", block_mbuster_t)
        await page.route("**/MBusterAPI/**", block_mbuster_t)

        # === 요청 캡처 ===
        async def on_request(request):
            entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "type": "request",
                "method": request.method,
                "url": request.url,
                "headers": dict(request.headers),
                "post_data": request.post_data,
                "resource_type": request.resource_type,
            }
            captured.append(entry)

            # 콘솔 출력
            label = f"[REQ] {request.method} {request.url}"
            if request.post_data:
                body_preview = request.post_data[:200]
                label += f"\n       POST: {body_preview}"
            print(label)

        # === 응답 캡처 ===
        async def on_response(response):
            body_text = None
            content_type = response.headers.get("content-type", "")

            # 텍스트 기반 응답만 본문 캡처 (이미지/폰트 등 제외)
            is_text = any(t in content_type for t in [
                "text/", "json", "xml", "javascript", "html", "form",
            ])

            if is_text:
                try:
                    raw = await response.body()
                    # 인코딩 시도: utf-8 → euc-kr → latin-1
                    for enc in ["utf-8", "euc-kr", "cp949", "latin-1"]:
                        try:
                            body_text = raw.decode(enc)
                            break
                        except (UnicodeDecodeError, ValueError):
                            continue
                    if body_text and len(body_text) > 50000:
                        body_text = body_text[:50000] + f"\n... (truncated, total {len(raw)} bytes)"
                except Exception:
                    body_text = None

            entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "type": "response",
                "status": response.status,
                "url": response.url,
                "headers": dict(response.headers),
                "body": body_text,
                "body_size": len(body_text) if body_text else None,
            }
            captured.append(entry)

            status_icon = "+" if response.status < 400 else "!"
            size_str = f"{len(body_text)}B" if body_text else "binary"
            print(f"[RES {status_icon}] {response.status} {response.url} ({size_str})")

        page.on("request", on_request)
        page.on("response", on_response)

        # === 콘솔 로그 캡처 ===
        def on_console(msg):
            print(f"[CONSOLE] {msg.type}: {msg.text}")
            captured.append({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "type": "console",
                "level": msg.type,
                "text": msg.text,
            })

        page.on("console", on_console)

        # === 페이지 로드 ===
        print(f"\n{'='*60}")
        print(f"캡처 시작: {URL}")
        print(f"{'='*60}")
        print("브라우저에서 자유롭게 조작하세요.")
        print("조작이 끝나면 브라우저를 닫으면 캡처가 저장됩니다.\n")

        # 1단계: 첫 로드 — MBuster 자연 통과 (intercept 없이)
        try:
            await page.goto(URL, timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(3)
        except Exception as e:
            print(f"[!] 페이지 로드 중 오류: {e}")
            print("    계속 캡처합니다...")

        print("[+] MBuster intercept 활성 — 이제 자유롭게 조작하세요.")

        # 브라우저가 닫힐 때까지 대기
        try:
            await page.wait_for_event("close", timeout=0)
        except Exception:
            pass

        # 브라우저 종료 대기
        try:
            await browser.close()
        except Exception:
            pass

    # === 결과 저장 ===
    # 요청/응답 쌍 매칭 + 요약
    requests_only = [e for e in captured if e["type"] == "request"]
    responses_only = [e for e in captured if e["type"] == "response"]

    # API 호출만 필터 (정적 리소스 제외)
    api_calls = []
    static_ext = {".js", ".css", ".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".svg"}
    for req in requests_only:
        url = req["url"]
        if any(url.lower().endswith(ext) for ext in static_ext):
            continue
        # 매칭 응답 찾기
        matching_resp = None
        for resp in responses_only:
            if resp["url"] == url:
                matching_resp = resp
                break
        api_calls.append({
            "method": req["method"],
            "url": url,
            "request_headers": req["headers"],
            "post_data": req["post_data"],
            "resource_type": req["resource_type"],
            "response_status": matching_resp["status"] if matching_resp else None,
            "response_headers": matching_resp["headers"] if matching_resp else None,
            "response_body": matching_resp["body"] if matching_resp else None,
        })

    output = {
        "capture_info": {
            "url": URL,
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_requests": len(requests_only),
            "total_responses": len(responses_only),
            "api_calls": len(api_calls),
        },
        "api_calls": api_calls,
        "full_log": captured,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"캡처 완료!")
    print(f"  전체 요청: {len(requests_only)}건")
    print(f"  전체 응답: {len(responses_only)}건")
    print(f"  API 호출 (정적 제외): {len(api_calls)}건")
    print(f"  저장: {args.output}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
