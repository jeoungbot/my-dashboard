#!/usr/bin/env python3
"""
공모전·인턴십 자동 크롤러
Sources: linkareer.com, contestkorea.com
Output : ../data.json

실행:
    pip install -r requirements.txt
    python crawler.py
"""

import json, re, time, os, hashlib
from datetime import datetime, date
from typing import Optional
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

# ── 설정 ─────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data.json")

# ── 유틸 ──────────────────────────────────────────────────────────────────────

def fetch(url: str) -> Optional[BeautifulSoup]:
    """URL을 가져와 BeautifulSoup 반환 (실패 시 None)"""
    try:
        time.sleep(1.5)  # 서버 부하 방지
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        # 인코딩 자동 감지
        r.encoding = r.apparent_encoding or "utf-8"
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"    ⚠ 실패: {url}  ({e})")
        return None


def make_id(*parts: str) -> str:
    return hashlib.md5("_".join(str(p) for p in parts).encode()).hexdigest()[:12]


def parse_date(text: str) -> Optional[str]:
    """한국어/숫자 날짜를 YYYY-MM-DD 로 변환"""
    if not text:
        return None
    text = re.sub(r"[~\(\)까지마감접수기간년월일]", " ", text).strip()

    # YYYY.MM.DD 또는 YYYY-MM-DD
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"

    # MM.DD (올해 또는 내년 추정)
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})", text)
    if m:
        today = date.today()
        mo, d = int(m.group(1)), int(m.group(2))
        y = today.year
        try:
            if date(y, mo, d) < today:
                y += 1
            return f"{y}-{mo:02d}-{d:02d}"
        except ValueError:
            pass

    try:
        return dateparser.parse(text, dayfirst=False).strftime("%Y-%m-%d")
    except Exception:
        return None


def classify(title: str, desc: str = "", hint: str = "") -> str:
    """항목 카테고리 자동 분류"""
    t = (title + " " + desc + " " + hint).lower()

    if any(k in t for k in ["조선", "기계", "선박", "해양", "플랜트", "lng", "offshore",
                              "ship", "marine", "금속", "재료", "기구", "조함"]):
        return "ship"
    if any(k in t for k in ["ai", "iot", "인공지능", "딥러닝", "머신러닝", "데이터",
                              "알고리즘", "소프트웨어", "앱 개발", "해커톤", "sw개발",
                              "it 공모", "코딩", "정보통신", "클라우드", "빅데이터"]):
        return "ai"
    if any(k in t for k in ["영상", "콘텐츠", "ucc", "사진", "영화", "광고", "미디어",
                              "방송", "유튜브", "숏폼", "다큐", "크리에이터"]):
        return "media"
    if any(k in t for k in ["해외", "글로벌", "global", "overseas", "무역관", "해외인턴"]):
        return "global"
    if any(k in t for k in ["인턴"]):
        return "corp"
    if any(k in t for k in ["장학", "scholarship", "장학금", "지원금", "학자금"]):
        return "scholar"
    # 서포터즈, 대외활동 등
    return "activity"


def is_valid_deadline(deadline: Optional[str]) -> bool:
    """마감일이 유효하고 아직 지나지 않았는지 확인"""
    if not deadline:
        return False
    try:
        dl = date.fromisoformat(deadline)
        return dl >= date.today()
    except ValueError:
        return False


# ── 링커리어 크롤러 ────────────────────────────────────────────────────────────

def scrape_linkareer_list(url: str, hint: str = "") -> list[dict]:
    """링커리어 목록 페이지 하나를 파싱"""
    items = []
    soup = fetch(url)
    if not soup:
        return items

    # 1) Next.js __NEXT_DATA__ 에서 JSON 추출 (가장 신뢰도 높음)
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            data = json.loads(tag.string)
            props = data.get("props", {}).get("pageProps", {})

            # 여러 가능한 키 이름 시도
            raw = (
                props.get("activities")
                or props.get("activityList")
                or props.get("data", {}).get("activities")
                or props.get("list")
                or []
            )

            # 중첩 구조 처리
            if not raw:
                for v in props.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        raw = v
                        break

            for a in raw:
                item = _lk_dict_to_item(a, hint)
                if item:
                    items.append(item)

            if items:
                return items
        except Exception as e:
            print(f"    Next.js 파싱 오류: {e}")

    # 2) HTML 직접 파싱 (폴백)
    items.extend(_lk_html_fallback(soup, hint))
    return items


def _lk_dict_to_item(a: dict, hint: str = "") -> Optional[dict]:
    """링커리어 API dict → 표준 항목"""
    try:
        title = (a.get("title") or a.get("name") or "").strip()
        if not title:
            return None

        # 기관명
        org_raw = a.get("organization") or a.get("organizer") or a.get("host") or {}
        org = (org_raw.get("name") or org_raw.get("title") if isinstance(org_raw, dict)
               else str(org_raw)).strip() or "미상"

        # 마감일
        deadline_raw = (
            a.get("applicationEndDate") or a.get("endDate")
            or a.get("deadline") or a.get("closeDate") or ""
        )
        if isinstance(deadline_raw, (int, float)):
            deadline = datetime.fromtimestamp(deadline_raw / 1000).strftime("%Y-%m-%d")
        elif deadline_raw:
            deadline = str(deadline_raw)[:10]
        else:
            return None

        if not re.match(r"\d{4}-\d{2}-\d{2}", deadline):
            return None
        if not is_valid_deadline(deadline):
            return None

        # 링크
        aid = str(a.get("id") or a.get("activityId") or "")
        if not aid:
            return None
        url = f"https://linkareer.com/activity/{aid}"

        desc = (a.get("summary") or a.get("description") or a.get("shortDescription") or "")[:200].strip()

        tags = []
        for key in ("tags", "keywords", "categories"):
            for t in a.get(key, []):
                tags.append(t.get("name") or t.get("title") or t if isinstance(t, dict) else t)
        tags = [str(t).strip() for t in tags if t][:5]

        return {
            "id": f"lk_{aid}",
            "title": title,
            "org": org,
            "cat": classify(title, desc, hint),
            "deadline": deadline,
            "url": url,
            "src": "링커리어",
            "desc": desc,
            "tags": tags,
        }
    except Exception:
        return None


def _lk_html_fallback(soup: BeautifulSoup, hint: str = "") -> list[dict]:
    """링커리어 HTML 카드 직접 파싱 (폴백)"""
    items = []
    # 링커리어 카드 셀렉터 후보
    for sel in [
        "li[class*='activity']",
        "div[class*='ActivityCard']",
        "div[class*='activity-card']",
        "article",
    ]:
        cards = soup.select(sel)
        if cards:
            break
    else:
        return items

    for card in cards[:25]:
        try:
            link_el = card.find("a", href=True)
            if not link_el:
                continue
            href = link_el["href"]
            if href.startswith("/"):
                href = "https://linkareer.com" + href

            title_el = (
                card.find(class_=re.compile(r"title", re.I))
                or card.find("h3") or card.find("h4") or card.find("strong")
            )
            title = (title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)).strip()
            if not title:
                continue

            date_el = card.find(class_=re.compile(r"date|deadline|close|period", re.I))
            deadline = parse_date(date_el.get_text() if date_el else "")
            if not is_valid_deadline(deadline):
                continue

            org_el = card.find(class_=re.compile(r"org|company|host|organ", re.I))
            org = org_el.get_text(strip=True) if org_el else "미상"

            items.append({
                "id": make_id("lk", title),
                "title": title,
                "org": org,
                "cat": classify(title, "", hint),
                "deadline": deadline,
                "url": href,
                "src": "링커리어",
                "desc": "",
                "tags": [],
            })
        except Exception:
            continue
    return items


def scrape_linkareer() -> list[dict]:
    print("📡 링커리어 크롤링...")
    results = []
    sections = [
        ("https://linkareer.com/list/contest",    "공모전"),
        ("https://linkareer.com/list/scholarship", "장학금"),
        ("https://linkareer.com/list/club",        "대외활동"),
    ]
    for url, hint in sections:
        print(f"  → {hint}: {url}")
        items = scrape_linkareer_list(url, hint)
        print(f"     {len(items)}건 수집")
        results.extend(items)
    return results


# ── 공모전코리아 크롤러 ──────────────────────────────────────────────────────────

def scrape_contestkorea() -> list[dict]:
    print("📡 공모전코리아 크롤링...")
    results = []

    # 공모전코리아는 서버 렌더링 PHP 사이트
    base = "https://www.contestkorea.com"
    pages = [
        f"{base}/sub/list.php?str_1=1&int_gub_no=0",   # 전체
        f"{base}/sub/list.php?str_1=1&int_gub_no=6",   # 과학/공학
        f"{base}/sub/list.php?str_1=1&int_gub_no=5",   # IT/소프트웨어
        f"{base}/sub/list.php?str_1=1&int_gub_no=10",  # 기획/아이디어
    ]

    for url in pages:
        print(f"  → {url}")
        items = _parse_contestkorea(url, base)
        print(f"     {len(items)}건 수집")
        results.extend(items)

    return results


def _parse_contestkorea(url: str, base: str) -> list[dict]:
    items = []
    soup = fetch(url)
    if not soup:
        return items

    # 공모전코리아 목록 구조 (여러 CSS 클래스 시도)
    cards = (
        soup.select("ul.list_style1 > li")
        or soup.select(".list_area li")
        or soup.select(".cont_list li")
        or soup.select("div.list li")
        or soup.select("li.list_item")
    )

    if not cards:
        # table 구조
        for tr in soup.select("table.list_table tbody tr, table tbody tr"):
            try:
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                link_el = tr.find("a", href=True)
                if not link_el:
                    continue
                title = link_el.get_text(strip=True)
                href = link_el["href"]
                if href.startswith("/"):
                    href = base + href
                # 날짜는 td 텍스트에서 찾기
                all_text = " ".join(td.get_text() for td in tds)
                deadline = parse_date(all_text)
                if not is_valid_deadline(deadline):
                    continue
                items.append({
                    "id": make_id("ck", title),
                    "title": title,
                    "org": tds[0].get_text(strip=True) if len(tds) > 0 else "미상",
                    "cat": classify(title),
                    "deadline": deadline,
                    "url": href,
                    "src": "공모전코리아",
                    "desc": "",
                    "tags": [],
                })
            except Exception:
                continue
        return items

    for card in cards:
        try:
            link_el = card.find("a", href=True)
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            href = link_el["href"]
            if href.startswith("/"):
                href = base + href

            # 날짜: 카드 전체 텍스트에서 날짜 패턴 검색
            card_text = card.get_text(" ", strip=True)
            dates_found = re.findall(r"\d{4}[.\-]\d{1,2}[.\-]\d{1,2}", card_text)
            deadline = parse_date(dates_found[-1]) if dates_found else None
            if not is_valid_deadline(deadline):
                continue

            # 기관명
            org_el = card.find(class_=re.compile(r"org|host|sponsor|company", re.I))
            org = org_el.get_text(strip=True) if org_el else "미상"

            # 설명 (있으면)
            desc_el = card.find(class_=re.compile(r"desc|summary|sub|detail", re.I))
            desc = desc_el.get_text(strip=True) if desc_el else ""

            items.append({
                "id": make_id("ck", title),
                "title": title,
                "org": org,
                "cat": classify(title, desc),
                "deadline": deadline,
                "url": href,
                "src": "공모전코리아",
                "desc": desc[:200],
                "tags": [],
            })
        except Exception:
            continue

    return items


# ── 메인 ──────────────────────────────────────────────────────────────────────

def deduplicate(items: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for item in items:
        key = re.sub(r"\s+", "", item["title"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def main():
    print(f"\n🚀 크롤러 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("─" * 50)

    all_items = []

    # 소스별 크롤링
    try:
        lk = scrape_linkareer()
        all_items.extend(lk)
    except Exception as e:
        print(f"  링커리어 전체 오류: {e}")

    try:
        ck = scrape_contestkorea()
        all_items.extend(ck)
    except Exception as e:
        print(f"  공모전코리아 전체 오류: {e}")

    # 중복 제거
    all_items = deduplicate(all_items)

    # 마감일순 정렬
    def sort_key(item):
        try:
            return date.fromisoformat(item["deadline"])
        except Exception:
            return date(9999, 12, 31)

    all_items.sort(key=sort_key)

    # 카테고리별 통계
    cats = {}
    for item in all_items:
        cats[item["cat"]] = cats.get(item["cat"], 0) + 1

    result = {
        "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(all_items),
        "items": all_items,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("─" * 50)
    print(f"✅ 완료: {len(all_items)}건 → data.json")
    print("   카테고리:", cats)
    print(f"   저장 경로: {os.path.abspath(OUT_PATH)}")


if __name__ == "__main__":
    main()
