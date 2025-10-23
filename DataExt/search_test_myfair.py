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
SEARCH_URL = "https://myfair.co/"
SEARCH_QUERY = "오토모티브 월드 도쿄"

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

    search_box = driver.find_element(By.XPATH, "//input[@placeholder='박람회명 검색']")
    search_box.send_keys(SEARCH_QUERY)
    time.sleep(0.1)

    print("검색어 입력 후 Enter 키를 누릅니다.")
    search_box.send_keys(Keys.ENTER)

    # --- 4. 결과 대기 ---
    print("검색 완료. 결과 링크가 나타날 때까지 최대 20초간 기다립니다...")
    try:
        wait = WebDriverWait(driver, 20)
        # --- myfair의 검색 결과 컨테이너 클래스 이름인 'css-azmimp'를 기다립니다. ---
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "css-azmimp")))
        print("-> 검색 결과가 성공적으로 로드되었습니다.")
    except TimeoutException:
        print("[오류] 검색 결과를 기다리다 시간 초과되었습니다.")
        driver.save_screenshot('error_screenshot.png')
        print("현재 화면을 'error_screenshot.png' 파일로 저장했습니다.")
        raise

    # --- 5. 최신 링크 찾기 ---
    # --- 각 결과 카드를 모두 가져옵니다. 클래스 이름: css-1byidqq ---
    xpath_selector = "//div[@class='css-1byidqq' and .//span[@class='css-1nutr9u']]"
    all_cards = driver.find_elements(By.XPATH, xpath_selector)

    if not all_cards:
        print(f"[오류] 검색 결과는 로드되었으나, 결과 카드를 찾지 못했습니다.")
    else:
        print(f"-> 총 {len(all_cards)}개의 관련 항목을 찾았습니다.")
        latest_year = 0
        latest_month = 0
        link_to_click = None

        # --- '카드(card)'를 하나씩 순회합니다. ---
        for card in all_cards:
            try:
                # --- 각 카드 안에서 '날짜 텍스트'와 '링크'를 별도로 찾습니다. ---
                # 날짜가 들어있는 span 태그를 찾습니다.
                date_span = card.find_element(By.CLASS_NAME, "css-1nutr9u")
                date_text = date_span.text

                # 제목과 링크가 들어있는 a 태그를 찾습니다. 클래스 이름이 여러 개이므로 XPath를 사용합니다.
                link_element = card.find_element(By.XPATH, ".//a[contains(@class, 'text-md')]")
                link_text = link_element.text
                
                print(f"   - 발견된 항목: [날짜: {date_text}] [제목: {link_text.strip()}]")

                # --- 링크의 제목에 검색어가 포함되어 있는지 먼저 확인합니다. ---
                query_words = SEARCH_QUERY.split()
                title_contains_query = all(word in link_text for word in query_words)

                if title_contains_query:
                    year_match = re.search(r'(20\d{2})', date_text)
                    month_match = re.search(r'(\d{1,2})월', date_text)
                    if year_match and month_match:
                        year = int(year_match.group(1))
                        month = int(month_match.group(1))
                        if year > latest_year:
                            latest_year = year
                            latest_month = month
                            link_to_click = link_element
                        elif year == latest_year:
                            if month > latest_month:
                                latest_month = month
                                link_to_click = link_element
                else:
                    # 제목에 검색어가 포함되지 않은 경우 건너뜁니다.
                    print(f"     - (건너뜀) 제목에 검색어 '{SEARCH_QUERY}'가 포함되지 않았습니다.")

            except Exception as e:
                print(f"   - [경고] 일부 항목을 처리하는 중 오류 발생: {e}")
                continue
        
        # --- 6. 최신 링크 클릭 및 확인 ---
        if link_to_click:
            print(f"\n-> 가장 최신 연도({latest_year})의 링크를 클릭합니다: '{link_to_click.text.strip()}'")
            driver.execute_script("arguments[0].click();", link_to_click)
            time.sleep(0.1)
            
            print("\n성공! 상세 페이지로 이동했습니다.")
            print(f"현재 URL: {driver.current_url}")
        else:
            print("\n[알림] 검색 결과에서 연도가 포함된 최신 링크를 찾지 못했습니다.")

except Exception as e:
    print(f"\n[치명적 오류] 스크립트 실행 중 예외가 발생했습니다: {e}")

finally:
    # --- 7. 마무리 ---
    print("\n브라우저를 자동으로 종료합니다.")
    driver.quit()
    print("브라우저가 종료되었습니다.")