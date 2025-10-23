import json
import os, json, re, requests
import time
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

# 저장할 형식
KEYS = [
        "전시회 국문명","영문명(Full Name)","영문명(약자)",
        "개최 시작","개최 종료",
        "개최장소(국문)","개최장소(영어)","국가","도시",
        "첫 개최년도","개최 주기","공식 홈페이지",
        "주최기관","담당자","전화","이메일",
        "산업분야","전시품목","출처"
    ]

# 흔한 오타/변형 키 교정 맵
KEY_ALIASES = {
    "영문명(Full Name": "영문명(Full Name)", 
    "영문명(FullName)": "영문명(Full Name)",
    "영문명(Full name)": "영문명(Full Name)",
    "공식홈페이지": "공식 홈페이지",
    "개최장소(영문)": "개최장소(영어)",
    "개최 장소(영어)": "개최장소(영어)",
}

KR_KEY = "전시회 국문명"
EN_KEY = "영문명(Full Name)"

DEFAULT_KEYS_ORDER = [
    "No.", "산업", "전시회 국문명", "영문명(Full Name)", "영문명(약자)",
    "개최 시작", "개최 종료",
    "개최장소(국문)", "개최장소(영어)", "국가", "도시",
    "첫 개최년도", "개최 주기", "공식 홈페이지",
    "주최기관", "담당자", "전화", "이메일",
    "산업분야", "전시품목", "출처"
]

def canonicalize_record(rec: Dict[str, Any]) -> Dict[str, str]:
    fixed = {}
    for k, v in rec.items():
        kk = KEY_ALIASES.get(k, k)
        fixed[kk] = v

    merged = {}
    for k in KEYS:
        candidates = []
        if k in fixed:
            candidates.append(fixed.get(k, ""))
        for fk in list(fixed.keys()):
            if fk != k and fk.startswith(k.rstrip(")")):
                candidates.append(fixed.get(fk, ""))
        val = next((str(c).strip() for c in candidates if str(c).strip()), "")
        merged[k] = val

    return merged

# 추출결과 표로 정리
def to_markdown_table(rec: Dict[str, str]) -> str:
    lines = ["| 항목 | 값 |", "|---|---|"]
    for k in KEYS:
        v = rec.get(k, "")
        # URL 링크
        if k in ("공식 홈페이지", "출처") and v and not v.startswith("["):
            v = f"[{v}]({v})"
        lines.append(f"| {k} | {v or ''} |")
    return "\n".join(lines)

def to_json(rec: Dict[str, str]) -> str:
    return "```json\n" + json.dumps(rec, ensure_ascii=False, indent=2) + "\n```"

# json 파일로 저장
def save_json(result_obj: Dict[str, Any], rec_canon: Dict[str, str], url: str) -> str | None:
    os.makedirs("outputs", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.abspath(os.path.join("outputs", f"extract_{ts}.json"))
    payload = {
        "source_url": url,
        "extracted_at": result_obj.get("extracted_at", ""),
        "model": result_obj.get("model", ""),
        "num_ctx": result_obj.get("num_ctx", ""),
        "keys": result_obj.get("keys", []),
        "data": rec_canon,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path if os.path.isfile(path) else None
    except Exception as e:
        print(f"[save_json] error: {e}")
        return None

# Crawl 결과 전처리
def normalize_text(s: str) -> str:
    if not s:
        return ""
    # 공백 정리(여러 공백 → 하나, 앞뒤 공백 제거)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)  # 빈 줄 2개 이하로
    return s.strip()

# 데이터 비교
def compare_with_uploaded(url_json, file_obj):
    if not url_json:
        return "먼저 URL에서 JSON을 추출하세요."
    if not file_obj:
        return "비교할 JSON 파일을 업로드하세요."

    # 업로드한 JSON 데이터 로드
    try:
        with open(file_obj, "r", encoding="utf-8") as f:
            uploaded_data = json.load(f)
        # 만약 업로드한 JSON이 전체 payload 구조라면 "data" 키 추출
        uploaded_data = uploaded_data.get("data", uploaded_data)
    except Exception as e:
        return f"업로드한 JSON 읽기 실패: {e}"

    keys = set(url_json.keys()) | set(uploaded_data.keys())
    rows = []
    for k in keys:
        v1 = url_json.get(k, "")
        v2 = uploaded_data.get(k, "")
        if str(v1) != str(v2):
            rows.append(f"**{k}**:\n - URL JSON: {v1}\n - 업로드 JSON: {v2}\n")

    if not rows:
        return "두 JSON 파일은 동일합니다."

    md = "| 항목 | JSON 1 | JSON 2 |\n|---|---|---|\n"
    for k, v1, v2 in rows:
        md += f"| {k} | {v1} | {v2} |\n"

# json 두개 비교
def compare_with_json(file1_obj, file2_obj):
    if not file1_obj or not file2_obj:
        return "두 개의 JSON 파일을 모두 업로드하세요."

    # 첫 번째 JSON 로드
    try:
        with open(file1_obj, "r", encoding="utf-8") as f:
            json1 = json.load(f)
        json1 = json1.get("data", json1)
    except Exception as e:
        return f"첫 번째 JSON 읽기 실패: {e}"


    # 두 번째 JSON 로드
    try:
        with open(file2_obj, "r", encoding="utf-8") as f:
            json2 = json.load(f)
        json2 = json2.get("data", json2)
    except Exception as e:
        return f"두 번째 JSON 읽기 실패: {e}"

    # 키 비교
    rows = []
    for k in KEYS:
        v1 = json1.get(k, "")
        v2 = json2.get(k, "")
        if str(v1) != str(v2):
            v2 = f'<span style="color:red">{v2}</span>'
        rows.append((k, str(v1), str(v2)))

    if not rows:
        return "두 JSON 파일은 동일합니다."

    # Markdown 표 생성
    md = "| 항목 | JSON 1 | JSON 2 |\n|---|---|---|\n"
    for k, v1, v2 in rows:
        md += f"| {k} | {v1} | {v2} |\n"

    return md

class FuzzyExhibitionMatcher:
    def __init__(
        self,
        threshold: float = 0.8,      # 매칭 임계치 (0~1)
        weight_kr: float = 0.6,      # 국문명 가중치
        weight_en: float = 0.4,      # 영문명 가중치
        keys_order: Optional[List[str]] = None
    ):
        self.threshold = threshold
        self.weight_kr = weight_kr
        self.weight_en = weight_en
        self.keys_order = keys_order or DEFAULT_KEYS_ORDER

        # 유사도 함수 준비(rapidfuzz -> difflib 백업)
        try:
            from rapidfuzz import fuzz
            self._use_rapidfuzz = True
            self._fuzz = fuzz
        except Exception:
            self._use_rapidfuzz = False
            self._fuzz = None

        # 정규화용 정규식
        self._punct_re = re.compile(r"[\s\-\_\/\|\(\)\[\]\{\}\.\,\!\?\:;’'\"“”`·]+")

    # ---------- 공개 API ----------
    def compare_files(self, base_json_path: str, target_json_path: str) -> str:
        """
        파일 경로 2개를 받아 매칭 요약 + 상세 차이표(Markdown) 반환.
        (파일은 {"data":[...]} 또는 리스트 형태 모두 허용)
        """
        base = self._load_any(base_json_path)
        targ = self._load_any(target_json_path)
        return self.compare_lists(base, targ)

    def compare_lists(self, base_list: List[Dict[str, Any]], target_list: List[Dict[str, Any]]) -> str:
        """
        리스트 2개를 받아 매칭 요약 + 상세 차이표(Markdown) 반환.
        """
        pairs = self._build_best_matches(base_list, target_list)

        if not pairs:
            return f"퍼지 임계치 {self.threshold} 기준으로 매칭된 항목이 없습니다."

        out = []
        out.append(f"### 매칭 결과 요약 (임계치={self.threshold}, KR:{self.weight_kr}, EN:{self.weight_en})")
        out.append("| DB | 사이트 데이터 | 매칭점수 |\n|---|---|---|")
        for a, b, s in pairs:
            out.append(f"| {a.get(KR_KEY,'')} / {a.get(EN_KEY,'')} | "
                       f"{b.get(KR_KEY,'')} / {b.get(EN_KEY,'')} | {s:.2f} |")

        # 상세 차이 표
        for idx, (a, b, s) in enumerate(pairs, start=1):
            out.append(f"\n---\n#### #{idx}. `{a.get(KR_KEY,'')}` ↔ `{b.get(KR_KEY,'')}` (score: {s:.2f})")
            out.append(self._diff_table(a, b))

        return "\n".join(out)

    # ---------- 내부 로직 ----------
    def _read_json_any(self, path: str):
        """파일이 JSON/JSONL 중 무엇이든 안전하게 읽어서 Python 객체로 반환"""
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read().strip()
        # JSONL 가능성: 줄마다 개별 JSON
        if "\n" in txt and txt.lstrip().startswith("{") is False and txt.lstrip().startswith("[") is False:
            objs = []
            for i, line in enumerate(txt.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    objs.append(json.loads(line))
                except Exception as e:
                    # 한 줄 JSON 파싱 실패 시 무시(또는 raise로 바꿔도 됨)
                    pass
            return objs
        # 일반 JSON
        return json.loads(txt)

    def _coerce_records(self, obj) -> List[Dict[str, Any]]:
        """
        다양한 입력 형태를 List[dict]로 강제 변환:
        - {"data": [...]}
        - {...} (단일 dict)
        - [...] (dict/str 혼재 가능 → str이면 json.loads 재시도)
        - 그 외는 스킵
        """
        if isinstance(obj, dict):
            # {"data": ...} or 단일 레코드
            data = obj.get("data", obj)
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = [data]
            else:
                return []
        elif isinstance(obj, list):
            items = obj
        else:
            return []

        records: List[Dict[str, Any]] = []
        for i, it in enumerate(items):
            if isinstance(it, dict):
                records.append(it)
            elif isinstance(it, str):
                # 요소가 문자열 JSON인 경우 파싱 시도
                try:
                    parsed = json.loads(it)
                    if isinstance(parsed, dict):
                        records.append(parsed)
                except Exception:
                    # 파싱 불가 문자열은 스킵
                    continue
            # 다른 타입은 스킵
        return records

    def _load_any(self, path: str) -> List[Dict[str, Any]]:
        obj = self._read_json_any(path)
        recs = self._coerce_records(obj)
        # 국문/영문명이 모두 비어있는 레코드는 매칭 불가 → 스킵
        cleaned = []
        for r in recs:
            if str(r.get(KR_KEY, "")).strip() or str(r.get(EN_KEY, "")).strip():
                cleaned.append(r)
        if not cleaned:
            raise ValueError(f"레코드가 비어있거나, '{KR_KEY}'/'{EN_KEY}'가 없는 데이터입니다: {os.path.basename(path)}")
        return cleaned


    def _normalize(self, s: Optional[str]) -> str:
        if not s:
            return ""
        s = s.strip().lower()
        s = self._punct_re.sub(" ", s)
        s = re.sub(r"\s+", " ", s)
        return s

    def _sim_ratio(self, a: str, b: str) -> float:
        """
        부분 일치 유사도 (0~1). rapidfuzz.partial_ratio 우선, 없으면 difflib로 대체.
        """
        if self._use_rapidfuzz:
            return float(self._fuzz.partial_ratio(a, b)) / 100.0
        else:
            from difflib import SequenceMatcher
            a, b = self._normalize(a), self._normalize(b)
            return SequenceMatcher(None, a, b).ratio()

    def _composite_score(self, a: Dict[str, Any], b: Dict[str, Any]) -> float:
        """
        국문/영문 각각 부분 일치 점수 → 사용 가능한 가중치만 정규화해 가중 평균.
        """
        kr_a = self._normalize(a.get(KR_KEY, ""))
        kr_b = self._normalize(b.get(KR_KEY, ""))
        en_a = self._normalize(a.get(EN_KEY, ""))
        en_b = self._normalize(b.get(EN_KEY, ""))

        score_kr = self._sim_ratio(kr_a, kr_b) if (kr_a and kr_b) else 0.0
        score_en = self._sim_ratio(en_a, en_b) if (en_a and en_b) else 0.0

        if score_kr == 0.0 and score_en == 0.0:
            return 0.0

        used_w_kr = self.weight_kr if score_kr > 0 else 0.0
        used_w_en = self.weight_en if score_en > 0 else 0.0
        denom = (used_w_kr + used_w_en) or 1.0

        return (score_kr * used_w_kr + score_en * used_w_en) / denom

    def _build_best_matches(
        self,
        base: List[Dict[str, Any]],
        target: List[Dict[str, Any]]
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any], float]]:
        """
        base 각 항목에 대해 target에서 최고 유사도 항목 선별, 임계치 이상만 반환.
        """
        matches = []
        for a in base:
            best_item = None
            best_score = -1.0
            for b in target:
                s = self._composite_score(a, b)
                if s > best_score:
                    best_item, best_score = b, s
            if best_item is not None and best_score >= self.threshold:
                matches.append((a, best_item, best_score))
        return matches

    def _diff_table(self, left: Dict[str, Any], right: Dict[str, Any]) -> str:
        """
        키 순서(self.keys_order)에 따라 값 비교 표 생성.
        값이 다르면 빨간색으로 강조.
        """
        md = "| 항목 | DB | 비교 데이터 |\n|---|---|---|\n"
        for k in self.keys_order:
            v1 = str(left.get(k, "") if left is not None else "")
            v2 = str(right.get(k, "") if right is not None else "")
            if v1 != v2:
                v2_html = f'<span style="color:red">{v2}</span>'
            else:
                v2_html = v2
            md += f"| {k} | {v1} | {v2_html} |\n"
        return md
