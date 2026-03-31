# 보험료 데이터 스크래퍼

KB라이프생명 보험료 계산기 및 금융감독원 보험다모아(e-insmarket)에서 보험료 데이터를 자동 수집하는 스크래퍼 모음입니다.

## 프로젝트 구조

```
sanhak-hyeopryuk/
├── einsmarket_scraper.py          # 금감원 보험다모아 암보험 스크래퍼 (Playwright)
├── scrape_whole_ins.py            # 금감원 보험다모아 종신보험 스크래퍼 (병렬 HTTP)
├── scrape_temp_ins.py             # 금감원 보험다모아 정기보험 스크래퍼 (병렬 HTTP)
├── capture_whole_ins.py           # 네트워크 캡처 도구
├── einsmarket_scraper_guide.md    # 금감원 스크래퍼 구조 & MBuster 우회 가이드
│
├── chrome_extension/              # Chrome 확장 프로그램 (KB라이프 스크래퍼)
│   ├── manifest.json              # 확장 프로그램 설정 (v2.0 — PC 사이트 대응)
│   ├── bridge.js                  # content script — 팝업 ↔ 페이지 메시지 중계
│   ├── page_runner.js             # 페이지 컨텍스트 — 명령 수신 + 스크래퍼 호출
│   ├── popup.html                 # 팝업 UI
│   ├── popup.js                   # 팝업 로직
│   ├── capture.js                 # API 요청 캡처 도구 (디버깅용, 기본 비활성)
│   ├── test_pc.js                 # PC 사이트 API 호출 테스트
│   ├── scraper.js                 # 착한정기보험II 전용 스크래퍼
│   ├── scraper_universal.js       # 범용 스크래퍼 (대부분의 상품 지원)
│   ├── scraper_health.js          # e-건강보험 전용 스크래퍼
│   ├── scraper_3n5.js             # 3N5 건강보험 전용 스크래퍼 (16개 상품)
│   ├── scraper_annuity.js         # 하이파이브연금 전용 스크래퍼
│   ├── scan_annuity.js            # 연금 상품 나이별 옵션 스캔 도구
│   └── existing_keys.json         # 이미 수집된 키 목록 (중복 방지)
│
└── data/                          # 수집된 데이터
    ├── einsmarket/                # 금감원 보험다모아 — 암보험 XLS
    ├── whole_ins/                 # 금감원 보험다모아 — 종신보험 XLS
    ├── temp_ins/                  # 금감원 보험다모아 — 정기보험 XLS
    └── premiums/                  # KB라이프 보험료 계산 결과 (JSONL)
```

## 현재 상태 (2026-04-01)

### KB라이프 WAF 차단 현황

KB라이프가 웹 방화벽(WAF)을 지속적으로 강화하고 있어서 스크래핑이 어려운 상태입니다.

**확인된 차단 로직:**

| 차단 레이어 | 설명 |
|-------------|------|
| 모바일 사이트 차단 | `m.kblife.co.kr` — DevTools 모바일 모드 사용 시 즉시 차단 |
| IP 블랙리스트 | API 호출 패턴 감지 시 해당 IP의 모든 API 차단 |
| XHR 변조 탐지 | XMLHttpRequest prototype 오버라이드 감지 시 차단 (AhnLab ASTX2) |
| 응답 암호화 | API 응답을 `cmmUtil.vestDec()`로 암호화 — 디코딩 필요 |

**현재 작동하는 접근 방식:**
- PC 사이트(`www.kblife.co.kr`) 사용
- 크롬 익스텐션 + 팝업 UI (DevTools 불필요)
- `premium-new-calculate` API → `cmmUtil.vestDec()` 디코딩 → `insuranceplans/{id}` 조회
- IP 차단 시 VPN 변경 필요

### 이어서 작업해야 할 것

**1. XHR 변조 탐지 문제 해결 (최우선)**

`capture.js`가 `XMLHttpRequest.prototype.open/send`를 오버라이드하면 WAF가 탐지하여 차단합니다. `console.log` 오버라이드도 마찬가지입니다. 현재 `bridge.js`에서 `capture.js`는 제거된 상태이고, `page_runner.js`에서 console 오버라이드도 제거되었습니다.

**하지만 스크래퍼 스크립트 자체의 주입(`<script src="...">`)이 탐지되는 건지, 아니면 API 호출 패턴(빈도/속도)이 탐지되는 건지 아직 명확하지 않습니다.**

다음 테스트를 해봐야 합니다:
- 익스텐션 로드된 상태에서 수동으로 보험료 계산 여러 번 → 차단 여부 확인
- 차단 안 되면 → 스크래퍼의 API 호출 패턴이 문제
- 차단 되면 → 스크립트 주입 자체가 탐지됨 → 다른 주입 방식 필요

**2. Rate Limiting 전략 수립**

현재 스크래퍼는 딜레이 없이 배치 병렬 호출(`Promise.all`)합니다. KB WAF의 rate limit 임계값을 파악하고 적절한 딜레이를 설정해야 합니다.

수정 위치:
- `scraper_3n5.js` → `BATCH_SIZE` (현재 3), `sleep(2000)` (배치 간 2초)
- `scraper_universal.js` → `BATCH_SIZE` (현재 10), 딜레이 없음
- `scraper_health.js` → `BATCH_SIZE` (현재 10), 딜레이 없음
- `scraper.js` → `BATCH_SIZE` (현재 10), 딜레이 없음

**3. vestDec 디코딩 적용 완료 확인**

모든 스크래퍼에 `cmmUtil.vestDec()` 디코딩이 추가되었지만 실제 스크래핑 테스트는 아직 못 했습니다.

적용된 파일:
- `scraper_3n5.js` — `calcOne()` 내 resultId 디코딩
- `scraper.js` — resultIds 배열 디코딩
- `scraper_universal.js` — resultId, resultIds 디코딩
- `scraper_health.js` — resultId 디코딩
- `scraper_annuity.js` — results[0] JSON 파싱 + 디코딩

## 스크래퍼 종류

### 금감원 보험다모아

#### `einsmarket_scraper.py` — 암보험

- **기술**: Python + Playwright (headless=False)
- **실행**: `python einsmarket_scraper.py --age-start 20 --age-end 64`
- **MBuster WAF 우회**: `navigator.webdriver` 제거 + MBuster API intercept

#### `scrape_whole_ins.py` — 종신보험

- **기술**: Playwright (세션 획득) + aiohttp (10건 병렬)
- **실행**: `python scrape_whole_ins.py --age-start 20 --age-end 64 --batch 10`

#### `scrape_temp_ins.py` — 정기보험

- **기술**: 종신보험 스크래퍼와 동일
- **실행**: `python scrape_temp_ins.py --age-start 20 --age-end 64 --batch 10`

### KB라이프 Chrome 확장

#### 사용 절차 (v2.0 — 팝업 UI)

```
1. chrome://extensions → 개발자 모드 ON → chrome_extension 폴더 로드
2. www.kblife.co.kr → 보험료 공시실 → 상품 페이지 접속
3. 수동으로 보험료 계산 1회 실행 (ajax 객체 초기화)
4. 우측 상단 확장 프로그램 아이콘 클릭 → 팝업에서 상품 선택 → 시작
5. (이전 방식) 또는 F12 콘솔에서 직접 함수 호출
```

#### `scraper_3n5.js` — 3N5 건강보험 (16개 상품)

- **호출**: `window.__scrape3n5('334000104', '3N5_간편335_표준형')` 또는 `window.__scrapeAll()`
- **API**: `premium-new-calculate` (주계약 + 특약 포함)
- **수집**: 나이(15~80세) x 성별 x 보험기간 x 납입기간 x 가입금액배수(1x, 2x)
- **특약 처리**: 나이/성별별 가입 가능 특약 자동 필터링 + 보험기간/납입기간 자동 매칭

#### `scraper.js` — 착한정기보험II

- **호출**: `window.__startScraper()`
- **API**: `premium-calculate`
- **수집**: 나이(19~70세) x 성별 x 보험기간 x 납입기간 x 납입주기 x 체형

#### `scraper_universal.js` — 범용

- **호출**: `window.__scrape('316100104', '착한암보험')`
- **API**: `premium-calculate`
- **지원**: 21개 상품 (3N5 16개 + 착한암 + e건강 + 착한정기II + 하이파이브연금)

#### `scraper_health.js` — e건강보험

- **호출**: `window.__scrapeHealth('337600104', 'e건강보험_일반심사')`
- **수집**: 나이(20~64세) x 성별 x 플랜(든든/실속/뇌심/입원) x 보험기간
- **특약**: 기본 + 선택형(중환자실, 응급실, 암진단 등)

#### `scraper_annuity.js` — 하이파이브연금

- **호출**: `window.__scrapeAnnuity()`
- **API**: `m-premium-calculate` → `getAnnuityExampleTotal`
- **수집**: 나이(19~65세) x 성별 x 납입기간(5/7/10/15년) x 월보험료(20만/50만)
- **결과**: 적립액 + 연금 6유형 (종신20년보증, 종신100세보증 등)

## 핵심 파일 수정 가이드

### WAF 차단 관련 수정

| 파일 | 위치 | 설명 |
|------|------|------|
| `bridge.js` | `SCRIPTS` 배열 | 페이지에 주입할 스크립트 목록. capture.js 등 추가/제거 |
| `page_runner.js` | 상단 | console 오버라이드 등 prototype 변조 코드 — WAF 탐지 주의 |
| `manifest.json` | `matches` | 대상 사이트 URL (`www.kblife.co.kr` 또는 `m.kblife.co.kr`) |

### 배치 크기/딜레이 조정

| 파일 | 변수 | 현재값 | 설명 |
|------|------|--------|------|
| `scraper_3n5.js` | `BATCH_SIZE` | 3 | 동시 호출 수 |
| `scraper_3n5.js` | `sleep(2000)` | 2초 | 배치 간 딜레이 |
| `scraper_universal.js` | `BATCH_SIZE` | 10 | 동시 호출 수 |
| `scraper_health.js` | `BATCH_SIZE` | 10 | 동시 호출 수 |
| `scraper.js` | `BATCH_SIZE` | 10 | 동시 호출 수 |

### vestDec 디코딩

모든 `premium-calculate`, `premium-new-calculate` 응답의 result/results 값이 vest 암호화되어 있습니다. 디코딩 패턴:

```js
// 단일 result (premium-new-calculate)
var resultId = calcResult.result;
if (typeof cmmUtil !== 'undefined' && cmmUtil.vestDec) {
  try { resultId = cmmUtil.vestDec(resultId); } catch(e) {}
}

// results 배열 (premium-calculate)
if (typeof cmmUtil !== 'undefined' && cmmUtil.vestDec) {
  resultIds = resultIds.map(r => { try { return cmmUtil.vestDec(r); } catch(e) { return r; } });
}

// results 배열 내 JSON 객체 (annuity 등)
if (typeof r.results[0] === 'string' && typeof cmmUtil !== 'undefined') {
  try { r.results[0] = JSON.parse(cmmUtil.vestDec(r.results[0])); } catch(e) {}
}
```

### 새 상품 추가

1. `insuranceplan-option` API로 상품 옵션 조회하여 구조 파악
2. 기존 스크래퍼 중 비슷한 구조의 것을 복사하여 수정
3. `PRODUCTS` 배열에 `{ name, prodCd }` 추가
4. 팝업 UI: `popup.html`의 `<select id="product">`에 `<option>` 추가
5. `page_runner.js`의 명령 핸들러에 새 action 추가

## 수집 데이터

### `data/einsmarket/` — 금감원 암보험 XLS (180개 파일)
### `data/whole_ins/` — 금감원 종신보험 XLS (90개 파일)
### `data/temp_ins/` — 금감원 정기보험 XLS (90개 파일)
### `data/premiums/` — KB라이프 보험료 JSONL

| 파일명 | 상품 |
|--------|------|
| `착한암보험_전체.jsonl` | 착한암보험 |
| `착한정기보험II_전체.jsonl` | 착한정기보험II |
| `e건강보험_일반심사_전체.jsonl` | e건강보험 (일반심사) |
| `e건강보험_간편심사355_전체.jsonl` | e건강보험 (간편심사) |
| `하이파이브연금_전체.jsonl` | 하이파이브연금 |
