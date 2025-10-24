# DKU_DataExt

> 🧠 단국대학교 **전시회(Exhibition) 데이터 자동화**  
> 키워드 → 3개 사이트(AUMA/GEP/Myfair) 자동검색 → URL 접속 → **Markdown 추출** → **LLM 요약/구조화** → **DB/엑셀 저장**  
> Gradio 웹 UI로 한 번에 수행하는 파이프라인

---

## 핵심 개념

- **웹 수집**: `crawl4ai.AsyncWebCrawler`로 페이지를 크롤링하고, **Markdown**으로 정제한 뒤 요약 파이프라인에 투입합니다.
- **LLM 요약/추출**: `llama.py` / `data.py`에 정의된 파이프라인을 호출해 **표준화 레코드**를 생성합니다.  
- **3개 검색원**:  
  - **AUMA**(영문명 기반 검색)  
  - **GEP, Myfair**(국문명 기반 검색)  
- **병렬 처리**: 선택된 URL 3개를 **쓰레드 풀**로 병렬 요약/추출합니다.  
- **저장**: 결과를 `saved/` 폴더에 **JSON/Excel**로 저장합니다.

---

## 기능 요약

- **SQL Server 로그인** 후 DB 검색  
- DB에서 찾은 전시회(국/영문명)로 **AUMA/GEP/Myfair 동시 검색**  
- 각 사이트에서 **선택한 결과**에 대해 **크롤링 → Markdown → LLM 요약/추출**  
- **정리된 표/JSON**을 UI에 렌더링, **엑셀(xlsx)**로 내보내기

---

# 💬 LLM Prompt 강화

본 프로젝트는 prompt.md 파일을 통해 GPT-OSS 20B 모델에게 세밀한 추론 지침(prompt instruction) 을 제공합니다.
이 방식으로 모델의 출력 일관성, 추출 정확도, 형식 안정성이 크게 향상되었으며,
실험 결과 **할루시네이션(hallucination) 발생률은 거의 0에 가까웠습니다.

prompt.md에는 다음과 같은 내용이 포함됩니다:

필드별 추출 기준 및 키 설명

불필요한 문장 제거 규칙

다국어(국문/영문) 병합 정책

Markdown 구조 인식 가이드

이를 통해 LLM이 단순 요약을 넘어 정확한 구조화된 데이터 레코드를 안정적으로 생성하도록 유도합니다.


## 시스템 구성

[사용자 키워드]
│
▼
[SQL Server 조회] ──(존재하면 표시/선택)
│
└───────────────▶ [AUMA/GEP/Myfair 자동검색]
│(선택)
▼
[크롤링 + Markdown]
│
▼
[LLM 요약/추출]
│
└──▶ saved/*.json, *.xlsx

## 요구 사항

- Python 3.10+
- Google Chrome (headless), `webdriver_manager`가 드라이버 자동 설치
- SQL Server + **ODBC Driver 17** (리눅스는 `msodbcsql17` 설치)
- 주요 라이브러리: `gradio`, `selenium`, `crawl4ai`, `pandas`, `openpyxl`, `pyodbc`, `transformers/torch`(LLM 백엔드)

---

## 설치

```bash
git clone https://github.com/yechan3219/DKU_DataExt
cd DKU_DataExt

# 가상환경
environment.yml 파일로 필요 패키지 콘다 환경 생성

실행
bash
코드 복사
python main2.py
Gradio 웹 UI가 127.0.0.1:7869에서 뜹니다.

사용 방법 (UI 탭)
1) 로그인
상단 SQL 서버 로그인에서 ID/PW 입력 → 로그인

연결 문자열은 ODBC Driver 17 / 127.0.0.1 / exhibition / dbo.Exhibition 기본값 사용

드라이버/서버/DB/스키마는 코드 상단 상수에서 수정 가능

2) 데이터베이스 검색
전시회명을 입력하고 DB 검색

결과가 여러 개면 리스트/테이블로 표시

선택된 전시회의 상세를 표로 확인 가능

3) 웹 검색 및 추출
DB에서 전시회를 선택했거나, DB에 없으면 키워드로 직접 3개 사이트 검색

AUMA(영문), GEP/ Myfair(국문) 결과가 드롭다운으로 뜸

각 사이트에서 하나씩 선택 → 데이터 추출 실행

페이지를 크롤링해 Markdown으로 정제 → LLM이 표준 스키마로 요약/추출

결과 표/JSON을 UI로 확인, 엑셀로 저장 가능

결과 저장
모든 산출물은 프로젝트 루트의 saved/ 폴더에 저장

JSON: prefix_YYYYMMDD_HHMMSS.json

Excel: 선택한 전시회별 시트 생성(컬럼 너비/헤더 스타일 자동 적용)

스키마(기본 키 목록)
기본 추출 키(예시):

전시회 국문명, 영문명(Full Name), 영문명(약자), 개최 시작, 개최 종료,
개최장소(국문), 개최장소(영어), 국가, 도시, 첫 개최년도, 개최 주기,
공식 홈페이지, 주최기관, 담당자, 전화, 이메일, 산업분야, 전시품목, 출처

추출 키는 data.py의 KEYS가 있으면 그걸 사용하고, 없으면 위 기본 리스트를 사용합니다.

환경/설정 포인트
AUMA는 영문명, GEP/Myfair는 국문명으로 검색하는 흐름이 기본값

크롤링은 비동기(AsyncWebCrawler) + 정규식 청크 전략(RegexChunking)

URL 다중 선택 시, 쓰레드 풀로 병렬 요약/추출

UI/표시용 CSS는 프로젝트에 맞춰 커스텀 적용됨

