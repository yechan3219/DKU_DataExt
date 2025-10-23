# llama.py
import os
import re
import json
import requests
from typing import List, Dict, Any
from datetime import datetime

# ==== 런타임 설정 (환경변수로 덮어쓰기 가능) ===============================
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = os.getenv("LLM_MODEL", "llama3.2")
NUM_CTX = int(os.getenv("NUM_CTX", "10000"))        
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2")) 
TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "500"))    
PROMPT_MD = os.getenv("PROMPT_MD") or os.path.join(os.path.dirname(__file__), "prompt.md")

# ==== 스키마 키 =============================================================
KEYS = [
    "전시회 국문명","영문명(Full Name)","영문명(약자)",
    "개최 시작","개최 종료",
    "개최장소(국문)","개최장소(영어)","국가","도시",
    "첫 개최년도","개최 주기","공식 홈페이지",
    "주최기관","담당자","전화","이메일",
    "산업분야","전시품목","출처"
]

# ==== 유틸 ==================================================================
def load_prompt_md(path: str = PROMPT_MD) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        # 파일이 없어도 동작하도록 안전 기본값
        return "너는 전시회 정보 추출기이다. 입력 마크다운에서 지정된 키만 추출하고 JSON만 출력하라."

def _safe_json_parse(text: str) -> Dict[str, Any]:
    """응답에서 JSON만 안전하게 뽑기 (grammar 쓰지만 혹시 모를 보호)"""
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        # 첫 {부터 마지막 }까지 잘라 재시도
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except Exception:
                return {}
        return {}

# ==== 날짜/연도 정규화 ======================================================
def normalize_date(s: str) -> str:
    """다양한 표기 → YYYY-MM-DD (모르면 그대로 반환)"""
    if not s:
        return ""
    s = s.strip()

    # 2025.05.06 ~ 05.08 / 2025-05-06 to 05-08 등 범위 케이스의 앞/뒤만 깔끔히 쓰고 싶다면
    # 이 함수 외부에서 '개최 시작','개최 종료'를 각각 원문에서 따로 추출하는 게 더 낫지만
    # 여기서는 단일 값만 들어온다고 보고 정규화만 수행.
    # 2025.05.06 / 2025-05-06 / 2025/5/6 / 2025년 5월 6일
    m = re.search(r"(\d{4})[.\-/\s년](\d{1,2})[.\-/\s월](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    # 2025.05 / 2025-5
    m = re.search(r"(\d{4})[.\-/\s년](\d{1,2})", s)
    if m:
        y, mo = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-01"

    # May 6, 2025 / 6 May 2025 등 간단 영문 포맷(있으면)
    try:
        from dateutil import parser  # conda/pip에 dateutil이 없다면 위의 규칙만 사용
        dt = parser.parse(s, fuzzy=True, dayfirst=False)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return s

def normalize_year(s: str) -> str:
    """첫 개최년도 등은 'YYYY'만 유지"""
    if not s:
        return ""
    m = re.search(r"(\d{4})", s)
    return m.group(1) if m else ""

def normalize_url(s: str) -> str:
    if not s:
        return ""
    s = s.strip().strip("[]()")
    if s.startswith("http://") or s.startswith("https://"):
        return s
    return ""  # http(s) 아닌 건 버림

# ==== Ollama 호출 (Grammar 강제) ============================================
def ask_ollama(system_prompt: str,
               before_user_prompt: List[str],
               before_assis_prompt: List[str],
               user_prompt: str) -> Dict[str, Any]:
    """
    기존 호출 시그니처 유지.
    - /api/generate + grammar 로 '지정 키만 있는 JSON'을 강제.
    """
    # 추출 키만 허용하는 간단 PEG 문법
    GRAMMAR = r'''
    root    <- ws obj ws
    obj     <- '{' ws (pair (ws ',' ws pair)*)? ws '}'
    pair    <- (k1/k2/k3/k4/k5/k6/k7/k8/k9/k10/k11/k12/k13/k14/k15/k16/k17/k18/k19) ws ':' ws value
    value   <- string / date / url / 'null' / array / obj

    array   <- '[' ws (value (ws ',' ws value)*)? ws ']'

    k1  <- '"' '전시회 국문명' '"'
    k2  <- '"' '영문명(Full Name)' '"'
    k3  <- '"' '영문명(약자)' '"'
    k4  <- '"' '개최 시작' '"'
    k5  <- '"' '개최 종료' '"'
    k6  <- '"' '개최장소(국문)' '"'
    k7  <- '"' '개최장소(영어)' '"'
    k8  <- '"' '국가' '"'
    k9  <- '"' '도시' '"'
    k10 <- '"' '첫 개최년도' '"'
    k11 <- '"' '개최 주기' '"'
    k12 <- '"' '공식 홈페이지' '"'
    k13 <- '"' '주최기관' '"'
    k14 <- '"' '담당자' '"'
    k15 <- '"' '전화' '"'
    k16 <- '"' '이메일' '"'
    k17 <- '"' '산업분야' '"'
    k18 <- '"' '전시품목' '"'
    k19 <- '"' '출처' '"'

    string  <- '"' chars* '"'
    chars   <- [^"\\] / escape
    escape  <- '\\' ["\\/bfnrt] / '\\u' [0-9a-fA-F]{4}

    date    <- '"' [0-9]{4} '-' [0-9]{2} '-' [0-9]{2} '"'
    url     <- '"' 'h' 't' 't' 'p' 's'? '://' [^"\\]+ '"'
    ws      <- [ \t\n\r]*
    '''

    # 시스템 규칙(외부 MD) + 기존 few-shot 프롬프트를 하나의 prompt로 합침
    rules_md = load_prompt_md()
    # 리스트 방어적 처리
    bu0 = (before_user_prompt[0] if before_user_prompt else "")
    ba0 = (before_assis_prompt[0] if before_assis_prompt else "")
    bu1 = (before_user_prompt[1] if len(before_user_prompt) > 1 else "")
    ba1 = (before_assis_prompt[1] if len(before_assis_prompt) > 1 else "")

    prompt = (
        (rules_md.strip() + "\n\n" if rules_md else "") +
        system_prompt.strip() + "\n\n" +
        bu0.strip() + "\n" + ba0.strip() + "\n" +
        bu1.strip() + "\n" + ba1.strip() + "\n" +
        user_prompt.strip() + "\n\nJSON:"
    )

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "options": {
            "num_ctx": NUM_CTX,
            "temperature": TEMPERATURE,
            "grammar": GRAMMAR
        },
        "stream": False
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        content = (resp.json() or {}).get("response", "")
        obj = _safe_json_parse(content)
        return obj if isinstance(obj, dict) else {}
    except Exception as e:
        print(f"[ERROR] Ollama request failed: {e}")
        return {}

# ==== 메인 추출 함수 =========================================================
def extract_from_text(text: str, keys: List[str], source_url: str = "") -> Dict[str, Any]:
    import os, json
    from typing import Any, Dict, List

    # 0) prompt.md 로드 (없으면 빈 문자열로 진행) + 로딩 확인 로그
    base_dir = os.path.dirname(__file__)
    prompt_path = os.path.join(base_dir, "prompt.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_md = f.read()
        print("[PROMPT LOADED]", prompt_path)
        #print((prompt_md or "")[:200], "...")
    except FileNotFoundError:
        print(f"[PROMPT WARNING] prompt.md not found at {prompt_path}. Using empty prompt.")
        prompt_md = ""

    # 1) 시스템 프롬프트: md + 핵심 원칙 + 양방향 보완 규칙(추가)
    system_prompt = (
        (prompt_md + "\n\n") +
        "너는 전시회 정보 추출 도우미다. 사용자가 제공한 텍스트에서 지정된 키만 찾아 "
        "정확한 JSON으로만 출력해라. 다음 규칙을 반드시 지켜라.\n"
        "[핵심 원칙]\n"
        "1) 절대 환각/추측 금지: 텍스트에 없는 정보는 \"\"(빈 문자열) 또는 null로 둔다.\n"
        "2) 가능한 한 원문 스팬을 보존해 추출하되, 날짜는 YYYY-MM-DD로 정규화한다.\n"
        "3) 여러 후보가 있으면 최신 회차/명시가 더 완전한 것을 우선한다.\n"
        "4) 출력은 지정된 키만 포함한 유효한 JSON이어야 한다(추가/누락/주석 금지).\n"
        "\n[국문 ↔ 영문 명칭/장소 보완 규칙 (엄격 모드 유지)]\n"
        "- 기본은 '없으면 비움'이지만, 다음 보완은 허용한다.\n"
        "  · 영문명(Full Name)이 없고 국문 공식명이 있으면: 자연스러운 영어로 변환(브랜드/고유명사는 보존,\n"
        "    Expo→Expo, Exhibition→Exhibition, Show→Show, Fair→Fair, Conference→Conference, Congress→Congress 등).\n"
        "    불필요한 연도/도시/국가 꼬리(예: 2026, Las Vegas, USA)는 제거하고 브랜드 핵심만 유지.\n"
        "  · 국문명이 없고 영문 공식명만 있으면: 자연스러운 한국어로 변환(브랜드 보존, Expo→엑스포, Exhibition→전시회,\n"
        "    Show→쇼, Fair→박람회, Conference→컨퍼런스, Congress→총회 등).\n"
        "  · 개최장소(국문/영어) 보완: 한쪽만 있을 때 전시장 고유명칭은 보존하고 상대 언어로 상용 번역.\n"
        "    예: 'Las Vegas Convention Center (LVCC)' ↔ '라스베이거스 컨벤션 센터', 'KINTEX' ↔ '킨텍스'.\n"
        "  · 단, 영문명(약자)은 본문에 실제로 등장할 때만 채운다(엄격)."
    )

    # 2) few-shot (기존 유지 가능)
    before_user_prompt = [(
        "[예시 1]\n"
        "[입력 발췌]\n"
        "2025 미국 라스베가스 폐기물 재활용 전시회 [WE]\nWaste Expo\nWE\n2025.05.06 - 2025.05.08\n"
        "개최국가 | 미국 \n개최장소 | Las Vegas Convention Center \n산업분야 | 물류&운송, 기계&장비, 환경&폐기물 \n"
        "전시품목 | 시설, 중장비, 운송, 처리 기술 및 시스템 \n"
        "주최기관 | Informa Market \n전화 | 212-520-2700 \n이메일 | informamarkets@informa.com \n"
        "홈페이지 | [www.wasteexpo.com]\n"
    ), (
        "[예시 2]\n"
        "[입력 발췌]\n"
        "# 미국 폐기물 및 재활용 전시회 2026(Waste Expo 2026)...\n"
        "개최 일정 | 2027년 05월 03일(월) - 06일(목)\n"
        "개최 장소 | Las Vegas Convention Center (LVCC)\n"
        "개최 주기 | 1회 / 2년 | 첫 개최년도 | 1968년\n"
    )]

    before_assis_prompt = [(
        json.dumps({
            "전시회 국문명": "2025 미국 라스베가스 폐기물 재활용 전시회",
            "영문명(Full Name)": "Waste Expo",
            "영문명(약자)": "WE",
            "개최 시작": "2025-05-06",
            "개최 종료": "2025-05-08",
            "개최장소(국문)": "라스베이거스 컨벤션 센터",
            "개최장소(영어)": "Las Vegas Convention Center",
            "국가": "United States",
            "도시": "Las Vegas",
            "첫 개최년도": "",
            "개최 주기": "Annual",
            "공식 홈페이지": "https://www.wasteexpo.com",
            "주최기관": "Informa Markets",
            "담당자": "",
            "전화": "212-520-2700",
            "이메일": "informamarkets@informa.com",
            "산업분야": "Logistics, Machinery, Environment & Waste",
            "전시품목": "Facilities, Heavy Equipment, Transport, Processing Tech & Systems",
            "출처": "https://example.com"
        }, ensure_ascii=False)
    ), (
        json.dumps({
            "전시회 국문명": "미국 폐기물 및 재활용 전시회 2026",
            "영문명(Full Name)": "Waste Expo 2026",
            "영문명(약자)": "",
            "개최 시작": "2027-05-03",
            "개최 종료": "2027-05-06",
            "개최장소(국문)": "라스베이거스 컨벤션 센터",
            "개최장소(영어)": "Las Vegas Convention Center (LVCC)",
            "국가": "United States",
            "도시": "Las Vegas",
            "첫 개최년도": "1968",
            "개최 주기": "Biennial",
            "공식 홈페이지": "https://www.wasteexpo.com/en/home.html",
            "주최기관": "",
            "담당자": "",
            "전화": "",
            "이메일": "",
            "산업분야": "Waste collection & transport, Smart waste mgmt, Recycling plants & equipment, Biogas & WtE, Eco-friendly treatment, Policy & Education",
            "전시품목": "",
            "출처": ""
        }, ensure_ascii=False)
    )]

    # 3) 사용자 프롬프트(사이트/URL 힌트 포함)
    user_prompt = (
        "[출력 규칙]\n"
        f"- 키 목록(순서 유지): {keys}\n"
        "- JSON 외 텍스트 출력 금지\n"
        "\n[명칭/약자 강화 규칙 요약]\n"
        "1) 영문명(Full Name): H1/H2/히어로/브레드크럼/메타에서 "
        "   Expo|Exhibition|Show|Fair|Congress|Conference|Summit|Forum|Convention 포함 영문 구를 우선.\n"
        "   연도/도시/국가 꼬리(예: 2026, Las Vegas, USA)는 제거하고 브랜드명만 남긴다.\n"
        "2) 영문명(약자): '(Full Name) (ABC)' / 'ABC – Full Name' / 'ABC: Full Name' 또는 "
        "   대문자 2–8자 토큰이 본문에 2회 이상 반복될 때만. 본문에 없으면 비움.\n"
        "3) 전시회 국문명: 한국어 공식 명칭이 있으면 그대로. 없으면 영문명을 자연스러운 한국어로 변환(브랜드 보존,\n"
        "   Expo→엑스포, Exhibition→전시회, Show→쇼, Fair→박람회, Conference→컨퍼런스 등). 애매하면 비움.\n"
        "4) 주최기관/담당자/전화/이메일: 텍스트에 명시된 경우만. 추측 금지.\n"
        "\n[사이트/URL 힌트]\n"
        f"- 출처 URL: {source_url}\n"
        "  · auma.de: 경로/쿼리의 하이픈/언더스코어 토큰에서 전시회명 후보 추출 "
        "    (예: 'las-vegas_waste-expo_229507' → 'Waste Expo').\n"
        "  · myfair.co: '국문명 (영문명 연도)' 패턴에서 괄호 안 영문을 추출(연도는 제거)하여 Full Name 후보로 사용.\n"
        "\n텍스트 시작:\n"
        f"{text}\n"
        "텍스트 끝."
    )

    # 4) 모델 호출
    obj = ask_ollama(system_prompt, before_user_prompt, before_assis_prompt, user_prompt)

    # 5) 견고한 파싱: 문자열이면 JSON 파싱 시도, dict 아니면 빈 dict
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            obj = {}
    if not isinstance(obj, dict):
        obj = {}

    # 6) 누락 키 보정 + 후처리(정규화)
    fixed: Dict[str, Any] = {}
    for k in keys:
        v = obj.get(k, "")
        if v is None:
            v = ""
        if not isinstance(v, str):
            v = str(v)
        v = v.strip()

        if k in ("개최 시작", "개최 종료"):
            v = normalize_date(v)
        elif k == "첫 개최년도":
            v = normalize_year(v)
        elif k == "공식 홈페이지":
            v = normalize_url(v)

        fixed[k] = v

    return fixed


# ==== 파이프라인 진입점 ======================================================
def run_pipeline_markdown(raw: dict) -> Dict[str, Any] | None:
    """
    입력: {'markdown': '...'} 형태
    출력: {extracted_at, model, num_ctx, keys, data}
    """
    text = (raw.get("markdown") or "").strip()
    source_url = (raw.get("source_url") or "").strip() 
    if not text:
        print("처리할 텍스트가 없습니다.")
        return None

    print(f"[INFO] {MODEL} model 처리 (num_ctx={NUM_CTX}, temp={TEMPERATURE})")
    rec = extract_from_text(text, KEYS, source_url=source_url)

    result = {
        "extracted_at": datetime.utcnow().isoformat() + "Z",
        "model": MODEL,
        "num_ctx": NUM_CTX,
        "keys": KEYS,
        "data": rec,
    }
    return result
