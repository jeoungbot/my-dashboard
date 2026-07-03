#!/usr/bin/env python3
"""
공모전·인턴십·장학금 자동 크롤러 v5
Sources  : linkareer.com, contestkorea.com, thinkyou.co.kr,
           kstudy.com, janghaggeum.com, jobkorea.co.kr, krs.co.kr
Bot 우회 : cloudscraper + 완전 Chrome 헤더 + 세션 워밍업 + 재시도
Output   : ../data.json  (지원 가능한 공고만, 지원 마감일 기준 필터)
"""

import json, re, time, os, hashlib, random
from datetime import datetime, date, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    from dateutil import parser as _du_parser
    def _dateutil_parse(s: str):
        return _du_parser.parse(s, dayfirst=False)
except ImportError:
    _du_parser = None
    def _dateutil_parse(s: str):
        raise ValueError("dateutil not available")

try:
    import cloudscraper as _cs_mod
    _HAS_CLOUDSCRAPER = True
except ImportError:
    _cs_mod = None
    _HAS_CLOUDSCRAPER = False

# ─────────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────────

OUT_PATH          = os.path.join(os.path.dirname(__file__), "..", "data.json")
LINKAREER_BASE    = "https://linkareer.com"
CONTESTKOREA_BASE = "https://www.contestkorea.com"
KR_RECRUIT_URL    = "https://www.krs.co.kr/kor/BBS/BF_Main.aspx?MRID=305&URID=300"
THINKYOU_BASE     = "https://www.thinkyou.co.kr"
KSTUDY_BASE       = "https://www.kstudy.com"
JANGHAGGEUM_BASE  = "https://www.janghaggeum.com"
JOBKOREA_BASE     = "https://www.jobkorea.co.kr"

# 실제 Chrome 125 브라우저와 동일한 헤더 (순서 포함)
_CHROME_HEADERS = [
    ("User-Agent",
     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    ("Accept",
     "text/html,application/xhtml+xml,application/xml;"
     "q=0.9,image/avif,image/webp,image/apng,*/*;"
     "q=0.8,application/signed-exchange;v=b3;q=0.7"),
    ("Accept-Language", "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"),
    ("Accept-Encoding", "gzip, deflate, br"),
    ("Cache-Control", "max-age=0"),
    ("Upgrade-Insecure-Requests", "1"),
    ("Sec-Fetch-Dest", "document"),
    ("Sec-Fetch-Mode", "navigate"),
    ("Sec-Fetch-Site", "none"),
    ("Sec-Fetch-User", "?1"),
    ("sec-ch-ua",
     '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"'),
    ("sec-ch-ua-mobile", "?0"),
    ("sec-ch-ua-platform", '"Windows"'),
    ("Connection", "keep-alive"),
    ("DNT", "1"),
]


def _make_session() -> requests.Session:
    """cloudscraper 우선, 없으면 requests.Session."""
    if _HAS_CLOUDSCRAPER:
        s = _cs_mod.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False},
            delay=3,
        )
        print("  🛡  cloudscraper 활성화 (봇 차단 우회)")
    else:
        s = requests.Session()
        print("  ⚠  cloudscraper 없음 — 기본 requests.Session 사용")

    s.headers.clear()
    for k, v in _CHROME_HEADERS:
        s.headers[k] = v
    return s


_SESSION: Optional[requests.Session] = None


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _make_session()
    return _SESSION


def _warm_up(base_url: str) -> None:
    """봇 감지 우회를 위해 홈페이지를 먼저 방문해 쿠키를 획득."""
    s = _session()
    try:
        s.headers["Referer"] = ""
        s.headers["Sec-Fetch-Site"] = "none"
        r = s.get(base_url, timeout=20)
        print(f"  🌐 워밍업 {base_url} → HTTP {r.status_code}")
        time.sleep(random.uniform(1.5, 2.5))
        s.headers["Sec-Fetch-Site"] = "same-origin"
        s.headers["Referer"] = base_url + "/"
    except Exception as e:
        print(f"  ⚠  워밍업 실패: {e}")


def fetch(url: str, retries: int = 3, timeout: int = 30) -> Optional[BeautifulSoup]:
    """재시도 + 지수 백오프 포함 fetch."""
    s = _session()
    for attempt in range(retries):
        wait = random.uniform(2.0, 3.5) + attempt * 2.5
        time.sleep(wait)
        try:
            r = s.get(url, timeout=timeout)
            if r.status_code in (403, 429, 503):
                print(f"    ⚠  HTTP {r.status_code} (시도 {attempt+1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(10 + attempt * 8)
                continue
            r.raise_for_status()
            enc = r.encoding or r.apparent_encoding or "utf-8"
            return BeautifulSoup(r.content, "lxml", from_encoding=enc)
        except Exception as e:
            print(f"    ⚠  오류 ({attempt+1}/{retries}): {type(e).__name__}: {e}")
            if attempt < retries - 1:
                time.sleep(5 + attempt * 4)
    print(f"    ✖  {url} — {retries}회 모두 실패")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _md5(*parts) -> str:
    return hashlib.md5("§".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _parse_ymd(text: str) -> Optional[str]:
    """다양한 날짜 표기 → YYYY-MM-DD (실패 시 None)."""
    if not text:
        return None
    t = re.sub(r"[년월일()\[\]까지마감접수기간~\s]", " ", str(text)).strip()

    m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    m = re.search(r"(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", t)
    if m:
        y = int(m.group(1)) + 2000
        return f"{y}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    try:
        return _dateutil_parse(t).strftime("%Y-%m-%d")
    except Exception:
        return None


def _ck_deadline(text: str) -> Optional[str]:
    """
    '26.05.16~27.01.16' 형태에서 마감일(뒤 날짜) 추출.
    """
    m = re.search(
        r"(\d{2})[.\-](\d{2})[.\-](\d{2})\s*~\s*(\d{2})[.\-](\d{2})[.\-](\d{2})",
        text
    )
    if m:
        y = int(m.group(4)) + 2000
        return f"{y}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"

    m = re.search(
        r"20\d{2}[.\-]\d{2}[.\-]\d{2}\s*~\s*(20\d{2})[.\-](\d{2})[.\-](\d{2})",
        text
    )
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    return _parse_ymd(text)


def _is_active(deadline: Optional[str]) -> bool:
    """지원 마감일이 오늘 이상인지 확인."""
    if not deadline:
        return False
    try:
        dl = date.fromisoformat(deadline)
        today = date.today()
        if dl < today:
            return False
        if (dl - today).days > 365 * 5:
            return False
        return True
    except ValueError:
        return False


def _extract_eligibility(text: str) -> dict:
    """제목·설명에서 지원 자격(학년, 학점) 추출."""
    t = text
    grade = ""
    gpa = ""
    note = ""

    # 학년 범위 패턴: "1~4학년", "전학년"
    m = re.search(r"(\d+)[~\-](\d+)\s*학년", t)
    if m:
        grade = f"{m.group(1)}~{m.group(2)}학년"
    else:
        m = re.search(r"(\d+)\s*학년\s*이상", t)
        if m:
            grade = f"{m.group(1)}학년 이상"
        else:
            m = re.search(r"(\d+)\s*학년", t)
            if m:
                grade = f"{m.group(1)}학년"
            elif "전학년" in t or "재학생" in t:
                grade = "전학년"

    # 학점 패턴
    m = re.search(r"(학점|gpa)[^\d]*(\d+\.\d+)", t, re.IGNORECASE)
    if m:
        gpa = f"{m.group(2)} 이상"
    else:
        m = re.search(r"(\d+\.\d+)\s*(학점|gpa|이상)", t, re.IGNORECASE)
        if m:
            gpa = f"{m.group(1)} 이상"

    return {"grade": grade, "gpa": gpa, "note": note}


# ─────────────────────────────────────────────────────────────────────────────
# 분류
# ─────────────────────────────────────────────────────────────────────────────

def _classify_scholar_sub(title: str, org: str = "", hint: str = "") -> str:
    """장학금 세부 카테고리 분류."""
    t = f"{title} {org} {hint}".lower()

    # 지역 장학금
    if any(k in t for k in [
        "부산", "경남", "경북", "경기", "서울", "인천", "대구", "광주", "대전",
        "울산", "세종", "강원", "충북", "충남", "전북", "전남", "제주",
        "지역", "향토", "로컬",
    ]):
        return "scholar_region"

    # 국가/공공 장학금
    if any(k in t for k in [
        "국가장학", "정부", "교육부", "한국장학재단", "kosaf", "국가",
        "공공기관", "공단", "공사", "공기업",
    ]):
        return "scholar_public"

    # 성적 우수 장학금
    if any(k in t for k in [
        "성적", "우수", "gpa", "학점", "수석", "우등", "성적우수", "학업우수",
    ]):
        return "scholar_merit"

    # 대학교 외부 장학금
    if any(k in t for k in [
        "총동문회", "동문회", "동문", "alumni", "졸업생",
    ]):
        return "scholar_univ"

    # 기업/사설 장학금
    if any(k in t for k in [
        "재단", "그룹", "기업", "주식회사", "삼성", "현대", "lg", "sk",
        "롯데", "포스코", "kt", "사설", "민간", "법인",
    ]):
        return "scholar_corp"

    return "scholar"


# 조선·기계·방산 관련 기술 키워드
_SHIP_TECH: frozenset[str] = frozenset([
    "조선", "선박", "해양", "플랜트", "lng", "ship", "marine", "offshore",
    "기계공학", "기계설계", "기계시스템", "기계항공", "금속공학", "재료공학",
    "용접", "한국선급", "kriso", "dsme", "선체", "선각", "추진기", "배관",
    "해양구조물", "부유식", "fpso", "drillship", "조선해양", "조선공학",
    "해양공학", "조선기자재", "선박기자재",
])

# 조선·기계·방산 주요 기업 및 연구소 이름 (소문자 비교용)
_SHIP_COS: frozenset[str] = frozenset([
    # 조선 빅3 계열
    "한화오션", "삼성중공업", "hd현대중공업", "현대중공업", "현대미포조선",
    "현대삼호중공업", "현대삼호",
    # 중견 조선
    "hj중공업", "한진중공업", "대한조선", "케이조선", "대선조선",
    "성동조선", "stx조선",
    # 기계·방산·에너지
    "한화에어로스페이스", "한화에어로", "두산에너빌리티", "두산중공업",
    "한화파워시스템", "hd현대인프라코어", "현대두산인프라코어",
    "한화시스템", "lg이노텍조선", "현대로보틱스",
    # 연구소
    "선박해양플랜트연구소", "한국기계연구원", "kimm", "생산기술연구원",
    "kitech", "rist",
])


def _is_ship_related(t: str) -> bool:
    return any(k in t for k in _SHIP_TECH) or any(k in t for k in _SHIP_COS)


def _classify(title: str, org: str = "", hint: str = "") -> str:
    t = f"{title} {org} {hint}".lower()

    if _is_ship_related(t):
        if any(k in t for k in ["공모전", "경진", "아이디어", "contest", "경쟁", "챌린지"]):
            return "ship_contest"
        if any(k in t for k in ["학술", "논문", "세미나", "학회", "심포지엄"]):
            return "ship_academic"
        if any(k in t for k in ["해외", "global", "abroad", "overseas", "해외인턴"]):
            return "ship_global"
        if any(k in t for k in ["장학", "scholarship"]):
            return "ship_scholar"
        return "ship_recruit"

    if any(k in t for k in [
        "ai", "iot", "인공지능", "딥러닝", "머신러닝", "빅데이터", "데이터사이언스",
        "소프트웨어", "해커톤", "알고리즘", "it공모", "it 공모", "정보보안",
        "사이버보안", "클라우드", "sw공모", "개발자공모",
    ]):
        return "ai"

    if any(k in t for k in [
        "영상", "콘텐츠", "ucc", "사진", "영화", "광고", "미디어", "방송",
        "유튜브", "숏폼", "크리에이터", "뮤직비디오",
    ]):
        return "media"

    if any(k in t for k in [
        "해외", "글로벌", "global", "overseas", "무역관", "해외인턴", "해외취업",
    ]):
        return "global"

    if "인턴" in t:
        return "corp"

    if any(k in t for k in ["장학", "scholarship", "장학금", "학자금"]):
        return _classify_scholar_sub(title, org, hint)

    return "activity"


def _clean_url(href: str, base: str = "") -> str:
    href = (href or "").strip()
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return base + href
    return base + "/" + href


# ─────────────────────────────────────────────────────────────────────────────
# 링커리어 (공모전·대외활동·인턴)
# ─────────────────────────────────────────────────────────────────────────────

def _apollo_items(soup: BeautifulSoup, hint: str) -> list[dict]:
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        print("    __NEXT_DATA__ 없음")
        return []

    try:
        data = json.loads(tag.string)
    except Exception as e:
        print(f"    JSON 파싱 오류: {e}")
        return []

    apollo: dict = (
        data.get("props", {})
            .get("pageProps", {})
            .get("__APOLLO_STATE__", {})
    )
    if not apollo:
        print("    __APOLLO_STATE__ 없음")
        return []

    results = []
    for key, val in apollo.items():
        if not re.match(r"^Activity:\d+$", key):
            continue
        if not isinstance(val, dict):
            continue
        item = _lk_build(val, hint)
        if item:
            results.append(item)

    return results


def _lk_build(val: dict, hint: str) -> Optional[dict]:
    try:
        aid   = str(val.get("id", ""))
        title = (val.get("title") or "").strip()
        if not aid or not title:
            return None

        org = (val.get("organizationName") or "미상").strip()

        close_ms = val.get("recruitCloseAt")
        if not close_ms:
            return None

        deadline = datetime.fromtimestamp(int(close_ms) / 1000).strftime("%Y-%m-%d")
        if not _is_active(deadline):
            return None

        url = f"{LINKAREER_BASE}/activity/{aid}"
        cat = _classify(title, org, hint)
        elig = _extract_eligibility(title)

        return {
            "id":          f"lk_{aid}",
            "title":       title,
            "org":         org,
            "cat":         cat,
            "deadline":    deadline,
            "url":         url,
            "src":         "링커리어",
            "desc":        "",
            "tags":        [],
            "eligibility": elig,
        }
    except Exception:
        return None


def scrape_linkareer() -> list[dict]:
    print("📡 링커리어 크롤링...")
    _warm_up(LINKAREER_BASE)

    pages = [
        (f"{LINKAREER_BASE}/list/contest",  "공모전"),
        (f"{LINKAREER_BASE}/list/club",     "대외활동"),
        (f"{LINKAREER_BASE}/list/intern",   "인턴십"),
    ]

    results = []
    for url, hint in pages:
        print(f"  → {hint}: {url}")
        soup = fetch(url)
        if not soup:
            print(f"     ✖ 수집 실패 — 다음 페이지로 진행")
            continue

        page_text = soup.get_text()
        if "access denied" in page_text.lower() or "captcha" in page_text.lower():
            print(f"     ⚠  봇 차단 응답 감지")
            continue

        nd_tag = soup.find("script", id="__NEXT_DATA__")
        if not nd_tag:
            print(f"     ⚠  __NEXT_DATA__ 없음")
            continue

        items = _apollo_items(soup, hint)
        print(f"     {len(items)}건 (활성)")
        results.extend(items)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 링커리어 장학금 (별도 시도)
# ─────────────────────────────────────────────────────────────────────────────

def scrape_linkareer_scholarship() -> list[dict]:
    """링커리어 장학금 페이지 크롤링 (페이지 1-3)."""
    print("📡 링커리어 장학금 크롤링 (다중 페이지)...")

    all_items: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(1, 4):
        url = (f"{LINKAREER_BASE}/list/scholarship"
               if page == 1
               else f"{LINKAREER_BASE}/list/scholarship?page={page}")
        print(f"  → 장학금 p{page}: {url}")
        soup = fetch(url, retries=3, timeout=60)

        if not soup:
            print(f"     ✖ 수집 실패 (p{page})")
            break

        page_text = soup.get_text()
        if "access denied" in page_text.lower() or "captcha" in page_text.lower():
            print(f"     ⚠  봇 차단 감지 (p{page})")
            break

        nd_tag = soup.find("script", id="__NEXT_DATA__")
        if not nd_tag:
            print(f"     ⚠  __NEXT_DATA__ 없음 (p{page})")
            break

        page_items = _apollo_items(soup, "장학금")
        new_items = []
        for item in page_items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                item["cat"] = _classify_scholar_sub(item["title"], item["org"], "장학금")
                item["eligibility"] = _extract_eligibility(item["title"])
                new_items.append(item)

        print(f"     {len(new_items)}건 (신규)")
        if not new_items:
            break
        all_items.extend(new_items)
        if page < 3:
            time.sleep(random.uniform(2.0, 3.5))

    print(f"  → 링커리어 장학금 총 {len(all_items)}건")
    return all_items


# ─────────────────────────────────────────────────────────────────────────────
# 씽유 (thinkyou.co.kr) 공모전 · 장학금
# ─────────────────────────────────────────────────────────────────────────────
#
# 구조: 메인 및 카테고리 페이지 <a onclick="location.href='URL'"> 파싱
#       상세 페이지 <table> 내 TR(접수기간, 주최, 응모자격) 파싱
# 장학금 키워드 포함 시 → scholar_* 분류, 그 외 → activity/media/ai 등

def scrape_thinkyou() -> list[dict]:
    """씽유(thinkyou.co.kr) 크롤링 - 공모전 및 대외활동."""
    print("📡 씽유 크롤링...")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    simple_hdr = dict(_CHROME_HEADERS)
    simple_hdr["Referer"] = THINKYOU_BASE + "/"

    # ── Step 1: 대외활동을 먼저, 공모전을 나중에 방문 (extAct가 contest 링크를 노출해 중복 방지)
    # 씽유에는 /scholarship/ 페이지가 없음; 장학금은 키워드로 분류
    target_pages = [
        (f"{THINKYOU_BASE}/extAct/",  "대외활동"),
        (f"{THINKYOU_BASE}/contest/", "공모전"),
    ]
    all_links: list[tuple[str, str, str]] = []  # (title, url, page_hint)
    seen_urls: set[str] = set()

    for page_url, label in target_pages:
        before = len(all_links)
        try:
            r = requests.get(page_url, headers=simple_hdr, timeout=12, verify=False)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "lxml")
        except Exception as e:
            print(f"  ✖ 씽유 {label} 페이지 실패: {e}")
            continue

        for a in soup.find_all("a", onclick=re.compile(r"location\.href")):
            onclick = a.get("onclick", "")
            m = re.search(r"location\.href='([^']+)'", onclick)
            if not m:
                continue
            href = m.group(1)
            if not href.startswith("http"):
                href = THINKYOU_BASE + href
            # 상세 페이지 URL인지 확인
            if not re.search(r"/(contest|extAct|scholarship)/\d+", href):
                continue
            # 제목: img alt 우선, 없으면 텍스트
            img = a.find("img")
            title = (img.get("alt", "") if img else "").strip() or a.get_text(strip=True)[:80]
            if not title or href in seen_urls:
                continue
            seen_urls.add(href)
            all_links.append((title, href, label))  # label을 hint로 저장

        print(f"  → 씽유 {label}: {len(all_links) - before}개 링크")
        time.sleep(random.uniform(1.0, 2.0))

    # ── Step 2: 상세 페이지 방문하여 마감일·주최·자격 파싱 ──
    results: list[dict] = []
    limit = min(len(all_links), 45)   # 최대 45건
    print(f"  상세 페이지 방문: {limit}건...")

    for title, url, page_hint in all_links[:limit]:
        time.sleep(random.uniform(0.8, 1.6))
        try:
            r = requests.get(url, headers=simple_hdr, timeout=10, verify=False)
            r.raise_for_status()
            detail = BeautifulSoup(r.content, "lxml")
        except Exception:
            continue

        org = "미상"
        deadline = None
        eligibility_text = ""

        for tr in detail.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not (th and td):
                continue
            th_txt = th.get_text(strip=True)
            td_txt = td.get_text(" ", strip=True)

            if any(k in th_txt for k in ["주최", "주관", "주최·주관", "주관·주최"]):
                org = re.sub(r"[·/].*", "", td_txt).strip()[:60] or "미상"
            elif any(k in th_txt for k in ["접수기간", "공모기간", "모집기간", "신청기간"]):
                deadline = _ck_deadline(td_txt)
            elif any(k in th_txt for k in ["응모자격", "지원자격", "신청자격", "참가자격"]):
                eligibility_text = td_txt[:200]

        if not _is_active(deadline):
            continue

        # 장학금 페이지 출처이거나 제목/기관에 장학 키워드 있으면 scholar 분류
        if page_hint == "장학금" or any(
            k in f"{title} {org}".lower()
            for k in ["장학", "scholarship", "학자금"]
        ):
            cat = _classify_scholar_sub(title, org, page_hint)
        else:
            cat = _classify(title, org, "씽유")

        elig = _extract_eligibility(f"{title} {eligibility_text}")
        tags = ["씽유"]
        if eligibility_text:
            if "대학" in eligibility_text:
                tags.append("대학생")
            if any(k in eligibility_text for k in ["전국민", "누구나", "제한 없음"]):
                tags.append("누구나")

        results.append({
            "id":          _md5("ty", url),
            "title":       title,
            "org":         org,
            "cat":         cat,
            "deadline":    deadline,
            "url":         url,
            "src":         "씽유",
            "desc":        eligibility_text[:100] if eligibility_text else "",
            "tags":        tags,
            "eligibility": elig,
        })

    print(f"  → 씽유 활성 항목: {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 한국선급 (KR)
# ─────────────────────────────────────────────────────────────────────────────

def scrape_kr_recruit() -> list[dict]:
    """한국선급(KR) 채용공고 크롤링."""
    print("📡 한국선급(KR) 채용 크롤링...")
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(
            KR_RECRUIT_URL,
            headers=dict(_CHROME_HEADERS),
            timeout=15,
            verify=False,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "lxml")
    except Exception as e:
        print(f"  ✖ KR선급 연결 실패: {e}")
        return []

    today = date.today()
    results: list[dict] = []

    for tr in soup.select(".board_list tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        title = tds[1].get_text(strip=True) if len(tds) > 1 else ""
        if not title:
            continue

        row_text = tr.get_text(" ", strip=True)
        # 날짜 패턴 전부 추출 (YYYY.MM.DD 또는 YYYY-MM-DD)
        all_dates = re.findall(r"\d{4}[.\-]\d{1,2}[.\-]\d{1,2}", row_text)
        parsed_dates = [_parse_ymd(d) for d in all_dates]
        parsed_dates = [d for d in parsed_dates if d]

        deadline: Optional[str] = None
        if len(parsed_dates) >= 2:
            # "시작일 ~ 종료일" 형태 — 가장 늦은 날짜를 마감일로
            deadline = max(parsed_dates)
        elif len(parsed_dates) == 1:
            # 날짜 1개 = 등록일 추정 → +180일
            reg = date.fromisoformat(parsed_dates[0])
            if (today - reg).days > 180:
                continue
            deadline = (reg + timedelta(days=180)).isoformat()
        else:
            continue

        if not _is_active(deadline):
            continue

        results.append({
            "id":          _md5("kr", title),
            "title":       title,
            "org":         "한국선급(KR)",
            "cat":         "ship_recruit",
            "deadline":    deadline,
            "url":         KR_RECRUIT_URL,
            "src":         "한국선급",
            "desc":        f"접수기간: {' ~ '.join(parsed_dates)}" if parsed_dates else "",
            "tags":        ["채용", "조선"],
            "eligibility": {"grade": "", "gpa": "", "note": ""},
        })

    print(f"  {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 공모전코리아
# ─────────────────────────────────────────────────────────────────────────────

# 공모전 (int_gbn=1) — 실제 사이트 카테고리에서 확인한 정확한 bcode
_CK_CONTEST_BCODES: dict[str, str] = {
    "030110001": "문학·문예",
    "030210001": "네이밍·슬로건",
    "030310001": "학문·과학·IT",
    "030610001": "미술·디자인·웹툰",
    "030810001": "스포츠",
    "030910001": "음악·콩쿠르·댄스",
    "031210001": "사진·영상·영화제",
    "031410001": "아이디어·건축·창업",
    "031810001": "다양한 분야",
}

# 대외활동 (int_gbn=2) — 장학금·인턴 포함
_CK_ACTIVITY_BCODES: dict[str, str] = {
    "040110001": "서포터즈·기자단",
    "040210001": "인턴·체험·탐방·봉사·동아리",
    "040310001": "서평단·참여단",
    "040410001": "교육·강연·멘토링",
    "040510001": "전시·박람·행사",
    "040610001": "다양한 대외활동",
    "040710001": "기획·홍보·마케팅",
}


def scrape_contestkorea() -> list[dict]:
    print("📡 공모전코리아 크롤링...")
    _warm_up(CONTESTKOREA_BASE)
    results = []

    for bcode, label in _CK_CONTEST_BCODES.items():
        url = f"{CONTESTKOREA_BASE}/sub/list.php?int_gbn=1&Txt_bcode={bcode}"
        print(f"  → {label}: {url}")
        items = _ck_page(url, bcode, int_gbn=1)
        print(f"     {len(items)}건")
        results.extend(items)

    for bcode, label in _CK_ACTIVITY_BCODES.items():
        url = f"{CONTESTKOREA_BASE}/sub/list.php?int_gbn=2&Txt_bcode={bcode}"
        print(f"  → [대외활동] {label}: {url}")
        items = _ck_page(url, bcode, int_gbn=2)
        print(f"     {len(items)}건")
        results.extend(items)

    return results


def _ck_page(url: str, bcode: str, int_gbn: int = 1) -> list[dict]:
    soup = fetch(url)
    if not soup:
        return []

    items: list[dict] = []
    seen_titles: set[str] = set()

    def add(item: Optional[dict]) -> None:
        if not item:
            return
        key = re.sub(r"\s+", "", item["title"].lower())
        if key in seen_titles:
            return
        seen_titles.add(key)
        items.append(item)

    # 타입 1: li.imminent
    for li in soup.select("li.imminent"):
        title_div = li.find("div", class_="title")
        if not title_div:
            continue
        link = title_div.find("a", href=True)
        if not link:
            continue

        for sp in link.find_all("span", class_="category"):
            sp.decompose()
        txt_span = link.find("span", class_="txt")
        title = (txt_span.get_text(strip=True) if txt_span
                 else link.get_text(strip=True)).strip()
        if not title:
            continue

        href = link["href"]
        clean_href = _ck_clean_href(href, bcode, int_gbn)

        host_ul  = li.find("ul", class_="host")
        deadline = _ck_deadline(host_ul.get_text(" ", strip=True) if host_ul else "")
        if not deadline:
            deadline = _ck_deadline(li.get_text(" ", strip=True))

        if not _is_active(deadline):
            continue

        org = "미상"
        if host_ul:
            for hli in host_ul.find_all("li"):
                cls = " ".join(hli.get("class", []))
                txt = hli.get_text(strip=True)
                if "icon_2" in cls or ("주최" in txt and "." in txt):
                    org = re.sub(r"^(주최|주관)\s*[.]\s*", "", txt).strip() or "미상"
                    break

        elig = _extract_eligibility(li.get_text(" ", strip=True))
        add({
            "id":          _md5("ck", title),
            "title":       title,
            "org":         org,
            "cat":         _classify(title, org, "공모전코리아"),
            "deadline":    deadline,
            "url":         clean_href,
            "src":         "공모전코리아",
            "desc":        "",
            "tags":        [],
            "eligibility": elig,
        })

    # 타입 2: 카드형 (div.txt_area)
    for li in soup.find_all("li"):
        txt_area = li.find("div", class_="txt_area")
        if not txt_area:
            continue
        link = txt_area.find("a", href=True)
        if not link:
            continue

        title_span = txt_area.find("span", class_="title")
        date_span  = txt_area.find("span", class_="date")
        org_span   = txt_area.find("span", class_="name")

        title = title_span.get_text(strip=True) if title_span else ""
        if not title:
            continue

        date_text = date_span.get_text(strip=True) if date_span else ""
        deadline  = _ck_deadline(date_text)

        if not _is_active(deadline):
            continue

        org  = (org_span.get_text(strip=True) if org_span else "미상") or "미상"
        href = _ck_clean_href(link["href"], bcode, int_gbn)
        elig = _extract_eligibility(title)

        add({
            "id":          _md5("ck", title),
            "title":       title,
            "org":         org,
            "cat":         _classify(title, org, "공모전코리아"),
            "deadline":    deadline,
            "url":         href,
            "src":         "공모전코리아",
            "desc":        "",
            "tags":        [],
            "eligibility": elig,
        })

    return items


def _ck_clean_href(href: str, bcode: str, int_gbn: int = 1) -> str:
    m = re.search(r"str_no=(\w+)", href)
    if m:
        str_no = m.group(1)
        return (
            f"{CONTESTKOREA_BASE}/sub/view.php"
            f"?int_gbn={int_gbn}&Txt_bcode={bcode}&str_no={str_no}"
        )
    return _clean_url(href, CONTESTKOREA_BASE)


# ─────────────────────────────────────────────────────────────────────────────
# 공모전코리아 장학금 키워드 검색 (상세 페이지 방문으로 날짜 추출)
# ─────────────────────────────────────────────────────────────────────────────

def scrape_contestkorea_scholar() -> list[dict]:
    """공모전코리아에서 '장학' 키워드 검색 후 상세 페이지 방문으로 날짜 추출."""
    import urllib.parse
    print("📡 공모전코리아 장학금 키워드 검색...")

    candidates: list[tuple[str, str]] = []  # (title, url)
    seen_urls: set[str] = set()

    for kw in ["장학", "장학재단"]:
        url = f"{CONTESTKOREA_BASE}/sub/search.php?Txt_word={urllib.parse.quote(kw)}"
        soup = fetch(url, retries=2)
        if not soup:
            continue
        for li in soup.select("li.imminent"):
            title_div = li.find("div", class_="title")
            if not title_div:
                continue
            link = title_div.find("a", href=True)
            if not link:
                continue
            for sp in link.find_all("span", class_="category"):
                sp.decompose()
            title = link.get_text(strip=True).strip()
            if not title:
                continue
            href = link["href"]
            # 상대경로(view.php, list.php)는 /sub/ 기준으로 조합
            if not href.startswith("http") and not href.startswith("/"):
                href = "/sub/" + href
            detail_url = _clean_url(href, CONTESTKOREA_BASE)
            if detail_url not in seen_urls:
                seen_urls.add(detail_url)
                candidates.append((title, detail_url))
        time.sleep(random.uniform(1.5, 2.5))

    print(f"  후보 {len(candidates)}건 → 상세 페이지 방문")
    results: list[dict] = []
    seen_keys: set[str] = set()

    for title, detail_url in candidates[:20]:
        key = re.sub(r"\s+", "", title.lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        time.sleep(random.uniform(1.5, 2.5))
        detail = fetch(detail_url, retries=1)
        if not detail:
            continue

        org = "미상"
        deadline = None
        elig_text = ""

        for tr in detail.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not (th and td):
                continue
            th_txt = th.get_text(strip=True)
            td_txt = td.get_text(" ", strip=True)
            if any(k in th_txt for k in ["주최", "주관"]):
                org = re.sub(r"[·/].*", "", td_txt).strip()[:60] or "미상"
            elif any(k in th_txt for k in ["접수기간", "공모기간", "신청기간"]):
                deadline = _ck_deadline(td_txt)
            elif any(k in th_txt for k in ["참가대상", "지원자격", "응모자격", "참가자격"]):
                elig_text = td_txt[:200]

        if not _is_active(deadline):
            continue

        cat = _classify_scholar_sub(title, org, "공모전코리아")
        results.append({
            "id":          _md5("cks", title),
            "title":       title,
            "org":         org,
            "cat":         cat,
            "deadline":    deadline,
            "url":         detail_url,
            "src":         "공모전코리아",
            "desc":        elig_text[:100] if elig_text else "",
            "tags":        ["장학금", "공모전코리아"],
            "eligibility": _extract_eligibility(f"{title} {elig_text}"),
        })

    print(f"  → 공모전코리아 장학금: {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 공모전코리아 조선/기계 키워드 검색
# ─────────────────────────────────────────────────────────────────────────────

def scrape_contestkorea_ship() -> list[dict]:
    """공모전코리아에서 조선/기계 키워드 검색 후 상세 페이지에서 마감일 추출."""
    import urllib.parse
    print("📡 공모전코리아 조선/기계 키워드 검색...")

    candidates: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    for kw in ["조선", "해양플랜트", "선박", "현대중공업", "한화오션", "삼성중공업"]:
        url = f"{CONTESTKOREA_BASE}/sub/search.php?Txt_word={urllib.parse.quote(kw)}"
        soup = fetch(url, retries=2)
        if not soup:
            continue
        for li in soup.select("li.imminent"):
            title_div = li.find("div", class_="title")
            if not title_div:
                continue
            link = title_div.find("a", href=True)
            if not link:
                continue
            for sp in link.find_all("span", class_="category"):
                sp.decompose()
            title = link.get_text(strip=True).strip()
            if not title:
                continue
            href = link["href"]
            if not href.startswith("http") and not href.startswith("/"):
                href = "/sub/" + href
            detail_url = _clean_url(href, CONTESTKOREA_BASE)
            if detail_url not in seen_urls:
                seen_urls.add(detail_url)
                candidates.append((title, detail_url))
        time.sleep(random.uniform(1.0, 2.0))

    print(f"  후보 {len(candidates)}건 → 상세 페이지 방문")
    results: list[dict] = []
    seen_keys: set[str] = set()

    for title, detail_url in candidates[:25]:
        key = re.sub(r"\s+", "", title.lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        time.sleep(random.uniform(1.0, 2.0))
        detail = fetch(detail_url, retries=1)
        if not detail:
            continue

        org = "미상"
        deadline = None

        for tr in detail.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not (th and td):
                continue
            th_txt = th.get_text(strip=True)
            td_txt = td.get_text(" ", strip=True)
            if any(k in th_txt for k in ["주최", "주관"]):
                org = re.sub(r"[·/].*", "", td_txt).strip()[:60] or "미상"
            elif any(k in th_txt for k in ["접수기간", "공모기간", "모집기간", "신청기간"]):
                deadline = _ck_deadline(td_txt)

        if not _is_active(deadline):
            continue

        cat = _classify(title, org, "공모전코리아")
        if not cat.startswith("ship"):
            cat = "ship_contest"

        results.append({
            "id":          _md5("cks_ship", title),
            "title":       title,
            "org":         org,
            "cat":         cat,
            "deadline":    deadline,
            "url":         detail_url,
            "src":         "공모전코리아",
            "desc":        "",
            "tags":        ["조선", "공모전코리아"],
            "eligibility": _extract_eligibility(title),
        })

    print(f"  → 공모전코리아 조선/기계: {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 사람인 조선/기계 채용 검색
# ─────────────────────────────────────────────────────────────────────────────

_SARAMIN_BASE = "https://www.saramin.co.kr"


def scrape_saramin_ship() -> list[dict]:
    """사람인 검색으로 조선/기계 기업 채용공고 수집 (인턴 포함)."""
    import urllib.parse
    print("📡 사람인 조선/기계 채용 검색...")

    results: list[dict] = []
    seen_urls: set[str] = set()

    search_terms = [
        "조선해양 인턴", "한화오션 채용", "삼성중공업 채용",
        "현대중공업 인턴", "선박 인턴십", "두산에너빌리티",
    ]

    for term in search_terms:
        url = (
            f"{_SARAMIN_BASE}/zf_user/search/recruit"
            f"?searchType=search&searchword={urllib.parse.quote(term)}&recruitPage=1"
        )
        soup = fetch(url, retries=2, timeout=25)
        if not soup:
            continue

        for item in soup.select(".item_recruit"):
            title_tag = item.select_one(".job_tit a")
            company_tag = item.select_one(".corp_name a")
            date_tag = item.select_one(".job_date .date")

            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            org = company_tag.get_text(strip=True) if company_tag else "미상"
            date_text = date_tag.get_text(strip=True) if date_tag else ""
            href = title_tag.get("href", "")
            detail_url = _clean_url(href, _SARAMIN_BASE) if href else _SARAMIN_BASE

            if detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)

            deadline = _parse_ymd(date_text) or _parse_ymd(re.sub(r"[^\d.]", ".", date_text))
            if not deadline:
                deadline = (date.today() + timedelta(days=30)).isoformat()

            if not _is_active(deadline):
                continue

            cat = _classify(title, org, "사람인")
            if not cat.startswith("ship"):
                if not _is_ship_related(f"{title} {org}".lower()):
                    continue
                cat = "ship_recruit"

            results.append({
                "id":          _md5("saramin", title + org),
                "title":       title,
                "org":         org,
                "cat":         cat,
                "deadline":    deadline,
                "url":         detail_url,
                "src":         "사람인",
                "desc":        "",
                "tags":        ["채용", "인턴"],
                "eligibility": _extract_eligibility(title),
            })

        time.sleep(random.uniform(1.5, 2.5))

    print(f"  → 사람인 조선/기계: {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 주요 기업 채용 페이지 직접 크롤링
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ship_career_page(soup: BeautifulSoup, org: str, base: str, src: str) -> list[dict]:
    """기업 채용 페이지 범용 파서 (테이블·카드 양식 모두 시도)."""
    results: list[dict] = []
    seen: set[str] = set()

    def _try_add(title: str, deadline_str: str, href: str) -> None:
        key = re.sub(r"\s+", "", title.lower())
        if key in seen or len(title) < 3:
            return
        deadline = _ck_deadline(deadline_str) or _parse_ymd(deadline_str)
        if not deadline:
            deadline = (date.today() + timedelta(days=60)).isoformat()
        if not _is_active(deadline):
            return
        seen.add(key)
        results.append({
            "id":          _md5(src, title),
            "title":       title[:100],
            "org":         org,
            "cat":         _classify(title, org, src),
            "deadline":    deadline,
            "url":         _clean_url(href, base),
            "src":         src,
            "desc":        "",
            "tags":        ["채용", "조선"],
            "eligibility": _extract_eligibility(title),
        })

    # 전략 1: 테이블 행
    for tr in soup.select("table tbody tr"):
        link = tr.find("a", href=True)
        if not link:
            continue
        title = link.get_text(strip=True)
        row_text = tr.get_text(" ", strip=True)
        _try_add(title, row_text, link["href"])

    # 전략 2: div/li 카드형
    if not results:
        for sel in [".list-item", ".recruit-item", ".job-item", "li.item", ".board-list li"]:
            for el in soup.select(sel):
                link = el.find("a", href=True)
                if not link:
                    continue
                title = link.get_text(strip=True)
                _try_add(title, el.get_text(" ", strip=True), link["href"])
            if results:
                break

    return results[:20]


_SHIP_CO_PAGES: list[tuple[str, str, str]] = [
    # (기관명, 채용페이지 URL, base URL)
    # 아래는 server-rendered 가능성이 있는 페이지만 포함
    # SPA(React/Next.js)인 경우 0건으로 실패하므로 안전
    ("한화오션",         "https://www.hanwhaocean.com/careers/ri/",              "https://www.hanwhaocean.com"),
    ("한화에어로스페이스", "https://www.hanwhaaerospace.com/kor/recruit/",        "https://www.hanwhaaerospace.com"),
    ("두산에너빌리티",   "https://www.doosanenerbility.com/en/employment/recruitment", "https://www.doosanenerbility.com"),
]


def scrape_ship_companies() -> list[dict]:
    """조선·기계 주요 기업 채용 페이지 크롤링."""
    print("📡 조선/기계 기업 채용 페이지 크롤링...")
    results: list[dict] = []

    for org, url, base in _SHIP_CO_PAGES:
        print(f"  → {org}: {url}")
        soup = fetch(url, retries=2, timeout=20)
        if not soup:
            continue
        items = _parse_ship_career_page(soup, org, base, org)
        if items:
            print(f"     {len(items)}건")
            results.extend(items)
        else:
            print(f"     0건 (파싱 실패 또는 공고 없음)")
        time.sleep(random.uniform(1.0, 2.0))

    print(f"  → 기업 채용 합계: {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 조선/기계 관련 연구소 채용 크롤링
# ─────────────────────────────────────────────────────────────────────────────

_SHIP_INSTITUTES: list[tuple[str, str, str]] = [
    # 채용공고 페이지 직접 URL (server-rendered 확인)
    ("KRISO(선박해양플랜트연구소)", "https://www.kriso.re.kr/board.es?mid=a10402030000&bid=0012", "https://www.kriso.re.kr"),
    ("한국기계연구원(KIMM)",        "https://www.kimm.re.kr/sub050301",                            "https://www.kimm.re.kr"),
    ("RIST(포항산업과학연구원)",    "https://www.rist.re.kr/contents/sub05_01.do",                 "https://www.rist.re.kr"),
]


def _parse_institute_board(soup: BeautifulSoup, org: str, base: str) -> list[dict]:
    """연구소 게시판 테이블 파서 — KRISO/KIMM 구조 대응."""
    results: list[dict] = []
    seen: set[str] = set()
    today = date.today()

    for tr in soup.select("table tbody tr, .board_list tbody tr"):
        cells = tr.find_all("td")
        link = tr.find("a", href=True)
        if not link or not cells:
            continue

        title = link.get_text(strip=True)
        title = re.sub(r"^새글\s*", "", title).strip()  # "새글" 접두 마커 제거
        if not title or len(title) < 4:
            continue

        # 상태 컬럼 "진행중" / "완료" 확인
        row_text = tr.get_text(" ", strip=True)
        if any(k in row_text for k in ["완료", "마감", "종료"]):
            continue

        # 날짜 추출
        dates = re.findall(r"\d{4}[.\-]\d{1,2}[.\-]\d{1,2}", row_text)
        parsed = [_parse_ymd(d) for d in dates]
        parsed = [d for d in parsed if d]
        deadline = max(parsed) if parsed else (today + timedelta(days=60)).isoformat()

        if not _is_active(deadline):
            continue

        href = link["href"]
        url = _clean_url(href, base)
        key = re.sub(r"\s+", "", title.lower())
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "id":          _md5(org, title),
            "title":       title[:100],
            "org":         org,
            "cat":         "ship_recruit",
            "deadline":    deadline,
            "url":         url,
            "src":         org,
            "desc":        "",
            "tags":        ["채용", "연구소", "조선"],
            "eligibility": _extract_eligibility(title),
        })

    return results[:15]


def scrape_ship_institutes() -> list[dict]:
    """조선·기계 관련 연구소 채용 공고 크롤링."""
    print("📡 조선/기계 연구소 채용 크롤링...")
    results: list[dict] = []

    for org, url, base in _SHIP_INSTITUTES:
        print(f"  → {org}: {url}")
        soup = fetch(url, retries=2, timeout=20)
        if not soup:
            continue
        items = _parse_institute_board(soup, org, base)
        if not items:
            items = _parse_ship_career_page(soup, org, base, org)
            for it in items:
                it["cat"] = "ship_recruit"
        if items:
            print(f"     {len(items)}건")
            results.extend(items)
        else:
            print(f"     0건")
        time.sleep(random.uniform(1.0, 2.0))

    print(f"  → 연구소 채용 합계: {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 범용 장학금 HTML 목록 파서
# ─────────────────────────────────────────────────────────────────────────────

def _parse_scholar_html(
    soup: BeautifulSoup, page_url: str, base: str, src: str
) -> list[dict]:
    """테이블/리스트 기반 장학금 HTML 페이지 범용 파서."""
    results: list[dict] = []
    seen: set[str] = set()

    # 전략 1: 테이블 행
    for tr in soup.select("table tbody tr, table tr"):
        link = tr.find("a", href=True)
        if not link:
            continue
        title = link.get_text(strip=True)
        if not title or len(title) < 4:
            continue
        row_text = tr.get_text(" ", strip=True)
        deadline = _ck_deadline(row_text)
        if not _is_active(deadline):
            continue
        url = _clean_url(link["href"], base)
        key = re.sub(r"\s+", "", title.lower())
        if key in seen:
            continue
        seen.add(key)
        cells = tr.find_all(["td", "th"])
        org = cells[-2].get_text(strip=True)[:50] if len(cells) >= 3 else "미상"
        org = org or "미상"
        results.append({
            "id":          _md5(src, title),
            "title":       title[:100],
            "org":         org,
            "cat":         _classify_scholar_sub(title, org, src),
            "deadline":    deadline,
            "url":         url,
            "src":         src,
            "desc":        "",
            "tags":        [src],
            "eligibility": _extract_eligibility(title),
        })

    # 전략 2: li/div 리스트 기반
    if not results:
        selectors = [
            "li", ".item", ".list-item", ".scholarship-item",
            ".board-list li", ".bbs-list li", "[class*='list'] li",
        ]
        for sel in selectors:
            for container in soup.select(sel):
                link = container.find("a", href=True)
                if not link:
                    continue
                title = link.get_text(strip=True)
                if not title or len(title) < 4:
                    continue
                container_text = container.get_text(" ", strip=True)
                deadline = _ck_deadline(container_text)
                if not _is_active(deadline):
                    continue
                url = _clean_url(link["href"], base)
                key = re.sub(r"\s+", "", title.lower())
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "id":          _md5(src, title),
                    "title":       title[:100],
                    "org":         "미상",
                    "cat":         _classify_scholar_sub(title, "", src),
                    "deadline":    deadline,
                    "url":         url,
                    "src":         src,
                    "desc":        "",
                    "tags":        [src],
                    "eligibility": _extract_eligibility(title),
                })
            if results:
                break

    return results[:30]


# ─────────────────────────────────────────────────────────────────────────────
# kstudy.com (한국장학재단 민간장학금 DB)
# ─────────────────────────────────────────────────────────────────────────────

def scrape_kstudy() -> list[dict]:
    """kstudy.com 민간/사설 장학금 크롤링."""
    print("📡 kstudy.com 크롤링...")
    _warm_up(KSTUDY_BASE)

    results: list[dict] = []
    seen: set[str] = set()
    target_pages = [
        (f"{KSTUDY_BASE}/scholarship/list",     "장학금 목록"),
        (f"{KSTUDY_BASE}/kor/scholarship/list", "장학금(KOR)"),
        (f"{KSTUDY_BASE}/scholarship/private",  "민간 장학금"),
        (f"{KSTUDY_BASE}/scholarship",          "장학금"),
        (f"{KSTUDY_BASE}/",                     "메인"),
    ]

    for url, label in target_pages:
        print(f"  → {label}: {url}")
        soup = fetch(url, retries=2, timeout=20)
        if not soup:
            continue
        items = _parse_scholar_html(soup, url, KSTUDY_BASE, "kstudy.com")
        for item in items:
            if item["id"] not in seen:
                seen.add(item["id"])
                results.append(item)
        if items:
            print(f"     {len(items)}건")
            break  # 첫 번째 유효 페이지에서 종료

    print(f"  → kstudy.com 활성 항목: {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 장학금닷컴 (janghaggeum.com)
# ─────────────────────────────────────────────────────────────────────────────

def scrape_janghaggeum() -> list[dict]:
    """장학금닷컴 (janghaggeum.com) 크롤링."""
    print("📡 장학금닷컴 크롤링...")
    _warm_up(JANGHAGGEUM_BASE)

    results: list[dict] = []
    seen: set[str] = set()
    target_pages = [
        (f"{JANGHAGGEUM_BASE}/",                 "메인"),
        (f"{JANGHAGGEUM_BASE}/scholarship",      "장학금"),
        (f"{JANGHAGGEUM_BASE}/scholarship/list", "목록"),
        (f"{JANGHAGGEUM_BASE}/list",             "목록2"),
    ]

    for url, label in target_pages:
        print(f"  → {label}: {url}")
        soup = fetch(url, retries=2, timeout=20)
        if not soup:
            continue
        items = _parse_scholar_html(soup, url, JANGHAGGEUM_BASE, "장학금닷컴")
        for item in items:
            if item["id"] not in seen:
                seen.add(item["id"])
                results.append(item)
        if items:
            print(f"     {len(items)}건")

    print(f"  → 장학금닷컴 활성 항목: {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 잡코리아 장학금
# ─────────────────────────────────────────────────────────────────────────────

def scrape_jobkorea_scholarship() -> list[dict]:
    """잡코리아 장학금 크롤링."""
    print("📡 잡코리아 장학금 크롤링...")
    _warm_up(JOBKOREA_BASE)

    results: list[dict] = []
    seen: set[str] = set()
    target_pages = [
        (f"{JOBKOREA_BASE}/recruit/scholarship",          "장학금"),
        (f"{JOBKOREA_BASE}/recruit/gi_read/scholarship",  "장학금2"),
        (f"{JOBKOREA_BASE}/scholar",                      "장학금3"),
        (f"{JOBKOREA_BASE}/recruit/activityList",         "대외활동"),
    ]

    for url, label in target_pages:
        print(f"  → {label}: {url}")
        soup = fetch(url, retries=2, timeout=20)
        if not soup:
            continue
        items = _parse_scholar_html(soup, url, JOBKOREA_BASE, "잡코리아")
        # 잡코리아는 장학 키워드 있는 항목만 수집
        scholar_items = [
            i for i in items
            if any(k in i["title"].lower() for k in ["장학", "scholarship", "학자금"])
        ]
        for item in scholar_items:
            if item["id"] not in seen:
                seen.add(item["id"])
                results.append(item)
        if scholar_items:
            print(f"     {len(scholar_items)}건")

    print(f"  → 잡코리아 활성 항목: {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────

def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for item in items:
        key = re.sub(r"\s+", "", item["title"].lower())
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def main() -> None:
    print(f"\n🚀 크롤러 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   오늘 날짜: {date.today()} (지원 마감일 기준 필터)")
    print("─" * 56)

    all_items: list[dict] = []

    try:
        all_items += scrape_linkareer()
    except Exception as e:
        print(f"  링커리어 전체 오류: {e}")

    try:
        all_items += scrape_linkareer_scholarship()
    except Exception as e:
        print(f"  링커리어 장학금 오류: {e}")

    try:
        all_items += scrape_contestkorea()
    except Exception as e:
        print(f"  공모전코리아 전체 오류: {e}")

    try:
        all_items += scrape_contestkorea_scholar()
    except Exception as e:
        print(f"  공모전코리아 장학금 검색 오류: {e}")

    try:
        all_items += scrape_contestkorea_ship()
    except Exception as e:
        print(f"  공모전코리아 조선 검색 오류: {e}")

    try:
        all_items += scrape_kr_recruit()
    except Exception as e:
        print(f"  한국선급 전체 오류: {e}")

    try:
        all_items += scrape_thinkyou()
    except Exception as e:
        print(f"  씽유 오류: {e}")

    try:
        all_items += scrape_saramin_ship()
    except Exception as e:
        print(f"  사람인 조선 검색 오류: {e}")

    try:
        all_items += scrape_ship_companies()
    except Exception as e:
        print(f"  기업 채용페이지 오류: {e}")

    try:
        all_items += scrape_ship_institutes()
    except Exception as e:
        print(f"  연구소 채용 오류: {e}")

    # 중복 제거 + 마감일 오름차순 정렬
    all_items = _dedupe(all_items)
    all_items.sort(key=lambda x: x.get("deadline", "9999-12-31"))

    cats: dict[str, int] = {}
    for item in all_items:
        cats[item["cat"]] = cats.get(item["cat"], 0) + 1

    out = {
        "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total":   len(all_items),
        "items":   all_items,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("─" * 56)
    print(f"✅ 완료: {len(all_items)}건 (지원 가능 공고만)")
    cat_labels = {
        "ship": "조선/기계", "ship_recruit": "조선 채용/인턴",
        "ship_contest": "조선 공모전", "ship_academic": "조선 학술",
        "ship_global": "조선 해외인턴", "ship_scholar": "조선 장학금",
        "ai": "AI/IoT", "media": "영상/콘텐츠",
        "global": "해외인턴", "corp": "대기업인턴",
        "scholar": "장학금(기타)",
        "scholar_public": "국가/공공 장학금",
        "scholar_corp": "기업/사설 장학금",
        "scholar_merit": "성적우수 장학금",
        "scholar_region": "지역 장학금",
        "scholar_univ": "대학외부 장학금",
        "activity": "대외활동",
    }
    for k, v in cats.items():
        print(f"   {cat_labels.get(k, k)}: {v}건")
    print(f"   저장: {os.path.abspath(OUT_PATH)}")

    print("\n── 링크 샘플 (첫 5건) ──")
    for item in all_items[:5]:
        dl = date.fromisoformat(item["deadline"])
        dday = (dl - date.today()).days
        print(f"  [{item['cat']:18}] D-{dday:3d} | {item['title'][:40]}")
        print(f"    URL: {item['url']}")


if __name__ == "__main__":
    main()
