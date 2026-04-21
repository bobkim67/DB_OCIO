"""
네이버 블로그 크롤러 — monygeek
모바일 버전 스크롤 기반 전체 글 URL 수집 → 개별 글 텍스트 추출 → JSON 저장
"""

import json
import os
import sys
import time
import re
from datetime import datetime
from pathlib import Path

# Windows cp949 콘솔/리다이렉트에서 한글 깨짐 방지
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

os.environ["WDM_SSL_VERIFY"] = "0"

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*InsecureRequestWarning.*")

# ── 설정 ──────────────────────────────────────────────
BLOG_ID = "monygeek"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "monygeek"
OUTPUT_FILE = DATA_DIR / "posts.json"

# 스크롤 기반 수집 — 최대 스크롤 횟수 (608건 / ~30건 per scroll ≈ 25회)
MAX_SCROLL = 50
SCROLL_PAUSE = 2.0


LOG_NOS_FILE = DATA_DIR / "log_nos.json"  # 목록 캐시


def create_driver():
    """Chrome headless 드라이버 생성"""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--log-level=3")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Mobile Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(30)
    return driver


def load_existing_posts():
    """기존 수집 데이터 로드 (중복 방지)"""
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            posts = json.load(f)
        return {p["log_no"]: p for p in posts}
    return {}


def save_posts(posts_dict):
    """JSON 저장 (날짜 내림차순 정렬)"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    posts = sorted(posts_dict.values(), key=lambda x: x.get("date", ""), reverse=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    print(f"[저장] {len(posts)}건 → {OUTPUT_FILE}")


def extract_log_nos(driver):
    """현재 페이지에서 모든 logNo 추출"""
    log_nos = set()
    links = driver.find_elements(By.CSS_SELECTOR, f'a[href*="{BLOG_ID}"]')
    for a in links:
        href = a.get_attribute("href") or ""
        m = re.search(rf"/{BLOG_ID}/(\d{{10,}})", href)
        if m:
            log_nos.add(m.group(1))
        m2 = re.search(r"logNo=(\d+)", href)
        if m2:
            log_nos.add(m2.group(1))
    return log_nos


def collect_all_log_nos(driver):
    """모바일 블로그에서 스크롤하며 전체 글 logNo 수집 — 중간 저장 포함"""
    # 기존 캐시 로드
    all_nos = _load_log_nos()
    if all_nos:
        print(f"  기존 캐시 {len(all_nos)}건 로드")

    driver.get(f"https://m.blog.naver.com/{BLOG_ID}")
    time.sleep(3)

    prev_count = 0
    stale_count = 0

    for i in range(MAX_SCROLL):
        new_nos = extract_log_nos(driver)
        all_nos.update(new_nos)

        if i % 5 == 0 or len(all_nos) == prev_count:
            print(f"  scroll {i}: {len(all_nos)}건 수집", flush=True)

        if len(all_nos) == prev_count:
            stale_count += 1
            if stale_count >= 5:
                print(f"  → 5회 연속 변동 없음, 수집 종료")
                break
        else:
            stale_count = 0
            prev_count = len(all_nos)

        # 10 스크롤마다 중간 저장
        if i % 10 == 0 and i > 0:
            _save_log_nos(all_nos)

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(SCROLL_PAUSE)

    _save_log_nos(all_nos)
    print(f"\n[목록 완료] 총 {len(all_nos)}건 고유 게시글")
    return all_nos


def _normalize_date(raw):
    """네이버 날짜 문자열 → YYYY-MM-DD 정규화"""
    if not raw:
        return ""
    # "2026. 3. 19. 9:47" 패턴
    m = re.match(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # "N시간 전", "N일 전" 등 — 오늘 날짜 기준 근사
    today = datetime.now()
    if "분 전" in raw or "시간 전" in raw or "방금" in raw:
        return today.strftime("%Y-%m-%d")
    m = re.search(r"(\d+)일 전", raw)
    if m:
        from datetime import timedelta
        d = today - timedelta(days=int(m.group(1)))
        return d.strftime("%Y-%m-%d")
    return raw  # 파싱 실패 시 원본 유지


def scrape_post(driver, log_no):
    """개별 게시글 내용 수집 (PC 버전 PostView 직접 접근)"""
    url = f"https://blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={log_no}"
    driver.get(url)
    time.sleep(2)

    post = {
        "log_no": log_no,
        "url": f"https://blog.naver.com/{BLOG_ID}/{log_no}",
        "scraped_at": datetime.now().isoformat(),
    }

    # 제목
    for sel in [".se-title-text", "div.se_title .se_textView span", ".pcol1 .itemSubjectBoldfont", ".htitle"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els and els[0].text.strip():
            post["title"] = els[0].text.strip()
            break
    else:
        post["title"] = ""

    # 날짜
    raw_date = ""
    for sel in ["span.se_publishDate", ".date", ".se-date", ".blog_date"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els and els[0].text.strip():
            raw_date = els[0].text.strip()
            break
    post["date"] = _normalize_date(raw_date)
    post["date_raw"] = raw_date

    # 카테고리 — 1) 블로그 카테고리 (구글 검색에서 추출, 예전 글에 설정)
    blog_cat = ""
    for sel in [".category a", ".blog2_category a", "a._cur_category"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els and els[0].text.strip():
            t = els[0].text.strip()
            if t not in ("카테고리 이동", "게시판"):
                blog_cat = t
                break
    post["blog_category"] = blog_cat

    # 카테고리 — 2) 제목 앞 [태그]에서 추출
    tag_match = re.match(r"\[(?:공지\]\s*\[)?(.+?)\]", post.get("title", ""))
    post["title_tag"] = tag_match.group(1) if tag_match else ""

    # 통합 카테고리 (blog_category 우선, 없으면 title_tag)
    post["category"] = blog_cat or (tag_match.group(1) if tag_match else "")

    # 본문 텍스트
    for sel in [".se-main-container", "#postViewArea", "div.se_component_wrap", ".post-view"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els and els[0].text.strip():
            post["content"] = els[0].text.strip()
            break
    else:
        post["content"] = ""

    if not post["title"] and not post["content"]:
        return None

    return post


def _save_log_nos(log_nos):
    """logNo 목록 캐시 저장"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_NOS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(log_nos), f)
    print(f"[목록 저장] {len(log_nos)}건 → {LOG_NOS_FILE}")


def _load_log_nos():
    """캐시된 logNo 목록 로드"""
    if LOG_NOS_FILE.exists():
        with open(LOG_NOS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def step1_collect_urls():
    """1단계: 전체 게시글 logNo 수집 (별도 드라이버)"""
    print("── 1단계: 게시글 목록 수집 (모바일 스크롤) ──")
    driver = create_driver()
    try:
        all_nos = collect_all_log_nos(driver)
    except Exception as e:
        print(f"[경고] 스크롤 중 오류: {e}")
        all_nos = _load_log_nos()
        print(f"  → 캐시에서 {len(all_nos)}건 복구")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return all_nos


def step2_scrape_posts(log_nos=None, incremental=True, batch_size=100):
    """2단계: 개별 게시글 내용 수집 (배치 단위로 드라이버 재시작)"""
    if log_nos is None:
        log_nos = _load_log_nos()
        if not log_nos:
            print("[오류] logNo 목록 없음. step1_collect_urls() 먼저 실행")
            return

    existing = load_existing_posts() if incremental else {}

    if incremental:
        new_nos = sorted(log_nos - set(existing.keys()))
        print(f"[필터] 신규 {len(new_nos)}건 (기존 {len(existing)}건 스킵)")
    else:
        new_nos = sorted(log_nos)

    if not new_nos:
        print("[완료] 새 글 없음")
        return

    print(f"\n── 2단계: 게시글 내용 수집 ({len(new_nos)}건) ──")
    success, fail = 0, 0

    # 배치 단위로 드라이버 재시작 (메모리 누수/타임아웃 방지)
    for batch_start in range(0, len(new_nos), batch_size):
        batch = new_nos[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        print(f"\n  [배치 {batch_num}] {batch_start+1}~{batch_start+len(batch)}건")

        driver = create_driver()
        try:
            for j, log_no in enumerate(batch, 1):
                i = batch_start + j
                try:
                    post = scrape_post(driver, log_no)
                except Exception as e:
                    print(f"  [{i}/{len(new_nos)}] ERROR: {e}")
                    fail += 1
                    continue

                if post:
                    existing[log_no] = post
                    success += 1
                    if i % 20 == 0 or j <= 2:
                        title_preview = post["title"][:40] if post["title"] else "(no title)"
                        print(f"  [{i}/{len(new_nos)}] {title_preview} | {post['date']}", flush=True)
                else:
                    fail += 1

                time.sleep(1.0)
        except Exception as e:
            print(f"  [배치 {batch_num} 오류] {e}")
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        # 배치 종료 시 저장
        save_posts(existing)

    print(f"\n[완료] 성공 {success}건, 실패 {fail}건, 총 {len(existing)}건 저장")


def run(incremental=True):
    """전체 파이프라인: 목록 수집 → 개별 글 수집"""
    existing = load_existing_posts() if incremental else {}
    print(f"[시작] 기존 {len(existing)}건 로드됨")

    # 1단계: 목록
    all_nos = step1_collect_urls()

    # 2단계: 글 수집
    step2_scrape_posts(all_nos, incremental=incremental)


if __name__ == "__main__":
    run(incremental=True)
