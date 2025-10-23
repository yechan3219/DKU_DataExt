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

# --- 1. 설정: 검색할 URL과 키워드를 지정합니다 ---
SEARCH_URL = "https://www.auma.de/en/"
SEARCH_QUERY = "tokyo automotive world"

# --- 2. 드라이버 설정: 봇으로 감지되지 않도록 옵션을 추가합니다 ---
options = webdriver.ChromeOptions()
# --- headless를 사용하지 않으려면 아래 두 줄을 주석처리 ---
options.add_argument("--headless=new") # 새로운 헤드리스 모드 사용
options.add_argument("--window-size=1920,1080") # 가상 화면 크기 지정
# -----------------------------------------------------------
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--start-maximized") # 브라우저를 최대화하여 실행

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)

try:
    # --- 3. 검색 실행 ---
    print(f"'{SEARCH_URL}' 페이지로 이동하여 '{SEARCH_QUERY}' 검색을 시작합니다.")
    driver.get(SEARCH_URL)
    time.sleep(0.1)

    search_box = driver.find_element(By.ID, "searchText")
    search_box.send_keys(SEARCH_QUERY)
    time.sleep(0.1)

    print("검색어 입력 후 Enter 키를 누릅니다.")
    search_box.send_keys(Keys.ENTER)

    # --- 4. 결과 대기 ---
    print("검색 완료. 결과 링크가 나타날 때까지 최대 20초간 기다립니다...")
    try:
        wait = WebDriverWait(driver, 20)
        # 검색 결과가 자바스크립트로 로드되므로, 결과가 담기는 컨테이너('totalSearchView') 안의 링크(a 태그)가 나타날 때까지 기다립니다.
        result_links_xpath = "//*[@id='totalSearchView']//a"
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "trade-fair-result")))
        print("-> 검색 결과가 성공적으로 로드되었습니다.")
    except TimeoutException:
        print("[오류] 검색 결과를 기다리다 시간 초과되었습니다. 웹사이트 구조가 변경되었거나 결과가 없을 수 있습니다.")
        # 오류 발생 시 현재 화면을 캡처하여 원인 파악을 돕습니다.
        driver.save_screenshot('error_screenshot.png')
        print("현재 화면을 'error_screenshot.png' 파일로 저장했습니다.")
        # try...finally 블록으로 이동하여 드라이버를 종료합니다.
        raise 


    # --- 5. 최신 링크 찾기 ---
    # --- 전체 항목의 개수 파악 ---
    row_xpath = "//tbody[@class='trade-fair-result__body']/tr[@class='trade-fair-result__row']"
    try:
        all_rows = driver.find_elements(By.XPATH, row_xpath)
        row_count = len(all_rows)
    except:
        row_count = 0

    if row_count == 0:
        print(f"[오류] 검색 결과는 로드되었으나, 링크가 포함된 결과 테이블을 찾지 못했습니다.")
    else:
        print(f"-> 총 {row_count}개의 관련 항목을 찾았습니다.")
        latest_year = 0
        latest_month = 0
        link_to_click_info = None

        month_map = {
            'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
            'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12
        }
        
        for i in range(row_count):
            # --- 새로고침 발생시 재시도 로직을 위한 반복문 ---
            retries = 3
            for attempt in range(retries):
                try:
                    # 매 시도마다 'i+1'번째 요소를 '새로' 찾습니다.
                    current_row = driver.find_element(By.XPATH, f"({row_xpath})[{i+1}]")

                    date_text = current_row.find_element(By.CLASS_NAME, "trade-fair-result__cell--strTermin").text
                    link_element = current_row.find_element(By.CLASS_NAME, "trade-fair-result__link")
                    link_text = link_element.text
                    link_href = link_element.get_attribute('href')
                    city_text = current_row.find_element(By.CLASS_NAME, "trade-fair-result__cell--strStadt").text
                    country_text = current_row.find_element(By.CLASS_NAME, "trade-fair-result__cell--strLand").text
                    
                    print(f"   - {i+1}번째 항목 처리 시도 ({attempt+1}/{retries}): [날짜: {date_text}] [제목: {link_text.strip()}]")

                    combined_text = f"{link_text} {city_text} {country_text}"
                    
                    query_words = SEARCH_QUERY.split()
                    title_contains_query = all(word.lower() in combined_text.lower() for word in query_words)

                    if title_contains_query:
                        year_match = re.search(r'(20\d{2})', date_text)
                        if year_match:
                            year = int(year_match.group(1))
                            month = 0
                            for name, num in month_map.items():
                                if name.lower() in date_text.lower(): month = num; break
                            if month == 0:
                                month_num_match = re.search(r'\.(\d{2})\.', date_text)
                                if month_num_match: month = int(month_num_match.group(1))

                            if year > latest_year:
                                latest_year, latest_month = year, month
                                link_to_click_info = {'text': link_text, 'href': link_href}
                            elif year == latest_year and month > latest_month:
                                latest_month = month
                                link_to_click_info = {'text': link_text, 'href': link_href}
                    else:
                        print(f"     - (건너뜀) 검색어 불일치")
                    
                    # --- 처리에 성공하면 재시도 루프를 빠져나갑니다. ---
                    break

                except Exception as e:
                    # --- 오류 발생 시 재시도 메시지를 출력하고 잠시 기다립니다. ---
                    print(f"   - [경고] {i+1}번째 항목 처리 중 오류 발생. ({attempt + 1}/{retries} 번째 재시도)")
                    time.sleep(1) # 1초 대기 후 재시도
                    if attempt == retries - 1:
                        print(f"   - [실패] {i+1}번째 항목 처리에 최종 실패했습니다.")

    # --- 6. 최신 링크 클릭 및 확인 ---
    if link_to_click_info:
        print(f"\n-> '{SEARCH_QUERY}'와 일치하는 가장 최신 날짜({latest_year}년 {latest_month}월)의 링크를 클릭합니다: '{link_to_click_info['text'].strip()}'")
        driver.get(link_to_click_info['href'])
        time.sleep(0.1)
        
        print("\n성공! 상세 페이지로 이동했습니다.")
        print(f"현재 URL: {driver.current_url}")
    else:
        print(f"\n[알림] '{SEARCH_QUERY}'와 일치하고 날짜가 포함된 최신 링크를 찾지 못했습니다.")

except Exception as e:
    print(f"\n[치명적 오류] 스크립트 실행 중 예외가 발생했습니다: {e}")

finally:
    # --- 7. 마무리 ---
    print("\n브라우저를 자동으로 종료합니다.")
    driver.quit()
    print("브라우저가 종료되었습니다.")