import subprocess
import concurrent.futures
import re
import sys
import os
from pathlib import Path

# ── 설정 ─────────────────────────────────────────────────────────────────────
# main.py와 같은 폴더에 3개 스크립트가 있다고 가정
THIS_DIR = Path(__file__).parent.resolve()

SCRIPTS = [
    (THIS_DIR / "search_test_gep.py").resolve(),
    (THIS_DIR / "search_test_myfair.py").resolve(),
    (THIS_DIR / "search_test_auma.py").resolve(),
]

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
TIMEOUT_SEC = 120

# ── 유틸 ─────────────────────────────────────────────────────────────────────
def pick_last_url(text: str) -> str:
    """stdout에서 마지막 http(s) URL만 추출"""
    matches = list(URL_RE.finditer(text or ""))
    return matches[-1].group(0) if matches else ""

# ── 실행기 ───────────────────────────────────────────────────────────────────
def run_search(script_path: Path, keyword: str) -> str:
    """각 스크립트를 subprocess로 실행하고, 최종 URL만 반환(없으면 빈 문자열)"""
    script_str = str(script_path)
    if not script_path.is_file():
        print(f"[search] not found: {script_str}")
        return ""

    cmd = [sys.executable, script_str, "--query", keyword, "--only-url", "--headless"]

    try:
        proc = subprocess.run(
            cmd,
            cwd=THIS_DIR,                    # 중요: 스크립트들과 같은 폴더에서 실행
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,        # stderr도 합쳐서 파싱
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=TIMEOUT_SEC,
            env={**os.environ},              # 필요시 환경변수 주입 가능
        )
        out = (proc.stdout or "").strip()
        url = pick_last_url(out)
        print(f"[{script_path.name}] rc={proc.returncode} url={url or '(none)'}")
        # 디버깅 필요하면 아래 주석 해제
        # print(f"---- STDOUT ----\n{out}\n-----------------")
        return url
    except subprocess.TimeoutExpired:
        print(f"[{script_path.name}] timeout after {TIMEOUT_SEC}s")
        return ""
    except Exception as e:
        print(f"[{script_path.name}] error: {e}")
        return ""

def parallel_search(keyword: str):
    """3개 검색을 병렬로 실행하고 URL 리스트 반환 [GEP, Myfair, AUMA]"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(run_search, s, keyword) for s in SCRIPTS]
        urls = [f.result() for f in futures]

    print("\n=== 모든 검색 완료 ===")
    for script, url in zip(SCRIPTS, urls):
        print(f"{script.name:<25} → {url or '(없음)'}")
    return urls

# ── 엔트리 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    keyword = input("검색어 입력: ").strip()
    parallel_search(keyword)
