#!/usr/bin/env python3
"""
공모전·인턴십 자동 크롤러 v3
Sources  : linkareer.com, contestkorea.com
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

    # OrderedDict 방식으로 헤더 순서 보장
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
        # 이후 요청은 same-site로 표시
        s.headers["Sec-Fetch-Site"] = "same-origin"
        s.headers["Referer"] = base_url + "/"
    except Exception as e:
        print(f"  ⚠  워밍업 실패: {e}")


def fetch(url: str, retries: int = 3) -> Optional[BeautifulSoup]:
    """재시도 + 지수 백오프 포함 fetch."""
    s = _session()
    for attempt in range(retries):
        wait = random.uniform(2.0, 3.5) + attempt * 2.5
        time.sleep(wait)
        try:
            r = s.get(url, timeout=30)
            # 봇 차단 응답
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

    # YYYY-MM-DD / YYYY.MM.DD
    m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # YY.MM.DD (두 자리 연도 → 2000+)
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
    단일 날짜인 경우 그 날짜를 반환.
    """
    # YY.MM.DD~YY.MM.DD
    m = re.search(
        r"(\d{2})[.\-](\d{2})[.\-](\d{2})\s*~\s*(\d{2})[.\-](\d{2})[.\-](\d{2})",
        text
    )
    if m:
        y = int(m.group(4)) + 2000
        return f"{y}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"

    # YYYY.MM.DD~YYYY.MM.DD
    m = re.search(
        r"20\d{2}[.\-]\d{2}[.\-]\d{2}\s*~\s*(20\d{2})[.\-](\d{2})[.\-](\d{2})",
        text
    )
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    return _parse_ymd(text)


def _is_active(deadline: Optional[str]) -> bool:
    """지원 마감일이 오늘 이상인지 확인 (오늘 = 지원 가능)."""
    if not deadline:
        return False
    try:
        dl = date.fromisoformat(deadline)
        today = date.today()
        # 마감일이 오늘 포함 이후여야 함
        if dl < today:
            return False
        # 너무 먼 미래(5년 초과)는 날짜 파싱 오류로 간주
        if (dl - today).days > 365 * 5:
            return False
        return True
    except ValueError:
        return False


def _classify(title: str, org: str = "", hint: str = "") -> str:
    t = f"{title} {org} {hint}".lower()
    h = hint.lower()

    # 조선/기계: "기계" 단독 사용 시 "자기계발" 오분류 → 복합어만 허용
    if any(k in t for k in [
        "조선", "선박", "해양", "플랜트", "lng", "ship", "marine", "offshore",
        "기계공학", "기계설계", "기계시스템", "기계항공", "금속공학", "재료공학",
        "용접", "한국선급", "kriso", "dsme",
    ]):
        # 페이지 유형에 따라 서브카테고리 결정
        if any(k in h for k in ["공모전", "경진", "공모전코리아"]):
            return "ship_contest"
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
        return "scholar"

    return "activity"


def _clean_url(href: str, base: str = "") -> str:
    """상대 URL → 절대 URL."""
    href = (href or "").strip()
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return base + href
    return base + "/" + href


# ─────────────────────────────────────────────────────────────────────────────
# 링커리어
# ─────────────────────────────────────────────────────────────────────────────
#
# 전략: __NEXT_DATA__ → props.pageProps.__APOLLO_STATE__
#       키 "Activity:숫자" → {id, title, organizationName, recruitCloseAt(ms)}
#
# recruitCloseAt = 지원 마감 유닉스 타임스탬프(밀리초) → 지원 마감일 기준 필터

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
        # "Activity:숫자" 형태만 (ActivityFile, ActivityImage 등 제외)
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

        # recruitCloseAt = 지원 마감일(밀리초)
        close_ms = val.get("recruitCloseAt")
        if not close_ms:
            return None

        deadline = datetime.fromtimestamp(int(close_ms) / 1000).strftime("%Y-%m-%d")

        # 지원 마감일 기준 필터 (이미 지난 공고 제외)
        if not _is_active(deadline):
            return None

        url = f"{LINKAREER_BASE}/activity/{aid}"
        cat = _classify(title, org, hint)

        return {
            "id":       f"lk_{aid}",
            "title":    title,
            "org":      org,
            "cat":      cat,
            "deadline": deadline,
            "url":      url,       # 반드시 해당 공고 직접 링크
            "src":      "링커리어",
            "desc":     "",
            "tags":     [],
        }
    except Exception:
        return None


def scrape_linkareer() -> list[dict]:
    print("📡 링커리어 크롤링...")
    _warm_up(LINKAREER_BASE)

    # 장학금(/list/scholarship)은 링커리어 서버 자체 504 상태 → 제외
    pages = [
        (f"{LINKAREER_BASE}/list/contest", "공모전"),
        (f"{LINKAREER_BASE}/list/club",    "대외활동"),
        (f"{LINKAREER_BASE}/list/intern",  "인턴십"),
    ]

    results = []
    for url, hint in pages:
        print(f"  → {hint}: {url}")
        soup = fetch(url)
        if not soup:
            print(f"     ✖ 수집 실패 — 다음 페이지로 진행")
            continue

        # 봇 차단 여부 진단 (본문에 Access Denied 문자열 포함 시)
        page_text = soup.get_text()
        if "access denied" in page_text.lower() or "captcha" in page_text.lower():
            print(f"     ⚠  봇 차단 응답 감지 (Access Denied/Captcha)")
            print(f"        응답 미리보기: {page_text[:200]!r}")
            continue

        # __NEXT_DATA__ 존재 여부로 정상 응답 확인
        nd_tag = soup.find("script", id="__NEXT_DATA__")
        if not nd_tag:
            print(f"     ⚠  __NEXT_DATA__ 없음 — 비정상 응답 (HTTP 차단 가능성)")
            print(f"        본문 미리보기: {soup.get_text()[:200]!r}")
            continue

        items = _apollo_items(soup, hint)
        print(f"     {len(items)}건 (지원 마감일 기준, 활성)")
        results.extend(items)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 한국선급 (KR)
# ─────────────────────────────────────────────────────────────────────────────
#
# 구조: table.board_list tbody tr > td[num, title, file, 등록일, 조회]
# 한계: 개별 공고 링크가 JS onclick("frmView(...)") → 리스트 페이지 URL 사용
# 마감일: 등록일 + 180일 추정 (실제 마감일 비공개)

def scrape_kr_recruit() -> list[dict]:
    """한국선급(KR) 채용공고 크롤링 (정적 HTML, 등록일 180일 이내)."""
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
        if len(tds) < 4:
            continue
        title = tds[1].get_text(strip=True)
        reg_str = tds[3].get_text(strip=True)
        if not title or not reg_str:
            continue

        reg_date = _parse_ymd(reg_str)
        if not reg_date:
            continue

        reg = date.fromisoformat(reg_date)
        # 등록일이 180일을 초과한 공고는 오래된 것으로 제외
        if (today - reg).days > 180:
            continue

        # 실제 마감일 불명 → 등록일로부터 180일을 추정 마감일로 설정
        deadline = (reg + timedelta(days=180)).isoformat()

        results.append({
            "id":       _md5("kr", title),
            "title":    title,
            "org":      "한국선급(KR)",
            "cat":      "ship_recruit",
            "deadline": deadline,
            "url":      KR_RECRUIT_URL,
            "src":      "한국선급",
            "desc":     f"등록일: {reg_date}",
            "tags":     ["채용", "조선"],
        })

    print(f"  {len(results)}건")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 공모전코리아
# ─────────────────────────────────────────────────────────────────────────────
#
# 구조:
#   li.imminent  → div.title > a (제목+링크), ul.host (기관·날짜)
#   li with div.img_area + div.txt_area → 카드형 (제목·날짜·기관)
#
# 주의: 메인 목록은 JS 렌더링 → 정적 크롤링으로는 위 두 타입만 수집 가능
#
# 마감일: "26.05.16~27.01.16" 범위의 뒤 날짜(지원 마감일) 사용

_CK_BCODES: dict[str, str] = {
    "030310001": "학문·과학·IT",
    "030610001": "미술·디자인·웹툰",
    "030210001": "네이밍·슬로건",
    "030110001": "문학·문예",
    "030410001": "사진·영상·영화제",
    "030510001": "아이디어·건축·창업",
    "030910001": "스포츠",
}


def scrape_contestkorea() -> list[dict]:
    print("📡 공모전코리아 크롤링...")
    _warm_up(CONTESTKOREA_BASE)
    results = []

    for bcode, label in _CK_BCODES.items():
        url = f"{CONTESTKOREA_BASE}/sub/list.php?int_gbn=1&Txt_bcode={bcode}"
        print(f"  → {label}: {url}")
        items = _ck_page(url, bcode)
        print(f"     {len(items)}건")
        results.extend(items)

    return results


def _ck_page(url: str, bcode: str) -> list[dict]:
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

    # ── 타입 1: li.imminent ────────────────────────────────────────────────
    for li in soup.select("li.imminent"):
        title_div = li.find("div", class_="title")
        if not title_div:
            continue
        link = title_div.find("a", href=True)
        if not link:
            continue

        # category span 제거 후 제목 추출
        for sp in link.find_all("span", class_="category"):
            sp.decompose()
        txt_span = link.find("span", class_="txt")
        title = (txt_span.get_text(strip=True) if txt_span
                 else link.get_text(strip=True)).strip()
        if not title:
            continue

        href = link["href"]
        # 직접 링크를 절대 URL로 변환
        clean_href = _ck_clean_href(href, bcode)

        # 날짜: ul.host 내 텍스트 또는 li 전체 텍스트
        host_ul  = li.find("ul", class_="host")
        deadline = _ck_deadline(host_ul.get_text(" ", strip=True) if host_ul else "")
        if not deadline:
            deadline = _ck_deadline(li.get_text(" ", strip=True))

        if not _is_active(deadline):
            continue

        # 기관: ul.host > li.icon_2 (주관자)
        org = "미상"
        if host_ul:
            for hli in host_ul.find_all("li"):
                cls = " ".join(hli.get("class", []))
                txt = hli.get_text(strip=True)
                if "icon_2" in cls or ("주최" in txt and "." in txt):
                    org = re.sub(r"^(주최|주관)\s*[.]\s*", "", txt).strip() or "미상"
                    break

        add({
            "id":       _md5("ck", title),
            "title":    title,
            "org":      org,
            "cat":      _classify(title, org, "공모전코리아"),
            "deadline": deadline,
            "url":      clean_href,
            "src":      "공모전코리아",
            "desc":     "",
            "tags":     [],
        })

    # ── 타입 2: 카드형 (div.txt_area) ─────────────────────────────────────
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
        href = _ck_clean_href(link["href"], bcode)

        add({
            "id":       _md5("ck", title),
            "title":    title,
            "org":      org,
            "cat":      _classify(title, org, "공모전코리아"),
            "deadline": deadline,
            "url":      href,
            "src":      "공모전코리아",
            "desc":     "",
            "tags":     [],
        })

    return items


def _ck_clean_href(href: str, bcode: str) -> str:
    """
    긴 쿼리 파라미터 URL을 최소한의 깔끔한 URL로 정리.
    str_no 추출 후 표준 view.php URL 반환.
    """
    m = re.search(r"str_no=(\w+)", href)
    if m:
        str_no = m.group(1)
        return (
            f"{CONTESTKOREA_BASE}/sub/view.php"
            f"?int_gbn=1&Txt_bcode={bcode}&str_no={str_no}"
        )
    # str_no가 없으면 절대 URL 변환
    return _clean_url(href, CONTESTKOREA_BASE)


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
        all_items += scrape_contestkorea()
    except Exception as e:
        print(f"  공모전코리아 전체 오류: {e}")

    try:
        all_items += scrape_kr_recruit()
    except Exception as e:
        print(f"  한국선급 전체 오류: {e}")

    # 중복 제거 + 마감일 오름차순 정렬
    all_items = _dedupe(all_items)
    all_items.sort(key=lambda x: x.get("deadline", "9999-12-31"))

    # 카테고리 통계
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
        "global": "해외인턴", "corp": "대기업인턴", "scholar": "장학금",
        "activity": "대외활동",
    }
    for k, v in cats.items():
        print(f"   {cat_labels.get(k, k)}: {v}건")
    print(f"   저장: {os.path.abspath(OUT_PATH)}")

    # 샘플 출력 (URL 검증용)
    print("\n── 링크 샘플 (첫 5건) ──")
    for item in all_items[:5]:
        dl = date.fromisoformat(item["deadline"])
        dday = (dl - date.today()).days
        print(f"  [{item['cat']:8}] D-{dday:3d} | {item['title'][:40]}")
        print(f"    URL: {item['url']}")


if __name__ == "__main__":
    main()
