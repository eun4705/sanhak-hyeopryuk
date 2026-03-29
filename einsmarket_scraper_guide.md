# e-insmarket.or.kr 스크래퍼 구조 & 차단 우회 가이드

## 1. 사이트 구조

- **URL**: `https://e-insmarket.or.kr/cancerIns/cancerInsList.knia`
- **운영**: 보험개발원 (KNIA) - 온라인 보험슈퍼마켓
- **보안**: MBuster 봇 감지 시스템
- **방식**: 폼 POST → 결과 테이블 → 엑셀 다운로드

### 폼 필드 구조

| 필드 | ID/name | 값 | 비고 |
|------|---------|-----|------|
| 생년월일 | `#insStartDtPicker` | `YYYY-MM-DD` | jQuery datepicker |
| 나이 | `name="age"`, `id="age"` | 숫자 (readonly) | `selectChange()`가 자동 계산 |
| 성별(남) | `id="sexM"`, `name="sex"` | `"1"` | checkbox |
| 성별(여) | `id="sexL"`, `name="sex"` | `"2"` | checkbox |
| 비갱신형 | `id="renewTypeA"`, `class="renewType"` | `"C1"` | checkbox |
| 갱신형 | `id="renewTypeB"`, `class="renewType"` | `"C2"` | checkbox |
| 상품분류 | `name="prdtSmlClsCd"` | `"D001"` | hidden |
| 정렬 | `name="ordering"` | `"ASC"` / `"DESC"` | select |

### 실제 POST 데이터 (네트워크 캡처)

```
menuId=&prdtSmlClsCd=D001&prdtCd=&prdtNm=&insrCmpyNm=&enterType=A
&page=1&sexDiv=&sex=1&birthday=20030210&age=23&renewTypeB=C2
&rgtMgntCd=&ordering=ASC
```

### 제출 버튼

```html
<button type="submit" class="btn_type04" onclick="pageRefresh(); return false;">
  상품비교하기
</button>
```

- `pageRefresh()` → `submitForm()` → `validateForm()` 통과 시 `$("#searchForm").submit()`

### validateForm() 체크 항목

1. `#age` 값이 비어있거나 0 미만이거나 100 초과 → 실패
2. `input.renewType` 체크박스 중 하나 이상 체크 → 통과

### 결과 페이지

- 총 건수: `<span class="fl total_count">총 <strong>12</strong> 건</span>`
- 테이블: `table.table_type01` (헤더: 번호, 회사명/상품명, 보장명, 보장금액, 보험료, 보장범위지수, 가입연령, 특성, 비고, 가입형태)
- 엑셀: `<button class="btn_excel" onclick="exceldown();">`

---

## 2. MBuster 봇 감지 시스템

### 개요

- **서버**: `https://mbst.knia.or.kr:8180/MBusterAPI/`
- **JS 파일**: `mbuster_api.js` (v2.1.2), `mbuster_meta.js` (v2.1.3)
- **감지 대상**: Selenium/Playwright, DevTools

### 감지 흐름

```
페이지 로드
  ↓
mbuster_api.js + mbuster_meta.js 로드
  ↓
① checkWhite.do (화이트리스트 확인)
  ↓
② navigator.webdriver 체크
  ├─ true → W_DECTECT : selenium 플래그 설정
  └─ false → 정상
  ↓
③ checkBotIp.do (봇 IP 체크 + W_DECTECT 전송)
  ↓
④ devtoolsDetector 시작 (DevTools 열림 감시)
  ├─ 열림 감지 → W_DECTECT : development tools
  └─ 안 열림 → 정상
```

### checkWhite.do 요청

```
POST https://mbst.knia.or.kr:8180/MBusterAPI/checkWhite.do

groupName=e-insmarket.or.kr
clientIp=190.2.155.233
loginId=190.2.155.233_T_864289_WC
```

### checkBotIp.do 요청

```
POST https://mbst.knia.or.kr:8180/MBusterAPI/checkBotIp.do

groupName=e-insmarket.or.kr
clientIp=190.2.155.233
loginId=190.2.155.233_T_864289_WC
user_login_id=
pageUrl=/cancerIns/cancerInsList.knia
userAgent=mozilla/5.0...chrome/146.0.0.0+safari/537.36+W_DECTECT+:+selenium
requestHeader=mozilla/5.0...chrome/146.0.0.0+safari/537.36+W_DECTECT+:+selenium
```

**핵심**: `userAgent`와 `requestHeader`에 `W_DECTECT : selenium`이 자동 추가됨

### W_DECTECT 플래그

MBuster 클라이언트 JS가 감지 결과를 userAgent에 붙여서 서버로 전송:

```javascript
if ('selenium-detect' === mode) {
    userAgent += " W_DECTECT : selenium";
} else if ('dev-detect' === mode) {
    userAgent += " W_DECTECT : development tools";
}
```

### 차단 방식

- **즉시 차단 아님** — selenium 감지되어도 처음엔 통과시킴
- **누적 기반** — 같은 IP에서 반복 감지되면 차단
- **IP 블랙리스트** — 한번 차단되면 쿨다운 필요 (시간 불명, VPN으로 IP 변경이 확실)
- **F12 열면 차단** — DevTools 감지 시 즉시 차단

---

## 3. 차단 우회 방법

### 성공한 조합 (v5 기준)

#### ① navigator.webdriver 제거 (필수)

```python
await context.add_init_script(
    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
)
```

- MBuster의 `navigator.webdriver && (c="selenium-detect")` 우회
- `W_DECTECT : selenium` 플래그가 안 붙음

#### ② 첫 로드는 자연 통과 + 이후 MBuster intercept (필수)

```python
# 1. 첫 로드 — MBuster 자연 통과
await page.goto(URL)
await page.wait_for_load_state("networkidle")

# 2. 이후 폼 제출 시 — MBuster API 가로채기
async def handle_mbuster(route):
    await route.fulfill(
        status=200,
        content_type="application/json",
        body='{"result":"OK","code":"0000"}',
    )
await page.route("**/MBusterAPI/**", handle_mbuster)
```

- 첫 페이지 로드에서 MBuster가 정상 동작하여 세션 인증
- 이후 폼 제출로 페이지 리로드될 때 MBuster 체크를 intercept

#### ③ 순수 Playwright 설정 (headless=False, channel="chrome")

```python
browser = await p.chromium.launch(headless=False, channel="chrome")
```

- stealth 스크립트 추가하면 오히려 감지됨
- `--disable-blink-features=AutomationControlled` → MBuster 감지 트리거했음
- **최소한의 설정이 최선**

### 실패한 방법들

| 방법 | 결과 | 이유 |
|------|------|------|
| `--disable-blink-features=AutomationControlled` | MBuster 차단 | 오히려 다른 감지 트리거 |
| stealth 스크립트 (plugins, languages 위장) | MBuster 차단 | 과도한 위장이 감지 패턴 |
| 처음부터 MBuster intercept | 페이지 깨짐 (1886 bytes) | 서버 측 검증도 있어서 클라이언트만 속이면 안 됨 |
| Chrome persistent context (유저 프로필) | 실행 불가 | Chrome이 이미 실행 중이면 프로필 잠금 |
| MBuster 차단 후 대기+재시도 | 실패 | IP 블랙리스트는 시간으로 안 풀림 |

### IP 차단 시 대응

1. **VPN / 모바일 핫스팟**으로 IP 변경 → 즉시 해결
2. 새 IP에서 **한 번의 브라우저 세션**으로 전체 수집 완료
3. 브라우저를 반복적으로 열었다 닫으면 누적 감지됨 → **테스트 최소화**

---

## 4. 스크래퍼 동작 흐름

```
브라우저 시작 (headless=False, channel="chrome")
  ↓
navigator.webdriver 제거 (init_script)
  ↓
페이지 로드 (MBuster 자연 통과)
  ↓
searchForm 존재 확인 (차단 감지)
  ↓
MBuster intercept 설정 (**/MBusterAPI/**)
  ↓
┌─ 루프: 갱신구분 × 성별 × 나이 ──────────────┐
│                                               │
│  이미 받은 파일? → 스킵                       │
│       ↓                                       │
│  폼 필드 세팅 (JS evaluate)                   │
│       ↓                                       │
│  "상품비교하기" 클릭 (button.btn_type04)      │
│       ↓                                       │
│  networkidle 대기 + 2초                       │
│       ↓                                       │
│  총 건수 파싱 (총 <strong>N</strong> 건)       │
│       ↓                                       │
│  0건 → 스킵 (debug HTML 저장)                 │
│  N건 → exceldown() → 파일 저장                │
│       ↓                                       │
│  delay 대기 (기본 2초)                        │
│                                               │
│  에러 시:                                     │
│   - 연결 끊김 → 브라우저 재시작 + intercept 재설정 │
│   - 기타 → go_back()                          │
└───────────────────────────────────────────────┘
  ↓
완료 (성공/에러/소요시간 출력)
```

---

## 5. 주의사항

### 반드시 지켜야 할 것

1. **첫 로드 전에 MBuster intercept 설정하지 말 것** — 페이지가 깨짐
2. **stealth 과다 적용 금지** — `webdriver` 제거만으로 충분
3. **테스트 반복 최소화** — 같은 IP에서 브라우저 여러 번 열면 누적 차단
4. **headless=False 유지** — headless 감지 가능성
5. **delay 최소 2초** — 서버 부하 방지

### 총 건수 파싱 정규식

HTML이 `총 <strong>12</strong> 건` 형태이므로:

```python
re.search(r'총\s*(?:<[^>]+>)?\s*(\d+)\s*(?:<[^>]+>)?\s*건', content)
```

### 에러 복구 시 주의

- `page.goto(URL)` 로 재접속하면 MBuster가 다시 트리거됨
- 가능하면 `page.go_back()` 사용
- 브라우저 완전히 죽었으면 재시작 후 MBuster intercept 재설정 필수

---

## 6. 파일 구조

```
einsmarket_scraper.py      # 메인 스크래퍼 (v5)
einsmarket_debug.py        # 네트워크 요청 캡처 (수동 조작)
einsmarket_debug2.py       # 엑셀 버튼/테이블 구조 캡처
einsmarket_test.py         # 단건 테스트 + HTML 저장

data/einsmarket/           # 수집된 엑셀 파일
  cancer_30세_남_비갱신형.xls
  cancer_30세_남_갱신형.xls
  ...

data/einsmarket_debug/     # 디버그 데이터
  network_log.json         # 전체 네트워크 로그
  excel_button_info.json   # 엑셀 버튼 HTML 구조
  result_full.html         # 결과 페이지 전체 HTML
```
