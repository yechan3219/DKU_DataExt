# main.py
# -*- coding: utf-8 -*-
import asyncio
import time
import html
import os
import json
import datetime
import re
from typing import Dict, List, Tuple, Optional


import gradio as gr
import pyperclip
import subprocess
import sys
from pathlib import Path

from crawl4ai import AsyncWebCrawler
from crawl4ai.chunking_strategy import RegexChunking
from pydantic import BaseModel, Field

from llama import *            # run_pipeline_markdown, KEYS 등
from data import *             # normalize_text, to_markdown_table, canonicalize_record, save_json, compare_with_uploaded, compare_with_json

# --- [ADD in main.py] URL 정규화 유틸 ---
from urllib.parse import urlparse


_URL_RE = re.compile(r'https?://[^\s\)\]\>"]+', re.I)
_ALLOWED_SCHEMES = {"http", "https", "file", "raw"}

def _extract_http_url(s: str) -> str:
    s = (s or "").strip()
    m = _URL_RE.search(s)
    return m.group(0) if m else ""

def run_search_script(script, query):
    cmd = [sys.executable, script, "--query", query, "--headless", "--only-url"]
    try:
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        match = re.search(r"https?://[^\s]+", output)
        return match.group(0) if match else ""
    except Exception as e:
        print(f"Error running {script}: {e}")
        return ""

def process_three_from_keyword(keyword):
    scripts = [
        "search_test_gep.py",
        "search_test_myfair.py",
        "search_test_auma.py",
    ]
    urls = [run_search_script(s, keyword) for s in scripts]
    print(f"[DEBUG] Extracted URLs: {urls}")
    return process_three(*urls)


def _now_tag():
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _sanitize_name(name: str) -> str:
    import re
    name = (name or "file").strip()
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name or "file"

from urllib.parse import urlparse

# 집계/플랫폼 도메인(공식 사이트가 아닌 경우) 필터
_AGGREGATOR_DOMAINS = {
    "auma.de", "myfair.co", "10times.com", "eventbrite.com",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com"
}

def _norm_url_maybe(u: str) -> str:
    u = normalize_url(u or "")  # data.py의 정규화 사용
    if u and not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u

def _is_official_domain(u: str) -> bool:
    try:
        host = urlparse(u).netloc.lower().split(":")[0]
    except Exception:
        host = ""
    return bool(host) and host not in _AGGREGATOR_DOMAINS

def _pick_official_url(*recs: Dict[str, str]) -> str:
    """각 결과의 '공식 홈페이지' 필드에서 후보를 모아 공식 도메인으로 보이는 첫 URL 반환."""
    cands = []
    for rec in recs:
        u = _norm_url_maybe((rec or {}).get("공식 홈페이지", ""))
        if u:
            cands.append(u)
    # 중복 제거(순서 유지)
    seen = set()
    uniq = [u for u in cands if not (u in seen or seen.add(u))]
    for u in uniq:
        if _is_official_domain(u):
            return u
    return ""

# 프로젝트 루트 기준 search_test.py 경로를 잡아주세요.
# (아래는 main.py와 같은 폴더에 있는 경우 예시)
SEARCH_SCRIPT = str(Path(__file__).parent / "search_test.py")

def find_url_by_name(exhibition_name: str, timeout_sec: int = 60) -> str:
    if not exhibition_name or not exhibition_name.strip():
        return ""
    base_cmd = [sys.executable, SEARCH_SCRIPT, "--query", exhibition_name.strip(),
                "--only-url", "--headless"]  # ★ 항상 headless로
    for attempt in (1, 2):  # ★ 한번 재시도
        try:
            out = subprocess.check_output(base_cmd, stderr=subprocess.STDOUT,
                                          timeout=timeout_sec, text=True)
            urls = _URL_RE.findall(out)
            if urls:
                return urls[-1]
        except Exception as e:
            print(f"[find_url_by_name] try{attempt} error:", e)
            # 재시도 루프가 한 번 더 돎
    return ""

def save_record_json_local(record: dict, prefix: str) -> str | None:
    """
    멀티 비교 탭 저장용. 반드시 '파일 경로'만 반환.
    실패/비정상 시 None 반환 → Gradio File 컴포넌트는 비워짐.
    """
    try:
        if not isinstance(record, dict):
            record = {}
        fname = _sanitize_name(f"{prefix}_{_now_tag()}.json")
        path = os.path.abspath(os.path.join(SAVED_DIR, fname))

        # 실제 파일로 저장
        with open(path, "w", encoding="utf-8") as f:
            import json
            json.dump(record, f, ensure_ascii=False, indent=2)

        # 파일이 맞는지 최종 확인
        return path if os.path.isfile(path) else None

    except Exception as e:
        print(f"[save_record_json_local] error: {e}")
        return None

# === 전역 CSS: 표 행 높이/열 너비/배경 톤 통일 ===
CUSTOM_CSS = """
:root{
  --ex-label-w: 170px;     /* 라벨(첫 열) 고정 너비 */
  --ex-row-h: 42px;        /* 모든 표 공통 행 높이 */
  --ex-border: 1px solid color-mix(in oklab, var(--body-text-color) 18%, transparent);
}

/* 우리 결과 테이블 공통 스타일 */
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
  opacity: .92;           /* 라벨이 너무 옅지 않게 */
}

/* 값 셀은 한 줄로 보여주고 길면 ... 처리 (전체 값은 title로 툴팁) */
.ex-table td .val {
  display: block;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* 아주 연한 줄무늬 배경으로 가독성 ↑ */
.ex-table tr:nth-child(even) td {
  background: color-mix(in oklab, var(--background-fill-primary) 92%, var(--body-text-color) 8%) !important;
}

/* Gradio DataFrame(편집표)도 같은 규칙 적용 */
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
  max-width: 0;           /* col 너비를 table-layout:fixed에 따르게 */
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
"""

# --------------------------------------------------------------------------------------
# 설정/상수
# --------------------------------------------------------------------------------------
APP_TITLE = "데이터 추출 하기"

# KEYS: llama.py 내 KEYS를 그대로 쓰되, 실패 시 fallback
try:
    EXTRACT_KEYS = KEYS  # from llama import *
except Exception:
    EXTRACT_KEYS = [
        "전시회 국문명","영문명(Full Name)","영문명(약자)",
        "개최 시작","개최 종료",
        "개최장소(국문)","개최장소(영어)","국가","도시",
        "첫 개최년도","개최 주기","공식 홈페이지",
        "주최기관","담당자","전화","이메일",
        "산업분야","전시품목","출처"
    ]

DATASET_COLORS = {1: "#D7263D", 2: "#1B9AAA", 3: "#2E7D32", 4: "#6A1B9A"}  # 1=빨강, 2=파랑, 3=초록

# --------------------------------------------------------------------------------------
# (선택) pydantic 모델 (안 쓰이면 그대로 둬도 무방)
# --------------------------------------------------------------------------------------
class PageSummary(BaseModel):
    title: str = Field(..., description="페이지 제목.")
    summary: str = Field(..., description="자세한 페이지 요약.")
    brief_summary: str = Field(..., description="간단한 페이지 요약.")
    keywords: list = Field(..., description="페이지에 할당된 키워드.")

# --------------------------------------------------------------------------------------
# 크롤 + 파이프라인 (기존 summarize_url 유지)
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
        print(f"[INFO] 전체 문장 길이: {bytes_norm} bytes")

        if not record:
            print("[INFO] 처리할 텍스트가 없습니다.")
            return

        result = run_pipeline_markdown(record)

        total_time = time.time() - start_time
        print(f"[INFO] 전체 걸린 시간: {total_time:.2f} s")
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
        print("[INFO] 처리 완료")
        return output, rec
    else:
        return "페이지를 크롤링하고 요약하는 데 실패했습니다."

# --- [PATCH in main.py] run_summarize_from_text() 교체 ---
def run_summarize_from_text(url: str):
    """텍스트박스 입력 → summarize_url → (textbox, markdown, state) 3개 반환"""

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(summarize_url(url))
    finally:
        loop.close()
    if isinstance(res, tuple):
        result, rec = res
    else:
        result, rec = res, None
    return url, result, rec


def run_summarize_url():
    try:
        url = pyperclip.paste()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        res = loop.run_until_complete(summarize_url(url))
        if isinstance(res, tuple):
            result, rec = res
        else:
            result, rec = res, None
        return url, result, rec
    except Exception as e:
        return "", f"오류가 발생했습니다: {str(e)}", None

# --------------------------------------------------------------------------------------
# 멀티 URL 비교/병합 도우미 (UI에서 사용)
# --------------------------------------------------------------------------------------
def _render_table_html(rec: Dict[str, str], idx: int, diff: set) -> str:
    if not rec:
        return "<div style='color:#999'>데이터가 없습니다.</div>"
    color = DATASET_COLORS.get(idx, "#333")
    rows = []
    for k in EXTRACT_KEYS:  # 고정 순서
        raw_v = "" if rec.get(k) is None else str(rec.get(k))
        v_esc = html.escape(raw_v)
        k_esc = html.escape(k)
        if k in diff and v_esc:
            v_html = f"<span class='val' title='{v_esc}' style='color:{color};font-weight:600'>{v_esc}</span>"
        else:
            v_html = f"<span class='val' title='{v_esc}'>{v_esc}</span>"
        rows.append(
            "<tr>"
            f"<th>{k_esc}</th>"
            f"<td>{v_html}</td>"
            "</tr>"
        )
    table = (
        "<div class='ex-card'>"
        "<table class='ex-table'>"
        "<colgroup><col class='label'><col></colgroup>"
        "<tbody>"
        + "".join(rows) +
        "</tbody></table></div>"
    )
    return table

def _diff_keys4(r1: Dict, r2: Dict, r3: Dict, r4: Dict) -> set:
    keys = set(r1.keys()) | set(r2.keys()) | set(r3.keys()) | set(r4.keys())
    diff = set()
    for k in keys:
        vset = {str(r.get(k, "")) for r in (r1, r2, r3, r4)}
        if len(vset) > 1:
            diff.add(k)
    return diff

# --- [PATCH in main.py] _extract_one_sync() 안에서도 보정 ---
def _extract_one_sync(url: str) -> Dict[str, str]:
    url = _ensure_url(url)  # <<< 추가
    if not url:
        return {}
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(summarize_url(url))
    finally:
        loop.close()
    if isinstance(res, tuple) and len(res) >= 2:
        _, rec = res
        return rec or {}
    return {}


def _agg_state_to_df(agg: Dict[str, str]) -> List[List[str]]:
    """딕셔너리 → DataFrame 2열 행 리스트"""
    return [[k, "" if agg.get(k) is None else str(agg.get(k))] for k in EXTRACT_KEYS]

def _df_to_agg_state(df_rows) -> Dict[str, str]:
    """
    Gradio DataFrame 이벤트는 pandas.DataFrame을 넘겨줄 수 있음.
    - DataFrame이면 to_numpy().tolist()로 변환
    - 리스트면 그대로 사용
    """
    if df_rows is None:
        rows = []
    elif hasattr(df_rows, "to_numpy"):
        try:
            rows = df_rows.to_numpy().tolist()
        except Exception:
            rows = getattr(df_rows, "values", df_rows).tolist()
    else:
        rows = df_rows  # already list[list]

    out: Dict[str, str] = {}
    for row in rows:
        if row is None or len(row) < 2:
            continue
        k = "" if row[0] is None else str(row[0])
        v = "" if row[1] is None else str(row[1])
        out[k] = v
    return out

def _agg_json(agg: Dict[str, str]) -> str:
    try:
        return json.dumps({k: agg.get(k, "") for k in EXTRACT_KEYS}, ensure_ascii=False, indent=2)
    except Exception:
        return "{}"

def process_three(url1: str, url2: str, url3: str):
    """버튼 클릭 → 3개 URL 추출 → 좌측 3표 + 콤보박스 세팅 + 4번째 편집표 초기화"""
    rec1 = _extract_one_sync(url1) or {}
    rec2 = _extract_one_sync(url2) or {}
    rec3 = _extract_one_sync(url3) or {}

    official_url = _pick_official_url(rec1, rec2, rec3)
    rec4 = _extract_one_sync(official_url) if official_url else {}

    diff = _diff_keys4(rec1, rec2, rec3, rec4)
    html1 = _render_table_html(rec1, 1, diff)
    html2 = _render_table_html(rec2, 2, diff)
    html3 = _render_table_html(rec3, 3, diff)
    html4 = _render_table_html(rec4, 4, diff) if rec4 else "<div style='color:#999'>공식 홈페이지를 찾지 못했습니다.</div>"

    # 콤보박스 choices/value, 편집표 초기값(기본은 1번 값)
    dd_updates = []
    agg = {}
    for k in EXTRACT_KEYS:
        c1 = rec1.get(k, "")
        c2 = rec2.get(k, "")
        c3 = rec3.get(k, "")
        c4 = rec4.get(k, "")
        choices = ["(비우기)", f"1) {c1}", f"2) {c2}", f"3) {c3}", f"4) {c4}"]
        dd_updates.append(gr.update(choices=choices, value=f"1) {c1}"))  # 필요시 value=f"4) {c4}"로 변경 가능
        agg[k] = c1

    df_init = _agg_state_to_df(agg)
    json_init = _agg_json(agg)

    # 상태로 rec1, rec2, rec3, agg 보관
    return [html1, html2, html3, html4] + dd_updates + [df_init, json_init, rec1, rec2, rec3, rec4, agg]

def on_choice(choice_label: str, key: str, rec1: Dict, rec2: Dict, rec3: Dict, rec4: Dict, agg: Dict[str, str]):
    """각 항목 콤보박스 변경 → agg 상태 반영 → 편집표/JSON 갱신"""
    val = ""
    if isinstance(choice_label, str):
        if choice_label.startswith("1)"):
            val = rec1.get(key, "")
        elif choice_label.startswith("2)"):
            val = rec2.get(key, "")
        elif choice_label.startswith("3)"):
            val = rec3.get(key, "")
        elif choice_label.startswith("4)"):
            val = rec4.get(key, "")
    # (비우기)이면 빈 값 유지
    new_agg = dict(agg)
    new_agg[key] = val
    return _agg_state_to_df(new_agg), _agg_json(new_agg), new_agg

def on_table_changed(df_rows: List[List[str]], agg: Dict[str, str]):
    """사용자가 표를 직접 수정했을 때 → agg 동기화 + JSON 갱신"""
    new_agg = _df_to_agg_state(df_rows)
    return _agg_json(new_agg), new_agg

# --------------------------------------------------------------------------------------
# Gradio UI (단일 탭: 키워드 → 3사이트 자동 추출)
# --------------------------------------------------------------------------------------

with gr.Blocks(css=CUSTOM_CSS) as demo:
    gr.Markdown(f"# {APP_TITLE}")

    with gr.Tabs():
        with gr.Tab("멀티 비교 (키워드 → 3사이트 자동 추출)"):
            gr.Markdown(
                "검색어(전시회명) **한 개**만 입력하면 GEP / Myfair / AUMA 3곳에서 자동으로 URL을 찾고, "
                "각 페이지에서 데이터를 추출해 좌측 3패널과 공식사이트(자동 감지) 패널에 보여줍니다. "
                "오른쪽에서 항목별 콤보 선택·표 편집·JSON 저장을 할 수 있습니다."
            )

            # 1) 입력 & 실행 버튼
            with gr.Row():
                keyword = gr.Textbox(
                    label="검색어",
                    placeholder="예: SILMO Paris / 바르셀로나 정보통신회 / Automotive World Tokyo"
                )
                run_button = gr.Button("검색 및 3개 사이트 자동 추출", variant="primary")

            # 2) 좌측 4패널: GEP / Myfair / AUMA / 공식사이트
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### GEP")
                    out1 = gr.HTML()
                    save1_btn = gr.Button("GEP 저장")
                    file1 = gr.File(label="GEP 파일", interactive=False, file_count="single", file_types=[".json"])

                with gr.Column(scale=1):
                    gr.Markdown("### Myfair")
                    out2 = gr.HTML()
                    save2_btn = gr.Button("Myfair 저장")
                    file2 = gr.File(label="Myfair 파일", interactive=False, file_count="single", file_types=[".json"])

                with gr.Column(scale=1):
                    gr.Markdown("### AUMA")
                    out3 = gr.HTML()
                    save3_btn = gr.Button("AUMA 저장")
                    file3 = gr.File(label="AUMA 파일", interactive=False, file_count="single", file_types=[".json"])

                with gr.Column(scale=1):
                    gr.Markdown("### 공식사이트 (자동 감지)")
                    out5 = gr.HTML()
                    save5_btn = gr.Button("공식사이트 저장")
                    file5 = gr.File(label="공식사이트 파일", interactive=False, file_count="single", file_types=[".json"])

            # 3) 우측: 항목별 선택/편집/저장
            with gr.Column(scale=1):
                gr.Markdown("### 4) 선택·편집 결과")

                combo_boxes: List[gr.Dropdown] = []
                with gr.Accordion("항목별 선택 (화살표)", open=False):
                    for k in EXTRACT_KEYS:
                        combo_boxes.append(
                            gr.Dropdown(label=k, choices=[], value=None, interactive=True)
                        )

                agg_table = gr.DataFrame(
                    headers=["항목", "값"],
                    datatype=["str", "str"],
                    row_count=(len(EXTRACT_KEYS), "fixed"),
                    col_count=(2, "fixed"),
                    interactive=True,
                    label="편집 가능한 결과 표"
                )
                agg_json = gr.Code(language="json", label="미리보기 JSON")

                save4_btn = gr.Button("선택·편집 JSON 저장 (4)")
                file4 = gr.File(label="JSON #4 파일 (편집본)", interactive=False, file_count="single", file_types=[".json"])

            # 4) 내부 상태(각 결과 + 현재 편집본)
            s1 = gr.State()   # rec1 (GEP)
            s2 = gr.State()   # rec2 (Myfair)
            s3 = gr.State()   # rec3 (AUMA)
            s4 = gr.State()   # rec4 (공식사이트)
            agg_state = gr.State({})  # 현재 편집본

            # 5) 실행 버튼 → 자동 검색+추출
            outputs = [out1, out2, out3, out5]  # 4 HTML
            outputs += combo_boxes              # 콤보박스 업데이트(choices/value)
            outputs += [agg_table, agg_json, s1, s2, s3, s4, agg_state]

            run_button.click(
                fn=process_three_from_keyword,
                inputs=[keyword],
                outputs=outputs
            )

            # 6) 콤보 변경 → 편집본 반영
            for i, k in enumerate(EXTRACT_KEYS):
                combo_boxes[i].change(
                    fn=lambda choice, _r1, _r2, _r3, _r4, _agg, _k=k: on_choice(choice, _k, _r1, _r2, _r3, _r4, _agg),
                    inputs=[combo_boxes[i], s1, s2, s3, s4, agg_state],
                    outputs=[agg_table, agg_json, agg_state],
                )

            # 7) 표 직접 수정 → JSON/상태 동기화
            agg_table.change(
                fn=on_table_changed,
                inputs=[agg_table, agg_state],
                outputs=[agg_json, agg_state],
            )

            # 8) 저장 버튼들
            save1_btn.click(lambda rec: save_record_json_local(rec, "gep"),       inputs=[s1],        outputs=[file1])
            save2_btn.click(lambda rec: save_record_json_local(rec, "myfair"),    inputs=[s2],        outputs=[file2])
            save3_btn.click(lambda rec: save_record_json_local(rec, "auma"),      inputs=[s3],        outputs=[file3])
            save5_btn.click(lambda rec: save_record_json_local(rec, "official"),  inputs=[s4],        outputs=[file5])
            save4_btn.click(lambda rec: save_record_json_local(rec, "agg"),       inputs=[agg_state], outputs=[file4])

# --------------------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7865)