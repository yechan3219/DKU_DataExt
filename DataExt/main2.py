# -*- coding: utf-8 -*-
import asyncio
import time
import html
import os
import json
import re
from typing import Dict, List, Tuple, Optional

import gradio as gr
import pyodbc  # SQL 서버 연동을 위해 추가
import pandas as pd # 엑셀 저장을 위해 추가

from crawl4ai import AsyncWebCrawler
from crawl4ai.chunking_strategy import RegexChunking

from llama import *          # LLM 관련 함수 임포트
from data import *           # 데이터 처리 관련 함수 임포트

# 저장 디렉토리 설정 및 생성
SAVED_DIR = os.path.abspath(os.path.join(os.getcwd(), "saved"))
os.makedirs(SAVED_DIR, exist_ok=True)

# ====== SQL 서버 연결 환경 설정  -> 이건 자기 sql 이름 넣으면 될듯 ======
DRIVER   = "ODBC Driver 17 for SQL Server"  # 드라이버 18 17 다 있는데 17로 되서 이걸로 함
SERVER   = "127.0.0.1"                       # 로컬
DATABASE = "exhibition"                      # 데이터베이스 이름
TABLE    = "Exhibition"                      # 전시회 정보 테이블 이름
SCHEMA   = "dbo"                             # 데이터베이스 스키마 이름




# --------------------------------------------------------------------------------------
# SQL 서버 연결 문자열 생성 함수
# --------------------------------------------------------------------------------------
def make_cs_sql_login(uid: str, pw: str) -> str:
    return (
        f"DRIVER={{{DRIVER}}};"           # ODBC 드라이버 지정
        f"SERVER={SERVER};"               # 서버 주소 지정
        f"DATABASE={DATABASE};"           # 데이터베이스 이름 지정
        f"UID={uid};PWD={pw};"            # 사용자 ID와 비밀번호
        "TrustServerCertificate=yes;"     # SSL 인증서 신뢰 설정
    )


def _now_tag():
    """
    지금 시간 타임 스탬프 찍는거
    Returns: YYYYMMDD_HHMMSS 이렇게 나옴
    """
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _sanitize_name(name: str) -> str:
    """
    파일명에 이상한거 들어가있으면 언더바로 바꿔줌
    """
    import re
    name = (name or "file").strip()
    name = re.sub(r"[^\w.\-]+", "_", name)  
    return name or "file"

def save_record_json_local(record, prefix: str) -> str | None:
    """
    추출된 데이터를 JSON 파일로 로컬에 저장
    """
    try:
        if not isinstance(record, dict):
            print(f"[save_record_json_local] record is not dict: {type(record)} - {record}")
            record = {}
        
        # 고유한 파일명 생성
        fname = _sanitize_name(f"{prefix}_{_now_tag()}.json")
        path = os.path.abspath(os.path.join(SAVED_DIR, fname))

        # JSON 파일로 저장
        with open(path, "w", encoding="utf-8") as f:
            import json
            json.dump(record, f, ensure_ascii=False, indent=2)

        # 파일 저장 성공 여부 확인
        return path if os.path.isfile(path) else None

    except Exception as e:
        print(f"[save_record_json_local] error: {e}")
        return None

def save_merged_excel(all_results: List[Dict], prefix: str) -> str | None: # 엑셀 저장
    try:
        if not all_results:
            print("[save_merged_excel] 저장할 데이터가 없습니다.")
            return None

        df_list = []
        for result in all_results:
            data = []
            rec_gep = result.get('GEP', {})
            rec_myfair = result.get('Myfair', {})
            rec_auma = result.get('AUMA', {})

            # 추출 키 목록에 따라 데이터 행 생성
            for k in EXTRACT_KEYS:
                row = {
                    "항목": k,
                    "GEP": rec_gep.get(k, ""),
                    "Myfair": rec_myfair.get(k, ""),
                    "AUMA": rec_auma.get(k, "")
                }
                data.append(row)

            # DataFrame 생성 및 시트 이름 지정
            df = pd.DataFrame(data)
            sheet_name = _sanitize_name(result['korean_name'])[:31] # 엑셀 시트명 길이 제한(31자)
            df_list.append((sheet_name, df))

        # 엑셀 파일명 생성
        fname = _sanitize_name(f"{prefix}_{_now_tag()}.xlsx")
        path = os.path.abspath(os.path.join(SAVED_DIR, fname))

        # 엑셀 파일 생성 및 스타일 적용
        with pd.ExcelWriter(path, engine='openpyxl') as writer:
            for sheet_name, df in df_list:
                df.to_excel(writer, sheet_name=sheet_name, index=False)

                # 열 너비 자동 조정
                worksheet = writer.sheets[sheet_name]
                worksheet.column_dimensions['A'].width = 25  # 항목 열
                worksheet.column_dimensions['B'].width = 40  # GEP 열
                worksheet.column_dimensions['C'].width = 40  # Myfair 열
                worksheet.column_dimensions['D'].width = 40  # AUMA 열

                # 헤더 스타일 설정
                from openpyxl.styles import Font, PatternFill, Alignment
                header_font = Font(bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
                header_alignment = Alignment(horizontal="center", vertical="center")

                # 첫 번째 행(헤더)에 스타일 적용
                for cell in worksheet[1]:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment

        return path if os.path.isfile(path) else None

    except Exception as e:
        print(f"[save_merged_excel] error: {e}")
        return None

# === 전역 CSS: 표 스타일 통일 및 가독성 개선 ===
CUSTOM_CSS = """
:root{
  --ex-label-w: 170px;     /* 라벨(첫 열) 고정 너비 */
  --ex-row-h: 42px;        /* 모든 표 공통 행 높이 */
  --ex-border: 1px solid color-mix(in oklab, var(--body-text-color) 18%, transparent);
}

/* 결과 테이블 공통 스타일 */
.ex-card { padding: 2px 0; }
.ex-table { table-layout: fixed; width: 100%; border-collapse: collapse; }
.ex-table col.label { width: var(--ex-label-w); }
.ex-table th, .ex-table td {
  background: transparent !important;
  border-bottom: var(--ex-border);
  height: var(--ex-row-h);
  line-height: var(--ex-row-h);
  vertical-align: middle;
  padding: 0 10px;
  color: var(--body-text-color);
}
.ex-table th {
  font-weight: 600;
  opacity: .92;           /* 라벨 가독성 향상 */
}

/* 값 셀: 긴 텍스트는 말줄임표 처리, 전체 내용은 툴팁으로 표시 */
.ex-table td .val {
  display: block;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* 줄무늬 배경으로 가독성 향상 */
.ex-table tr:nth-child(even) td {
  background: color-mix(in oklab, var(--background-fill-primary) 92%, var(--body-text-color) 8%) !important;
}

/* Gradio DataFrame 편집표에도 동일한 스타일 적용 */
[data-testid="dataframe"] table {
  table-layout: fixed;
}
[data-testid="dataframe"] table td,
[data-testid="dataframe"] table th {
  background: transparent !important;
  border-bottom: var(--ex-border);
  height: var(--ex-row-h);
  line-height: var(--ex-row-h);
  vertical-align: middle;
  padding: 0 10px;
  color: var(--body-text-color);
  max-width: 0;           /* 열 너비 고정 */
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
"""

# --------------------------------------------------------------------------------------
# 애플리케이션 설정 및 상수
# --------------------------------------------------------------------------------------
APP_TITLE = "데추"  # 애플리케이션 제목

try:
    EXTRACT_KEYS = KEYS 
except Exception:
    EXTRACT_KEYS = [
        "전시회 국문명","영문명(Full Name)","영문명(약자)",
        "개최 시작","개최 종료",
        "개최장소(국문)","개최장소(영어)","국가","도시",
        "첫 개최년도","개최 주기","공식 홈페이지",
        "주최기관","담당자","전화","이메일",
        "산업분야","전시품목","출처"
    ]

DATASET_COLORS = {1: "#D7263D", 2: "#1B9AAA", 3: "#2E7D32"}  # 1=AUMA(빨강), 2=GEP(파랑), 3=Myfair(초록)



# --------------------------------------------------------------------------------------
# 웹 크롤링 및 데이터 추출 파이프라인
# --------------------------------------------------------------------------------------
async def crawl_and_summarize(url: str):
    if not url:
        return "URL이 제공되지 않았습니다. 클립보드에 URL이 복사되어 있는지 확인해주세요."

    async with AsyncWebCrawler(verbose=True) as crawler:
        start_time = time.time()
        result = await crawler.arun(
            url=url,
            word_count_threshold=1,           
            chunking_strategy=RegexChunking(), 
            bypass_cache=True,                
        )
        
        raw_md = getattr(result, "markdown", "") or ""
        text_base = normalize_text(raw_md)

        record = {"markdown": text_base or "", "source_url": url}

        bytes_norm = len((text_base or "").encode("utf-8"))
        print(f"[INFO] 추출된 텍스트 길이: {bytes_norm} bytes")

        if not record:
            print("[INFO] 처리할 텍스트가 없습니다.")
            return

        result = run_pipeline_markdown(record)

        total_time = time.time() - start_time
        print(f"[INFO] 전체 처리 시간: {total_time:.2f} s")
        return result

async def summarize_url(url: str) -> Tuple[str, Dict[str, str]] | str:
    if not url:
        return "URL이 제공되지 않았습니다. 클립보드에 URL이 복사되어 있는지 확인해주세요."

    result = await crawl_and_summarize(url)
    if isinstance(result, str):
        return result  
        
    if result:
        rec_raw = result["data"]
        rec = canonicalize_record(rec_raw)
        
        table_md = to_markdown_table(rec)      
        pretty = to_json(rec)                 
        saved_path = save_json(result, rec, url) 

        output = (
            "### 추출 결과(표)\n"
            f"{table_md}\n\n"
            "### Raw JSON(정리 후)\n"
            f"{pretty}\n"
            f"<sub>모델: {result['model']} · 컨텍스트: {result['num_ctx']} · 추출시각(UTC): {result['extracted_at']}</sub>\n"
            f"**JSON 저장:** `{saved_path}`"
        )
        print("[INFO] URL 처리 완료")
        return output, rec
    else:
        return "페이지를 크롤링하고 정보를 추출하는 데 실패했습니다."



# --------------------------------------------------------------------------------------
# 3개 전시회 사이트 검색 함수
# --------------------------------------------------------------------------------------
def search_auma(exhibition: str) -> List[Dict[str, str]]:
    """
    AUMA 사이트에서 전시회 검색하여 여러 결과 반환
    
    Returns:
        List[Dict[str, str]]: 검색 결과 리스트 (display_text, url, year, month, city, country)
    """
    try:
        import time
        import re
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException

        search_query = exhibition.strip()
        results = []
        
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        try:
            driver.get("https://www.auma.de/en/")
            time.sleep(0.1)

            search_box = driver.find_element(By.ID, "searchText")
            search_box.send_keys(search_query)
            time.sleep(0.1)
            search_box.send_keys(Keys.ENTER)

            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "trade-fair-result")))

            row_xpath = "//tbody[@class='trade-fair-result__body']/tr[@class='trade-fair-result__row']"
            all_rows = driver.find_elements(By.XPATH, row_xpath)
            
            if not all_rows:
                print("[AUMA] no search results found")
                return []

            month_map = {
                'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
                'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12
            }

            for i, row in enumerate(all_rows):
                try:
                    # Re-find the row to avoid stale element reference
                    current_row = driver.find_element(By.XPATH, f"({row_xpath})[{i+1}]")
                    
                    date_text = current_row.find_element(By.CLASS_NAME, "trade-fair-result__cell--strTermin").text
                    link_element = current_row.find_element(By.CLASS_NAME, "trade-fair-result__link")
                    link_text = link_element.text
                    link_href = link_element.get_attribute('href')
                    city_text = current_row.find_element(By.CLASS_NAME, "trade-fair-result__cell--strStadt").text
                    country_text = current_row.find_element(By.CLASS_NAME, "trade-fair-result__cell--strLand").text
                    
                    combined_text = f"{link_text} {city_text} {country_text}"
                    query_words = search_query.split()
                    # 유연한 검색: 검색어 중 하나라도 포함되면 결과에 포함 (OR 조건)
                    title_contains_query = any(word.lower() in combined_text.lower() for word in query_words)

                    if title_contains_query:
                        # 날짜 정보 추출
                        year = 0
                        month = 0
                        year_match = re.search(r'(20\d{2})', date_text)
                        if year_match:
                            year = int(year_match.group(1))
                            for name, num in month_map.items():
                                if name.lower() in date_text.lower(): 
                                    month = num; break
                            if month == 0:
                                month_num_match = re.search(r'\.(\d{2})\.', date_text)
                                if month_num_match: month = int(month_num_match.group(1))

                        # 표시 텍스트 생성
                        display_text = f"{link_text}"
                        if year:
                            display_text += f" {year}"
                        if city_text:
                            display_text += f" - {city_text}"
                        if country_text:
                            display_text += f" ({country_text})"

                        results.append({
                            'display_text': display_text,
                            'url': link_href,
                            'year': year,
                            'month': month,
                            'city': city_text,
                            'country': country_text,
                            'title': link_text
                        })
                        
                except Exception as e:
                    print(f"[AUMA] error processing row {i+1}: {e}")
                    continue

            print(f"[AUMA] found {len(results)} results")
            return results

        finally:
            driver.quit()

    except Exception as e:
        print(f"[AUMA 검색 오류] {e}")
        return []

def search_gep(exhibition: str) -> List[Dict[str, str]]:
    """
    GEP 사이트에서 전시회 검색하여 여러 결과 반환
    
    Returns:
        List[Dict[str, str]]: 검색 결과 리스트 (display_text, url, year, month, title)
    """
    try:
        import time
        import re
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException

        search_query = exhibition.strip()
        results = []
        
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        try:
            driver.get("https://www.gep.or.kr/gept/ovrss/main/mainPage.do")
            time.sleep(0.1)

            search_box = driver.find_element(By.ID, "topQuery")
            search_box.send_keys(search_query)
            time.sleep(0.1)
            search_box.send_keys(Keys.ENTER)

            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.XPATH, "//*[@id='totalSearchView']//a")))

            all_items = driver.find_elements(By.CLASS_NAME, "text-info")
            
            if not all_items:
                return []

            for item in all_items:
                try:
                    date_div = item.find_element(By.CLASS_NAME, "info-date")
                    date_text = date_div.text
                    link_element = item.find_element(By.CSS_SELECTOR, ".info-title a")
                    link_text = link_element.text
                    link_href = link_element.get_attribute('href')
                    
                    query_words = search_query.split()
                    # 유연한 검색: 검색어 중 하나라도 포함되면 결과에 포함 (OR 조건)
                    title_contains_query = any(word in link_text for word in query_words)

                    if title_contains_query:
                        # 날짜 정보 추출
                        year = 0
                        month = 0
                        year_match = re.search(r'(20\d{2})', date_text)
                        month_match = re.search(r'-(\d{2})-', date_text)

                        if year_match and month_match:
                            year = int(year_match.group(1))
                            month = int(month_match.group(1))

                        # 표시 텍스트 생성
                        display_text = f"{link_text}"
                        if year:
                            display_text += f" {year}"
                        if month:
                            display_text += f".{month:02d}"

                        # JavaScript 링크 처리를 위한 URL 생성
                        final_url = link_href
                        if link_href and link_href.startswith("javascript:"):
                            match = re.search(r"viewOverseasExhibition\('([^']+)'\)", link_href)
                            if match:
                                exhibition_id = match.group(1)
                                final_url = f"https://www.gep.or.kr/gept/ovrss/sear/selectOverseasExhibitionView.do?exhbId={exhibition_id}"

                        results.append({
                            'display_text': display_text,
                            'url': final_url,
                            'year': year,
                            'month': month,
                            'title': link_text,
                            'original_url': link_href
                        })
                        
                except Exception as e:
                    print(f"[GEP] error processing item: {e}")
                    continue

            print(f"[GEP] found {len(results)} results")
            return results

        finally:
            driver.quit()

    except Exception as e:
        print(f"[GEP 검색 오류] {e}")
        return []

def search_myfair(exhibition: str) -> List[Dict[str, str]]:
    """
    Myfair 사이트에서 전시회 검색하여 여러 결과 반환
    
    Returns:
        List[Dict[str, str]]: 검색 결과 리스트 (display_text, url, year, month, title)
    """
    try:
        import time
        import re
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException

        search_query = exhibition.strip()
        results = []
        
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        try:
            driver.get("https://myfair.co/")
            time.sleep(0.1)

            search_box = driver.find_element(By.XPATH, "//input[@placeholder='박람회명 검색']")
            search_box.send_keys(search_query)
            time.sleep(0.1)
            search_box.send_keys(Keys.ENTER)

            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "css-azmimp")))

            xpath_selector = "//div[@class='css-1byidqq' and .//span[@class='css-1nutr9u']]"
            all_cards = driver.find_elements(By.XPATH, xpath_selector)
            
            if not all_cards:
                print("[Myfair] no search results found")
                return []

            for card in all_cards:
                try:
                    date_span = card.find_element(By.CLASS_NAME, "css-1nutr9u")
                    date_text = date_span.text
                    link_element = card.find_element(By.XPATH, ".//a[contains(@class, 'text-md')]")
                    link_text = link_element.text
                    link_href = link_element.get_attribute('href')
                    
                    query_words = search_query.split()
                    # 유연한 검색: 검색어 중 하나라도 포함되면 결과에 포함 (OR 조건)
                    title_contains_query = any(word in link_text for word in query_words)

                    if title_contains_query:
                        # 날짜 정보 추출
                        year = 0
                        month = 0
                        year_match = re.search(r'(20\d{2})', date_text)
                        month_match = re.search(r'(\d{1,2})월', date_text)
                        
                        if year_match:
                            year = int(year_match.group(1))
                        if month_match:
                            month = int(month_match.group(1))

                        # 표시 텍스트 생성
                        display_text = f"{link_text}"
                        if year:
                            display_text += f" {year}"
                        if month:
                            display_text += f".{month}월"

                        results.append({
                            'display_text': display_text,
                            'url': link_href,
                            'year': year,
                            'month': month,
                            'title': link_text
                        })
                        
                except Exception as e:
                    print(f"[Myfair] error processing card: {e}")
                    continue

            print(f"[Myfair] found {len(results)} results")
            return results

        finally:
            driver.quit()

    except Exception as e:
        print(f"[Myfair 검색 오류] {e}")
        return []



# --------------------------------------------------------------------------------------
# 다중 URL 비교 및 병합 도우미 함수
# --------------------------------------------------------------------------------------






def _extract_multiple_parallel(urls: List[str]) -> List[Dict[str, str]]:
    """
    여러 URL을 병렬로 동시에 추출하여 성능 향상
    
    Args:
        urls (List[str]): 추출할 URL 리스트
        
    Returns:
        List[Dict[str, str]]: 추출된 데이터 리스트 (URL 순서대로)
    """
    import concurrent.futures
    import threading
    
    def extract_single(url_idx):
        url = urls[url_idx]
        if not url:
            return url_idx, {}
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(summarize_url(url))
        finally:
            loop.close()
        
        if isinstance(res, tuple) and len(res) >= 2:
            _, rec = res
            return url_idx, rec or {}
        return url_idx, {}
    
    results = [{}] * len(urls)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_idx = {
            executor.submit(extract_single, i): i 
            for i in range(len(urls))
        }
        
        for future in concurrent.futures.as_completed(future_to_idx):
            try:
                idx, rec = future.result()
                results[idx] = rec
            except Exception as e:
                idx = future_to_idx[future]
                print(f"[병렬 추출 오류] URL {idx+1}: {e}")
                results[idx] = {}
    
    return results



def search_three_sites_for_one(korean_name: str, english_name: str):
    """
    하나의 전시회에 대해 3개 사이트에서 언어에 맞춰 검색
    
    Args:
        korean_name (str): 전시회 국문명 (GEP, Myfair 검색용)
        english_name (str): 전시회 영문명 (AUMA 검색용)
        
    Returns:
        tuple: (AUMA 결과 리스트, GEP 결과 리스트, Myfair 결과 리스트)
    """
    print("-" * 50)
    print(f"[검색 시작] 국문: '{korean_name}', 영문: '{english_name}'")

    # 각 사이트의 특성에 맞춰 검색어 선택
    # AUMA: 독일 사이트이므로 영문명으로 검색
    # GEP, Myfair: 한국 사이트이므로 국문명으로 검색
    results_auma = search_auma(english_name)
    results_gep = search_gep(korean_name)
    results_myfair = search_myfair(korean_name)

    print(f"[검색 결과] AUMA: {len(results_auma)}개, GEP: {len(results_gep)}개, Myfair: {len(results_myfair)}개")
    return results_auma, results_gep, results_myfair

def render_search_results_dropdowns(results_auma: List[Dict], results_gep: List[Dict], results_myfair: List[Dict]) -> str:
    """
    3개 사이트 검색 결과를 드롭다운으로 렌더링
    
    Args:
        results_auma: AUMA 검색 결과 리스트
        results_gep: GEP 검색 결과 리스트  
        results_myfair: Myfair 검색 결과 리스트
        
    Returns:
        str: HTML 드롭다운 표시
    """
    html_parts = []
    
    # AUMA 드롭다운 ->  result를 사이트별로 지정해서 드롭다운으로 구현함
    # 뭐 이제 index별로 지정을 해줬고 드랍다운으로 구현함
    auma_choices = ["선택 안함"] + [f"{i+1}. {result['display_text']}" for i, result in enumerate(results_auma)]
    auma_html = f"""
    <div style="margin: 15px 0; padding: 15px; border: 1px solid var(--border-color-primary); border-radius: 8px; background: var(--background-fill-secondary);">
        <h4 style="margin: 0 0 10px 0; color: {DATASET_COLORS.get(1, '#D7263D')}; font-size: 16px; font-weight: 600;">🔍 AUMA 검색 결과 ({len(results_auma)}개)</h4>
        <select id="auma_dropdown" style="width: 100%; padding: 8px; border: 1px solid var(--border-color-secondary); border-radius: 4px; background: var(--background-fill-primary); color: var(--body-text-color);">
            {"".join([f'<option value="{choice}">{choice}</option>' for choice in auma_choices])}
        </select>
    </div>
    """
    html_parts.append(auma_html)
    
    # GEP 드롭다운
    gep_choices = ["선택 안함"] + [f"{i+1}. {result['display_text']}" for i, result in enumerate(results_gep)]
    gep_html = f"""
    <div style="margin: 15px 0; padding: 15px; border: 1px solid var(--border-color-primary); border-radius: 8px; background: var(--background-fill-secondary);">
        <h4 style="margin: 0 0 10px 0; color: {DATASET_COLORS.get(2, '#1B9AAA')}; font-size: 16px; font-weight: 600;">🔍 GEP 검색 결과 ({len(results_gep)}개)</h4>
        <select id="gep_dropdown" style="width: 100%; padding: 8px; border: 1px solid var(--border-color-secondary); border-radius: 4px; background: var(--background-fill-primary); color: var(--body-text-color);">
            {"".join([f'<option value="{choice}">{choice}</option>' for choice in gep_choices])}
        </select>
    </div>
    """
    html_parts.append(gep_html)
    
    # Myfair 드롭다운
    myfair_choices = ["선택 안함"] + [f"{i+1}. {result['display_text']}" for i, result in enumerate(results_myfair)]
    myfair_html = f"""
    <div style="margin: 15px 0; padding: 15px; border: 1px solid var(--border-color-primary); border-radius: 8px; background: var(--background-fill-secondary);">
        <h4 style="margin: 0 0 10px 0; color: {DATASET_COLORS.get(3, '#2E7D32')}; font-size: 16px; font-weight: 600;">🔍 Myfair 검색 결과 ({len(results_myfair)}개)</h4>
        <select id="myfair_dropdown" style="width: 100%; padding: 8px; border: 1px solid var(--border-color-secondary); border-radius: 4px; background: var(--background-fill-primary); color: var(--body-text-color);">
            {"".join([f'<option value="{choice}">{choice}</option>' for choice in myfair_choices])}
        </select>
    </div>
    """
    html_parts.append(myfair_html)
    
    # 실행 버튼
    execute_html = """
    <div style="margin: 20px 0; text-align: center;">
        <button id="execute_extraction" style="padding: 12px 24px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 6px; font-size: 16px; font-weight: 600; cursor: pointer;">
            🚀 선택된 전시회로 데이터 추출 실행
        </button>
    </div>
    """
    html_parts.append(execute_html)
    
    return "".join(html_parts)

def extract_selected_urls(auma_choice: str, results_auma: List[Dict], 
                         gep_choice: str, results_gep: List[Dict],
                         myfair_choice: str, results_myfair: List[Dict]) -> Tuple[str, str, str]:
    """
    드롭다운에서 선택된 결과에서 URL 추출
    
    Args:
        auma_choice: AUMA 드롭다운 선택값
        results_auma: AUMA 검색 결과 리스트
        gep_choice: GEP 드롭다운 선택값
        results_gep: GEP 검색 결과 리스트
        myfair_choice: Myfair 드롭다운 선택값
        results_myfair: Myfair 검색 결과 리스트
        
    Returns:
        tuple: (AUMA URL, GEP URL, Myfair URL)
    """
    def get_url_from_choice(choice: str, results: List[Dict]) -> str:
        if not choice or choice == "선택 안함":
            return ""
        
        # 선택값에서 인덱스 추출 (예: "1. Hannover Messe 2024" -> 0)
        import re
        match = re.match(r'^(\d+)\.', choice)
        if match:
            index = int(match.group(1)) - 1
            if 0 <= index < len(results):
                return results[index]['url']
        return ""
    
    url_auma = get_url_from_choice(auma_choice, results_auma)
    url_gep = get_url_from_choice(gep_choice, results_gep)
    url_myfair = get_url_from_choice(myfair_choice, results_myfair)
    
    return url_auma, url_gep, url_myfair

def search_exhibition_in_db(search_term: str, connection=None) -> List[Dict[str, str]]:
    """
    데이터베이스에서 전시회명으로 검색 (국문명/영문명 모두 대상)
    
    Args:
        search_term (str): 검색어
        connection: 데이터베이스 연결 객체
        
    Returns:
        List[Dict[str, str]]: 검색된 전시회 정보 리스트
    """
    exhibitions = []
    try:
        if connection:
            conn = connection
            should_close = False
        else:
            raise Exception("로그인된 연결이 필요합니다.")
        
        cursor = conn.cursor()
        # 국문명 또는 영문명에 검색어가 포함된 전시회 검색 (LIKE 연산자 사용)
        search_query = f"SELECT No, ExhibitionID, Industry, ExKoreanName, ExEnglishName, NameAbbreviation, HostCycle, HostType, FirstHost, OfficialSite, HostInstitution, Staff, Tel, Email, ExhibitItem, createdAt, logoImage FROM dbo.Exhibition WHERE ExKoreanName LIKE '%{search_term}%' OR ExEnglishName LIKE '%{search_term}%';"
        cursor.execute(search_query)
        rows = cursor.fetchall()
        
        # 검색 결과를 딕셔너리 리스트로 변환 (a.txt 기준 모든 컬럼)
        for row in rows:
            if len(row) >= 17:
                exhibitions.append({
                    'No': str(row[0]) if row[0] else '',
                    'ExhibitionID': row[1] or '',
                    'Industry': row[2] or '',
                    'korean_name': row[3] or '',
                    'english_name': row[4] or '',
                    'NameAbbreviation': row[5] or '',
                    'host_cycle': row[6] or '',
                    'HostType': row[7] or '',
                    'first_host': str(row[8]) if row[8] else '',
                    'official_site': row[9] or '',
                    'host_institution': row[10] or '',
                    'staff': row[11] or '',
                    'tel': row[12] or '',
                    'email': row[13] or '',
                    'exhibit_item': row[14] or '',
                    'createdAt': str(row[15]) if row[15] else '',
                    'logoImage': row[16] or ''
                })
        
        return exhibitions
        
    except Exception as e:
        print(f"[DB 검색 오류] {e}")
        return []

def render_db_selection_table(exhibitions: List[Dict[str, str]]) -> str:
    """
    데이터베이스 검색 결과를 간단하게 표시 (선택용)
    
    Args:
        exhibitions (List[Dict[str, str]]): 전시회 정보 리스트
        
    Returns:
        str: HTML 테이블 문자열
    """
    if not exhibitions:
        return "<div style='color: var(--body-text-color-subdued);'>검색 결과가 없습니다.</div>"
    
    result_count = len(exhibitions)
    count_info = f"<div style='margin-bottom: 15px; color: var(--body-text-color); font-weight: 500;'>📋 데이터베이스 검색 결과 (총 {result_count}개) - 아래에서 원하는 전시회를 선택하세요</div>"
    
    exhibitions_html = ""
    for i, ex in enumerate(exhibitions):
        korean_name = html.escape(ex.get('korean_name', ''))
        english_name = html.escape(ex.get('english_name', ''))
        industry = html.escape(ex.get('Industry', ''))
        first_host = html.escape(ex.get('first_host', ''))
        
        # 도시 정보 추출
        city = extract_city_from_exhibition(ex)
        
        # 표시 텍스트 생성
        display_text = f"{korean_name}"
        if english_name:
            display_text += f" ({english_name})"
        if city:
            display_text += f" - {city}"
        if industry:
            display_text += f" [{industry}]"
        if first_host and first_host != 'None':
            display_text += f" (시작: {first_host})"
        
        # 간단한 전시회 정보 표시
        exhibition_html = f"""
        <div style="margin: 10px 0; padding: 12px; border: 1px solid var(--border-color-primary); border-radius: 6px; background: var(--background-fill-secondary); color: var(--body-text-color);">
            <div style="font-size: 14px; font-weight: 600; color: var(--body-text-color);">
                {i+1}. {display_text}
            </div>
        </div>
        """
        exhibitions_html += exhibition_html
    
    return count_info + exhibitions_html

def render_db_table_with_selection(exhibitions: List[Dict[str, str]]) -> str:
    """
    데이터베이스 검색 결과를 각 전시회별 정보와 함께 표시
    
    Args:
        exhibitions (List[Dict[str, str]]): 전시회 정보 리스트
        
    Returns:
        str: HTML 테이블 문자열
    """
    if not exhibitions:
        return "<div style='color: var(--body-text-color-subdued);'>검색 결과가 없습니다.</div>"
    
    result_count = len(exhibitions)
    count_info = f"<div style='margin-bottom: 15px; color: var(--body-text-color); font-weight: 500;'>📋 데이터베이스 검색 결과 (총 {result_count}개) - 아래에서 원하는 전시회를 선택하세요</div>"
    
    exhibitions_html = ""
    for i, ex in enumerate(exhibitions):
        korean_name = html.escape(ex.get('korean_name', ''))
        english_name = html.escape(ex.get('english_name', ''))
        industry = html.escape(ex.get('Industry', ''))
        first_host = html.escape(ex.get('first_host', ''))
        
        # 도시 정보 추출
        city = extract_city_from_exhibition(ex)
        
        # 표시 텍스트 생성
        display_text = f"{korean_name}"
        if english_name:
            display_text += f" ({english_name})"
        if city:
            display_text += f" - {city}"
        if industry:
            display_text += f" [{industry}]"
        if first_host and first_host != 'None':
            display_text += f" (시작: {first_host})"
        
        # 각 전시회를 위한 HTML 생성 (테마에 맞는 색상 사용)
        exhibition_html = f"""
        <div style="margin: 15px 0; padding: 15px; border: 1px solid var(--border-color-primary); border-radius: 8px; background: var(--background-fill-secondary); color: var(--body-text-color);">
            <div style="margin-bottom: 10px; font-size: 16px; font-weight: 600; color: var(--body-text-color);">
                {i+1}. {display_text}
            </div>
            <div style="margin-top: 10px; padding: 15px; background: var(--background-fill-primary); border-radius: 6px; border: 1px solid var(--border-color-secondary);">
                {render_single_exhibition_table_html(ex)}
            </div>
        </div>
        """
        exhibitions_html += exhibition_html
    
    return count_info + exhibitions_html

def render_single_exhibition_table_html(exhibition: Dict[str, str]) -> str:
    """
    단일 전시회 정보를 HTML 테이블로 렌더링 (테마 적용)
    
    Args:
        exhibition (Dict[str, str]): 전시회 정보
        
    Returns:
        str: HTML 테이블 문자열
    """
    # 모든 필드 정의 (a.txt 기준)
    field_mapping = {
        'No': 'No',
        'ExhibitionID': 'ExhibitionID', 
        'Industry': 'Industry',
        'ExKoreanName': 'korean_name',
        'ExEnglishName': 'english_name',
        'NameAbbreviation': 'NameAbbreviation',
        'HostCycle': 'host_cycle',
        'HostType': 'HostType',
        'FirstHost': 'first_host',
        'OfficialSite': 'official_site',
        'HostInstitution': 'host_institution',
        'Staff': 'staff',
        'Tel': 'tel',
        'Email': 'email',
        'ExhibitItem': 'exhibit_item',
        'createdAt': 'createdAt',
        'logoImage': 'logoImage'
    }
    
    rows = ""
    for display_name, key in field_mapping.items():
        value = html.escape(exhibition.get(key, ''))
        if value:  # 값이 있는 경우만 표시
            rows += (
                f"<tr>"
                f"<th style='text-align: left; padding: 8px 12px; width: 150px; font-weight: 600; color: var(--body-text-color); background: var(--background-fill-secondary); border-bottom: 1px solid var(--border-color-primary);'>{display_name}</th>"
                f"<td style='padding: 8px 12px; color: var(--body-text-color); border-bottom: 1px solid var(--border-color-primary);'><span class='val' title='{value}' style='display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;'>{value}</span></td>"
                f"</tr>"
            )
    
    table = (
        "<table class='ex-table' style='table-layout: fixed; width: 100%; border-collapse: collapse; border: 1px solid var(--border-color-primary); border-radius: 6px; overflow: hidden;'>"
        "<colgroup><col class='label' style='width: 150px;'><col></colgroup>"
        "<tbody>" + rows + "</tbody>"
        "</table>"
    )
    return table

def render_single_exhibition_table(exhibition: Dict[str, str]) -> str:
    """
    단일 전시회 정보를 세로 표로 렌더링
    
    Args:
        exhibition (Dict[str, str]): 전시회 정보
        
    Returns:
        str: HTML 테이블 문자열
    """
    # 모든 필드 정의 (a.txt 기준)
    field_mapping = {
        'No': 'No',
        'ExhibitionID': 'ExhibitionID', 
        'Industry': 'Industry',
        'ExKoreanName': 'korean_name',
        'ExEnglishName': 'english_name',
        'NameAbbreviation': 'NameAbbreviation',
        'HostCycle': 'host_cycle',
        'HostType': 'HostType',
        'FirstHost': 'first_host',
        'OfficialSite': 'official_site',
        'HostInstitution': 'host_institution',
        'Staff': 'staff',
        'Tel': 'tel',
        'Email': 'email',
        'ExhibitItem': 'exhibit_item',
        'createdAt': 'createdAt',
        'logoImage': 'logoImage'
    }
    
    rows = []
    for display_name, key in field_mapping.items():
        value = html.escape(exhibition.get(key, ''))
        rows.append(
            f"<tr>"
            f"<th style='text-align: left; padding: 8px 12px; font-weight: 600; color: var(--body-text-color); background: var(--background-fill-secondary); border-bottom: 1px solid var(--border-color-primary);'>{display_name}</th>"
            f"<td style='padding: 8px 12px; color: var(--body-text-color); border-bottom: 1px solid var(--border-color-primary);'><span class='val' title='{value}' style='display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;'>{value}</span></td>"
            f"</tr>"
        )
    
    count_info = f"<div style='margin-bottom: 15px; color: var(--body-text-color); font-weight: 500;'>📋 데이터베이스 검색 결과 (1개)</div>"
    
    table = (
        f"{count_info}"
        "<div class='ex-card' style='padding: 0;'>"
        "<table class='ex-table' style='table-layout: fixed; width: 100%; border-collapse: collapse; border: 1px solid var(--border-color-primary); border-radius: 6px; overflow: hidden;'>"
        "<colgroup><col class='label' style='width: 150px;'><col></colgroup>"
        "<tbody>" + "".join(rows) + "</tbody>"
        "</table></div>"
    )
    return table

def extract_city_from_exhibition(exhibition: Dict[str, str]) -> str:
    """
    전시회 정보에서 도시 정보 추출
    
    Args:
        exhibition (Dict[str, str]): 전시회 정보
        
    Returns:
        str: 도시 이름
    """
    # official_site에서 도시 정보 추출 시도
    official_site = exhibition.get('official_site', '')
    if official_site:
        import re
        # 도시 관련 키워드 검색
        city_keywords = ['Seoul', 'Busan', 'Incheon', 'Daegu', 'Daejeon', 'Gwangju', 'Ulsan', 'Suwon', 'Goyang', 
                        '서울', '부산', '인천', '대구', '대전', '광주', '울산', '수원', '고양',
                        'New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia',
                        'San Antonio', 'San Diego', 'Dallas', 'San Jose', 'Austin', 'Jacksonville',
                        'Frankfurt', 'Munich', 'Berlin', 'Hamburg', 'Cologne', 'Düsseldorf',
                        'Paris', 'Lyon', 'Marseille', 'Toulouse', 'Nice', 'Nantes',
                        'London', 'Birmingham', 'Manchester', 'Glasgow', 'Liverpool', 'Leeds',
                        'Tokyo', 'Osaka', 'Nagoya', 'Sapporo', 'Kobe', 'Kyoto']
        
        for city in city_keywords:
            if city.lower() in official_site.lower():
                return city
    
    # 다른 필드에서 도시 정보 추출 시도
    for field in ['host_institution', 'ExhibitItem']:
        text = exhibition.get(field, '')
        if text:
            for city in ['Seoul', 'Busan', 'Incheon', 'Daegu', 'Daejeon', 'Gwangju', 'Ulsan', 'Suwon', 'Goyang',
                        '서울', '부산', '인천', '대구', '대전', '광주', '울산', '수원', '고양']:
                if city in text:
                    return city
    
    return ""

def _render_site_table(site_name: str, record: Dict[str, str], color: str) -> str:
    """
    단일 사이트 데이터를 표로 렌더링
    
    Args:
        site_name (str): 사이트 이름
        record (Dict[str, str]): 추출된 데이터
        color (str): 사이트 색상
        
    Returns:
        str: HTML 테이블 문자열
    """
    if not record:
        return f"<div class='ex-card' style='padding: 15px; border: 1px solid var(--border-color-primary); border-radius: 8px; background: var(--background-fill-secondary); margin-bottom: 15px;'><h4 style='margin: 0 0 10px 0; color: {color}; font-size: 16px; font-weight: 600;'>📊 {site_name} 검색 결과 없음</h4></div>"
    
    rows = []
    for k in EXTRACT_KEYS:
        value = html.escape(record.get(k, ""))
        rows.append(
            f"<tr>"
            f"<th style='text-align: left; padding: 8px 12px; font-weight: 600; color: var(--body-text-color); background: var(--background-fill-secondary); border-bottom: 1px solid var(--border-color-primary);'>{k}</th>"
            f"<td style='padding: 8px 12px; color: var(--body-text-color); border-bottom: 1px solid var(--border-color-primary);'><span class='val' title='{value}' style='display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;'>{value}</span></td>"
            f"</tr>"
        )
    
    table = (
        f"<div class='ex-card' style='padding: 0; margin-bottom: 15px;'>"
        f"<h4 style='margin: 0 0 15px 0; color: {color}; font-size: 18px; font-weight: 600;'>📊 {site_name} 검색 결과</h4>"
        "<table class='ex-table' style='table-layout: fixed; width: 100%; border-collapse: collapse; border: 1px solid var(--border-color-primary); border-radius: 6px; overflow: hidden;'>"
        "<colgroup><col class='label' style='width: 150px;'><col></colgroup>"
        "<tbody>" + "".join(rows) + "</tbody>"
        "</table></div>"
    )
    return table

def search_db_only(search_term: str, connection=None):
    """
    데이터베이스에서만 전시회 검색
    
    Args:
        search_term (str): 검색할 전시회 이름
        connection: 데이터베이스 연결 객체
        
    Returns:
        tuple: (표시용 HTML, 검색된 전시회 리스트) 또는 (오류 메시지, None)
    """
    # 데이터베이스에서 전시회 검색
    exhibitions = search_exhibition_in_db(search_term, connection)
    
    # DB 정보만 표시
    if exhibitions:
        db_table_html = render_db_selection_table(exhibitions)
        return db_table_html, exhibitions
    else:
        no_result_html = "<div style='color: #666; margin-bottom: 10px;'>📋 데이터베이스에 해당 전시회가 없습니다.</div>"
        return no_result_html, None

def search_and_extract_single(search_term: str, connection=None):
    """
    전시회 검색: 1) DB에서 먼저 찾아서 표시, 2) 3사이트에서 검색 및 드롭다운 표시
    
    Args:
        search_term (str): 검색할 전시회 이름
        connection: 데이터베이스 연결 객체
        
    Returns:
        tuple: (표시용 HTML, 검색 결과 데이터) 또는 (오류 메시지, None)
    """
    # 1. 데이터베이스에서 전시회 검색
    exhibitions = search_exhibition_in_db(search_term, connection)
    
    # DB 정보 표시
    db_table_html = render_db_selection_table(exhibitions) if exhibitions else "<div style='color: #666; margin-bottom: 10px;'>📋 데이터베이스에 해당 전시회가 없습니다.</div>"
    
    # 2. 3사이트 검색 (DB 결과와 상관없이 항상 실행)
    if exhibitions:
        # DB에 결과가 있는 경우: 첫 번째 결과로 검색
        ex = exhibitions[0]
        korean_name = ex['korean_name']
        english_name = ex['english_name']
        print(f"[DB 검색 성공] '{korean_name}' 찾음. 3사이트 검색 시작...")
        results_auma, results_gep, results_myfair = search_three_sites_for_one(korean_name, english_name)
    else:
        # DB에 결과가 없는 경우: 검색어로 직접 검색
        print(f"[DB 검색 실패] '{search_term}' 없음. 3사이트 직접 검색 시작...")
        results_auma = search_auma(search_term)
        results_gep = search_gep(search_term)
        results_myfair = search_myfair(search_term)
    
    # 3. 검색 결과를 드롭다운으로 표시
    dropdowns_html = render_search_results_dropdowns(results_auma, results_gep, results_myfair)
    
    # DB 정보와 드롭다운 결합
    final_html = db_table_html + "<hr>" + dropdowns_html
    
    # 저장용 데이터 구조화 (선택된 결과는 나중에 업데이트됨)
    result_data = {
        "korean_name": exhibitions[0]['korean_name'] if exhibitions else search_term,
        "english_name": exhibitions[0]['english_name'] if exhibitions else search_term,
        "AUMA": {},
        "GEP": {},
        "Myfair": {},
        "db_results": exhibitions,
        "search_results": {
            "auma": results_auma,
            "gep": results_gep,
            "myfair": results_myfair
        }
    }
    
    return final_html, result_data

def extract_from_selected_choices(auma_choice: str, gep_choice: str, myfair_choice: str, search_data: Dict):
    """
    사용자가 선택한 드롭다운 항목으로 데이터 추출
    
    Args:
        auma_choice: AUMA 드롭다운 선택값
        gep_choice: GEP 드롭다운 선택값
        myfair_choice: Myfair 드롭다운 선택값
        search_data: 이전 검색 결과 데이터
        
    Returns:
        tuple: (표시용 HTML, 결과 데이터)
    """
    if not search_data or 'search_results' not in search_data:
        return "검색 데이터가 없습니다.", None
    
    results_auma = search_data['search_results'].get('auma', [])
    results_gep = search_data['search_results'].get('gep', [])
    results_myfair = search_data['search_results'].get('myfair', [])
    
    # 선택된 URL 추출
    url_auma, url_gep, url_myfair = extract_selected_urls(
        auma_choice, results_auma, gep_choice, results_gep, myfair_choice, results_myfair
    )
    
    urls = [url_auma, url_gep, url_myfair]
    
    # 선택된 URL들에서 병렬로 정보 추출
    records = _extract_multiple_parallel(urls)
    rec_auma, rec_gep, rec_myfair = records
    
    # 각 사이트 결과를 개별 표로 생성
    auma_html = _render_site_table("AUMA", rec_auma, DATASET_COLORS.get(1, "#D7263D"))
    gep_html = _render_site_table("GEP", rec_gep, DATASET_COLORS.get(2, "#1B9AAA"))
    myfair_html = _render_site_table("Myfair", rec_myfair, DATASET_COLORS.get(3, "#2E7D32"))
    
    # 결과 결합
    final_html = auma_html + gep_html + myfair_html
    
    # 저장용 데이터 업데이트
    result_data = search_data.copy()
    result_data.update({
        "AUMA": rec_auma,
        "GEP": rec_gep,
        "Myfair": rec_myfair
    })
    
    return final_html, result_data

def process_selected_exhibition(selected_index: float, exhibitions_list: List[Dict], enable_search: bool, connection=None):
    """
    선택된 전시회를 처리하여 상세 정보 표시 또는 전체 검색/추출 수행
    
    Args:
        selected_index (float): 선택된 전시회 인덱스
        exhibitions_list (List[Dict]): 검색된 전시회 리스트
        enable_search (bool): 검색기능 활성화 여부
        connection: 데이터베이스 연결 객체
        
    Returns:
        tuple: (상세 정보 HTML, 전체 결과 HTML, 저장 데이터) 또는 (오류 메시지, None, None)
    """
    if selected_index is None or not exhibitions_list or selected_index >= len(exhibitions_list):
        return "선택된 전시회가 없습니다.", None, None
    
    # 선택된 전시회 정보
    selected_exhibition = exhibitions_list[int(selected_index)]
    korean_name = selected_exhibition['korean_name']
    english_name = selected_exhibition['english_name']
    
    # 상세 정보 표시
    details_html = render_single_exhibition_table(selected_exhibition)
    
    if not enable_search:
        # 검색기능 비활성화: 상세 정보만 표시
        result_data = {
            "korean_name": korean_name,
            "english_name": english_name,
            "AUMA": {},
            "GEP": {},
            "Myfair": {},
            "db_results": [selected_exhibition]
        }
        return details_html, None, result_data
    else:
        # 검색기능 활성화: 3사이트 검색 및 추출
        print(f"[선택된 전시회] '{korean_name}' 3사이트 검색 시작...")
        url_auma, url_gep, url_myfair = search_three_sites_for_one(korean_name, english_name)
        urls = [url_auma, url_gep, url_myfair]
        
        # 병렬로 정보 추출
        records = _extract_multiple_parallel(urls)
        rec_auma, rec_gep, rec_myfair = records
        
        # 각 사이트 결과를 개별 표로 생성
        auma_html = _render_site_table("AUMA", rec_auma, DATASET_COLORS.get(1, "#D7263D"))
        gep_html = _render_site_table("GEP", rec_gep, DATASET_COLORS.get(2, "#1B9AAA"))
        myfair_html = _render_site_table("Myfair", rec_myfair, DATASET_COLORS.get(3, "#2E7D32"))
        
        # 상세 정보와 3사이트 정보 결합
        final_html = details_html + "<hr>" + auma_html + gep_html + myfair_html
        
        result_data = {
            "korean_name": korean_name,
            "english_name": english_name,
            "AUMA": rec_auma,
            "GEP": rec_gep,
            "Myfair": rec_myfair,
            "db_results": [selected_exhibition]
        }
        
        return details_html, final_html, result_data







# --------------------------------------------------------------------------------------
# 로그인 상태 관리 함수
# --------------------------------------------------------------------------------------



def try_login(uid: str, pw: str, state):
    """
    SQL 서버 로그인 시도 및 상태 관리, 없는걸로 하면 전부 오류 뜸
    
    Args:
        uid (str): 사용자 ID
        pw (str): 비밀번호
        state: 현재 로그인 상태
        
    Returns:
        tuple: (로그인 섹션 가시성, 오류 메시지, 업데이트된 상태)
    """
    if not uid or not pw:
        return gr.update(visible=True), gr.update(value="ID와 PW를 입력하세요.", visible=True), state
    
    try:
        # SQL Server 연결 문자열 생성 및 접속 시도
        cs = make_cs_sql_login(uid, pw)
        conn = pyodbc.connect(cs)
        
        # 연결 테스트를 위한 간단한 쿼리 실행
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        test_result = cursor.fetchone()
        
        # 로그인 성공 시 상태 업데이트
        new_state = {"logged_in": True, "connection": conn}
        return gr.update(visible=False), gr.update(value="로그인 성공!", visible=False), new_state
        
    except Exception as e:
        # 로그인 실패 시 오류 메시지 표시
        error_msg = f"로그인 실패: {str(e)}"
        return gr.update(visible=True), gr.update(value=error_msg, visible=True), state

# --------------------------------------------------------------------------------------
# Gradio 웹 인터페이스 구성
# --------------------------------------------------------------------------------------

with gr.Blocks(css=CUSTOM_CSS) as demo:
    # 애플리케이션 로그인 상태 관리
    login_state = gr.State({"logged_in": False, "connection": None})
    
    # 애플리케이션 제목 표시
    gr.Markdown(f"# {APP_TITLE}")
    
    # 로그인 상태 표시 영역
    login_status = gr.Markdown("### 🔒 로그인이 필요합니다")
    
    # 로그인 폼 섹션
    with gr.Group(visible=True) as login_section:
        gr.Markdown("## SQL 서버 로그인")
        with gr.Row():
            with gr.Column(scale=1):
                uid_input = gr.Textbox(label="ID", placeholder="SQL Server ID 입력")
            with gr.Column(scale=1):
                pw_input = gr.Textbox(label="Password", type="password", placeholder="SQL Server 비밀번호 입력")
        
        with gr.Row():
            login_btn = gr.Button("로그인", variant="primary")
        
        # 로그인 오류 메시지 표시 영역
        login_error = gr.Textbox(label="오류 메시지", visible=False, interactive=False)
    
        # 탭 기반 메뉴 구성
    with gr.Tabs():
        # 첫 번째 탭: 데이터베이스 검색
        with gr.Tab("데이터베이스 검색"):
            gr.Markdown("전시회 이름을 검색하여 **SQL 서버**에서 해당 전시회 정보를 확인합니다.")
            
            # 검색 입력 폼
            with gr.Row():
                db_search_input = gr.Textbox(label="전시회명 검색", placeholder="검색할 전시회 이름을 입력하세요")
                db_search_btn = gr.Button("DB 검색", variant="primary")
            
            # 검색 결과 표시 영역
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### 📊 데이터베이스 검색 결과")
                    db_search_output = gr.HTML("검색 버튼을 누르면 여기에 결과가 표시됩니다.")
            
            # DB 검색 결과 저장용 상태 변수
            s_db_exhibitions = gr.State()
            
            def check_login_and_db_search(search_term, state):
                """
                로그인 상태 확인 후 DB 검색 실행
                
                Args:
                    search_term (str): 검색어
                    state: 로그인 상태
                    
                Returns:
                    tuple: (결과 HTML, 검색된 전시회 리스트) 또는 (오류 메시지, None)
                """
                if not state or not state.get("logged_in"):
                    return "로그인이 필요합니다.", None
                if not search_term or not search_term.strip():
                    return "검색어를 입력하세요.", None
                try:
                    connection = state.get("connection")
                    # DB 조회
                    exhibitions = search_exhibition_in_db(search_term.strip(), connection)
                    
                    if not exhibitions:
                        return "<div style='color: var(--body-text-color-subdued); margin-bottom: 10px;'>📋 데이터베이스에 해당 전시회가 없습니다.</div>", None
                    
                    # 검색 결과 표시 (모든 전시회 정보 표시)
                    result_html = render_db_table_with_selection(exhibitions)
                    return result_html, exhibitions
                        
                except Exception as e:
                    return f"검색 중 오류: {str(e)}", None
            
            # DB 검색 버튼 이벤트 연결
            db_search_btn.click(
                fn=check_login_and_db_search,
                inputs=[db_search_input, login_state],
                outputs=[db_search_output, s_db_exhibitions],
            )
        
        # 두 번째 탭: 웹 검색 및 추출
        with gr.Tab("웹 검색 및 추출"):
            gr.Markdown("데이터베이스에서 전시회를 선택하면 **3개 사이트**에서 자동으로 검색 및 **LLM 데이터 추출**을 수행합니다.")
            
            # 전시회 선택 폼
            with gr.Row():
                web_search_input = gr.Textbox(label="전시회명 검색", placeholder="검색할 전시회 이름을 입력하세요")
                web_search_btn = gr.Button("DB에서 전시회 찾기", variant="primary")
            
            # DB 전시회 선택 영역
            with gr.Column(visible=False) as db_selection_column:
                gr.Markdown("### 🔍 데이터베이스에서 전시회 선택")
                exhibition_dropdown = gr.Dropdown(
                    label="전시회 선택", 
                    choices=[], 
                    value=None,
                    interactive=True
                )
                
                # 선택된 전시회로 3사이트 검색 버튼
                db_search_execute_btn = gr.Button("선택된 전시회로 3사이트 검색", variant="primary", visible=False)
            
            # 웹 검색 결과 표시 영역
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### 🌐 웹 검색 및 추출 결과")
                    web_search_output = gr.HTML("전시회를 선택하고 웹 검색을 실행하면 여기에 결과가 표시됩니다.")
                    
                    # 드롭다운 선택 영역 (초기에는 숨김)
                    with gr.Column(visible=False) as dropdown_selection_column:
                        gr.Markdown("### 🔍 검색 결과에서 전시회 선택")
                        
                        with gr.Row():
                            with gr.Column():
                                auma_dropdown = gr.Dropdown(
                                    label="AUMA 검색 결과 선택",
                                    choices=["선택 안함"],
                                    value="선택 안함",
                                    interactive=True
                                )
                            with gr.Column():
                                gep_dropdown = gr.Dropdown(
                                    label="GEP 검색 결과 선택", 
                                    choices=["선택 안함"],
                                    value="선택 안함",
                                    interactive=True
                                )
                            with gr.Column():
                                myfair_dropdown = gr.Dropdown(
                                    label="Myfair 검색 결과 선택",
                                    choices=["선택 안함"], 
                                    value="선택 안함",
                                    interactive=True
                                )
                        
                        # 선택된 결과로 데이터 추출 버튼
                        extract_from_selections_btn = gr.Button("선택된 전시회로 데이터 추출 실행", variant="primary", visible=False)
                    
                    # 최종 추출 결과 표시 영역
                    extraction_results_output = gr.HTML(visible=False)
                    
                    with gr.Row():
                        save_web_btn = gr.Button("결과 엑셀로 저장")
                    file_web = gr.File(label="엑셀 파일", interactive=False, file_count="single", file_types=[".xlsx"])
            
            # 웹 검색 결과 저장용 상태 변수
            s_web_result = gr.State()
            # 검색된 전시회 목록 저장용 상태 변수
            s_web_exhibitions = gr.State()
            # 검색 결과 데이터 저장용 상태 변수
            s_search_data = gr.State()
            
            def check_login_and_web_search(search_term, state):
                """
                로그인 상태 확인 후 웹 검색 실행 (DB 결과와 상관없이 항상 3사이트 검색)
                
                Args:
                    search_term (str): 검색어
                    state: 로그인 상태
                    
                Returns:
                    tuple: (결과 HTML, 드롭다운 업데이트들, 선택 컬럼 가시성, 추출 버튼 가시성, 검색 데이터)
                """
                if not state or not state.get("logged_in"):
                    return "로그인이 필요합니다.", gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update(visible=False), None
                if not search_term or not search_term.strip():
                    return "검색어를 입력하세요.", gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update(visible=False), None
                try:
                    connection = state.get("connection")
                    # DB 조회
                    exhibitions = search_exhibition_in_db(search_term.strip(), connection)
                    
                    # DB 정보 표시
                    if exhibitions:
                        db_html = render_db_table_with_selection(exhibitions)
                        # DB에 결과가 있는 경우: 아직 3사이트 검색 안 함 (사용자가 DB에서 선택해야 함)
                        results_auma, results_gep, results_myfair = [], [], []
                        
                        # DB 선택용 드롭다운 옵션 생성
                        db_choices = []
                        for i, ex in enumerate(exhibitions):
                            korean_name = ex.get('korean_name', '')
                            english_name = ex.get('english_name', '')
                            industry = ex.get('Industry', '')
                            first_host = ex.get('first_host', '')
                            city = extract_city_from_exhibition(ex)
                            
                            display_text = f"{i+1}. {korean_name}"
                            if english_name:
                                display_text += f" ({english_name})"
                            if city:
                                display_text += f" - {city}"
                            if industry:
                                display_text += f" [{industry}]"
                            if first_host and first_host != 'None':
                                display_text += f" (시작: {first_host})"
                            
                            db_choices.append(display_text)
                        
                        # DB 선택 컬럼 표시
                        return (db_html,
                               gr.update(choices=db_choices, visible=True),
                               gr.update(choices=["선택 안함"], visible=False),
                               gr.update(choices=["선택 안함"], visible=False),
                               gr.update(choices=["선택 안함"], visible=False),
                               gr.update(visible=True),  # DB 선택 컬럼
                               gr.update(visible=False), # 사이트 드롭다운 컬럼
                               gr.update(visible=False), # 추출 버튼
                               exhibitions,  # DB 결과를 s_web_exhibitions에 저장
                               None)  # search_data는 아직 없음
                    else:
                        db_html = "<div style='color: var(--body-text-color-subdued); margin-bottom: 10px;'>📋 데이터베이스에 해당 전시회가 없습니다. 3사이트에서 직접 검색합니다.</div>"
                        # DB에 결과가 없는 경우: 검색어로 직접 3사이트 검색
                        print(f"[DB 검색 실패] '{search_term}' 없음. 3사이트 직접 검색 시작...")
                        results_auma = search_auma(search_term)
                        results_gep = search_gep(search_term)
                        results_myfair = search_myfair(search_term)
                        
                        # 드롭다운 옵션 생성
                        auma_choices = ["선택 안함"] + [f"{i+1}. {result['display_text']}" for i, result in enumerate(results_auma)]
                        gep_choices = ["선택 안함"] + [f"{i+1}. {result['display_text']}" for i, result in enumerate(results_gep)]
                        myfair_choices = ["선택 안함"] + [f"{i+1}. {result['display_text']}" for i, result in enumerate(results_myfair)]
                        
                        # 드롭다운 HTML 생성
                        dropdowns_html = render_search_results_dropdowns(results_auma, results_gep, results_myfair)
                        
                        # 전체 HTML 결합
                        final_html = db_html + "<hr>" + dropdowns_html
                        
                        # 검색 데이터 구조화
                        search_data = {
                            "korean_name": search_term,
                            "english_name": search_term,
                            "AUMA": {},
                            "GEP": {},
                            "Myfair": {},
                            "db_results": [],
                            "search_results": {
                                "auma": results_auma,
                                "gep": results_gep,
                                "myfair": results_myfair
                            }
                        }
                        
                        return (final_html,
                               gr.update(choices=["선택 안함"], visible=False),
                               gr.update(choices=auma_choices, visible=True),
                               gr.update(choices=gep_choices, visible=True),
                               gr.update(choices=myfair_choices, visible=True),
                               gr.update(visible=False), # DB 선택 컬럼
                               gr.update(visible=True),  # 사이트 드롭다운 컬럼
                               gr.update(visible=True),  # 추출 버튼
                               [],  # s_web_exhibitions는 빈 리스트
                               search_data)
                        
                except Exception as e:
                    return f"검색 중 오류: {str(e)}", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update(visible=False), [], None
            
            def execute_db_selection_and_search(db_choice, exhibitions_list, state):
                """
                DB에서 선택된 전시회로 3사이트 검색 실행
                
                Args:
                    db_choice: DB 드롭다운 선택값
                    exhibitions_list: DB 검색 결과 리스트
                    state: 로그인 상태
                    
                Returns:
                    tuple: (검색 결과 HTML, 드롭다운 업데이트들, 컬럼 가시성, 검색 데이터)
                """
                if not state or not state.get("logged_in"):
                    return "로그인이 필요합니다.", gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update(visible=False), None
                
                if not db_choice or not exhibitions_list:
                    return "선택된 전시회가 없습니다.", gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update(visible=False), None
                
                try:
                    # 선택된 텍스트에서 인덱스 추출
                    import re
                    match = re.match(r'^(\d+)\.', db_choice)
                    if not match:
                        return "선택된 전시회를 찾을 수 없습니다.", gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update(visible=False), None
                    
                    selected_index = int(match.group(1)) - 1
                    selected_exhibition = exhibitions_list[selected_index]
                    korean_name = selected_exhibition['korean_name']
                    english_name = selected_exhibition['english_name']
                    
                    print(f"[선택된 전시회] '{korean_name}' 3사이트 검색 시작...")
                    results_auma, results_gep, results_myfair = search_three_sites_for_one(korean_name, english_name)
                    
                    # 드롭다운 옵션 생성
                    auma_choices = ["선택 안함"] + [f"{i+1}. {result['display_text']}" for i, result in enumerate(results_auma)]
                    gep_choices = ["선택 안함"] + [f"{i+1}. {result['display_text']}" for i, result in enumerate(results_gep)]
                    myfair_choices = ["선택 안함"] + [f"{i+1}. {result['display_text']}" for i, result in enumerate(results_myfair)]
                    
                    # 드롭다운 HTML 생성
                    dropdowns_html = render_search_results_dropdowns(results_auma, results_gep, results_myfair)
                    
                    # 검색 데이터 구조화
                    search_data = {
                        "korean_name": korean_name,
                        "english_name": english_name,
                        "AUMA": {},
                        "GEP": {},
                        "Myfair": {},
                        "db_results": [selected_exhibition],
                        "search_results": {
                            "auma": results_auma,
                            "gep": results_gep,
                            "myfair": results_myfair
                        }
                    }
                    
                    return (dropdowns_html,
                           gr.update(choices=auma_choices, visible=True),
                           gr.update(choices=gep_choices, visible=True),
                           gr.update(choices=myfair_choices, visible=True),
                           gr.update(visible=True),  # 사이트 드롭다운 컬럼
                           gr.update(visible=True),  # 추출 버튼
                           [selected_exhibition],  # s_web_exhibitions 업데이트
                           search_data)
                           
                except Exception as e:
                    return f"3사이트 검색 중 오류: {str(e)}", gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update(visible=False), [], None

            def execute_extraction_from_selections(auma_choice, gep_choice, myfair_choice, search_data):
                """
                드롭다운에서 선택된 항목으로 데이터 추출 실행
                
                Args:
                    auma_choice: AUMA 드롭다운 선택값
                    gep_choice: GEP 드롭다운 선택값
                    myfair_choice: Myfair 드롭다운 선택값
                    search_data: 검색 결과 데이터
                    
                Returns:
                    tuple: (추출 결과 HTML, 업데이트된 데이터)
                """
                if not search_data:
                    return "검색 데이터가 없습니다.", None
                
                try:
                    final_html, result_data = extract_from_selected_choices(
                        auma_choice, gep_choice, myfair_choice, search_data
                    )
                    
                    return final_html, result_data
                    
                except Exception as e:
                    return f"데이터 추출 중 오류: {str(e)}", None
            
            # 웹 검색 버튼 이벤트 연결
            web_search_btn.click(
                fn=check_login_and_web_search,
                inputs=[web_search_input, login_state],
                outputs=[web_search_output, exhibition_dropdown, auma_dropdown, gep_dropdown, myfair_dropdown, db_selection_column, dropdown_selection_column, extract_from_selections_btn, s_search_data],
            )
            
            # 전시회 선택 시 버튼 표시 이벤트
            exhibition_dropdown.change(
                fn=lambda choice, exhibitions, state: gr.update(visible=True) if choice and exhibitions and state and state.get("logged_in") else gr.update(visible=False),
                inputs=[exhibition_dropdown, s_web_exhibitions, login_state],
                outputs=[db_search_execute_btn],
            )
            
            # DB 전시회 선택 후 3사이트 검색 버튼 이벤트
            db_search_execute_btn.click(
                fn=execute_db_selection_and_search,
                inputs=[exhibition_dropdown, s_web_exhibitions, login_state],
                outputs=[web_search_output, auma_dropdown, gep_dropdown, myfair_dropdown, dropdown_selection_column, extract_from_selections_btn, s_search_data],
            ).then(
                fn=lambda: gr.update(visible=True),
                outputs=[dropdown_selection_column]
            )
            
            # 선택된 결과로 데이터 추출 버튼 이벤트
            extract_from_selections_btn.click(
                fn=execute_extraction_from_selections,
                inputs=[auma_dropdown, gep_dropdown, myfair_dropdown, s_search_data],
                outputs=[extraction_results_output, s_web_result],
            ).then(
                fn=lambda: gr.update(visible=True),
                outputs=[extraction_results_output]
            )
            
            # 엑셀 저장 버튼 이벤트 연결
            save_web_btn.click(
                fn=lambda data: save_merged_excel([data] if data else [], "web_search_result"),
                inputs=[s_web_result],
                outputs=[file_web]
            )
        


    # 로그인 버튼 이벤트 연결
    login_btn.click(
        fn=try_login,
        inputs=[uid_input, pw_input, login_state],
        outputs=[login_section, login_error, login_state]
    ).then(
        # 로그인 성공 시 UI 상태 업데이트
        fn=lambda state: (gr.update(visible=False), gr.update(value="### ✅ 로그인되었습니다")) if state and state.get("logged_in") else (gr.update(visible=True), gr.update()),
        inputs=[login_state],
        outputs=[login_section, login_status]
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7869)
