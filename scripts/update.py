#!/usr/bin/env python3
"""抓取各駐村資料庫的最新徵件，寫入 data/opencalls.js 供網站顯示。

只用標準函式庫。規則：
- 會進到各徵件的詳情頁抓「截止日期」（抓得到才顯示，抓不到留空）。
- 只保留「第一次看到距今 30 天內」的消息（各站多半不提供公布日期，
  以 data/seen.json 記錄每個連結第一次出現的日期來近似）。
- 截止超過 7 天的項目剔除。
- 不同來源的同一則徵件用標題相似度去重，中文來源優先保留。

用法：python3 scripts/update.py
"""
import re
import ssl
import json
import html
import datetime
import urllib.error
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "opencalls.js"
SEEN = ROOT / "data" / "seen.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
TODAY = datetime.date.today()
FRESH_DAYS = 30      # 只留第一次出現在 30 天內的消息
GRACE_DAYS = 7       # 截止超過 7 天就剔除
MAX_ITEMS = 60

MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", "ignore")
    except urllib.error.URLError as e:
        if "CERTIFICATE" not in str(e).upper():
            raise
        # 這台機器的 Python 沒裝根憑證；只讀公開頁面，退回不驗證連線
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            return r.read().decode("utf-8", "ignore")


def strip_tags(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def parse_dates(text):
    """從文字中抓出所有日期，回傳 date 物件列表。"""
    out = []
    for y, mo, d in re.findall(r"(20\d\d)[./year\-]{1,2}\s?(\d{1,2})[./month\-]{1,2}\s?(\d{1,2})", text):
        try:
            out.append(datetime.date(int(y), int(mo), int(d)))
        except ValueError:
            pass
    for d, mname, y in re.findall(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(20\d\d)", text):
        mo = MONTHS.get(mname.lower())
        if mo:
            try:
                out.append(datetime.date(int(y), mo, int(d)))
            except ValueError:
                pass
    for mname, d, y in re.findall(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)", text):
        mo = MONTHS.get(mname.lower())
        if mo:
            try:
                out.append(datetime.date(int(y), mo, int(d)))
            except ValueError:
                pass
    return out


def find_deadline(page_html):
    """在截止關鍵字附近找日期。"""
    txt = strip_tags(page_html)
    for kw in ("截止日期", "截止", "application deadline", "deadline", "apply by", "applications close"):
        for m in re.finditer(kw, txt, re.I):
            window = txt[m.end():m.end() + 120]
            ds = parse_dates(window)
            if ds:
                return ds[0]
    return None


def links(html_text, href_pattern, base="", min_len=8):
    out, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.S | re.I):
        href, text = m.group(1), strip_tags(m.group(2))
        if not re.search(href_pattern, href) or len(text) < min_len:
            continue
        url = href if href.startswith("http") else base + href
        if url in seen:
            continue
        seen.add(url)
        out.append((text[:80].rstrip() + ("…" if len(text) > 80 else ""), url))
    return out


def with_deadlines(items, src, cap):
    """並行抓每筆的詳情頁，補上截止日期。items: [(title, url)]"""
    items = items[:cap]
    def one(pair):
        t, u = pair
        try:
            dl = find_deadline(fetch(u))
        except Exception:
            dl = None
        return {"src": src, "title": t, "deadline": dl.isoformat() if dl else None, "url": u}
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(one, items))


# ── 各來源 ────────────────────────────────

def grab_moc():
    page = fetch("https://artres.moc.gov.tw/zh/calls")
    pairs = []
    seen = set()
    for m in re.finditer(r'<a href="(/zh/calls/content/[a-f0-9]+)" title="([^"]+)"', page):
        u = "https://artres.moc.gov.tw" + m.group(1)
        if u in seen:
            continue
        seen.add(u)
        pairs.append((html.unescape(m.group(2)).strip()[:80], u))
    return with_deadlines(pairs, "文化部藝術進駐網", cap=60)


def grab_airj():
    page = fetch("https://air-j.info/en/program/")
    return with_deadlines(links(page, r"/en/program/.", base="https://air-j.info"),
                          "AIR_J", cap=10)


def grab_aca():
    page = fetch("https://artistcommunities.org/directory/open-calls")
    return with_deadlines(links(page, r"/directory/open-calls/.", base="https://artistcommunities.org"),
                          "Artist Communities Alliance", cap=12)


def grab_resartis():
    page = fetch("https://resartis.org/open-calls/")
    return with_deadlines(links(page, r"/open-call/"), "Res Artis", cap=12)


def grab_transartists():
    page = fetch("https://www.transartists.org/en/call-artists")
    out = []
    # 條目結構：<h3>標題</h3> … 區塊內有外部連結與 Deadline 文字
    blocks = re.split(r"<h3[^>]*>", page)[1:]
    for b in blocks[:15]:
        title = strip_tags(b.split("</h3>")[0])[:80]
        if len(title) < 8:
            continue
        link = re.search(r'href="(https?://(?!www\.transartists)[^"]+)"', b)
        dl = None
        dm = re.search(r"[Dd]eadline:?\s*([^<]{4,60})", b)
        if dm:
            ds = parse_dates(dm.group(1))
            dl = ds[0].isoformat() if ds else None
        out.append({"src": "TransArtists", "title": title,
                    "deadline": dl, "url": link.group(1) if link else "https://www.transartists.org/en/call-artists"})
    return out


def grab_eflux():
    # 列表資料内嵌在頁面 JSON（含公布日期），涵蓋近期封存、不只當天
    page = fetch("https://www.e-flux.com/announcements")
    trips = re.findall(
        r'\\"url\\":\\"(/announcements/\d+/[^"\\\\]*)\\",\\"date\\":\\"(20[0-9-]+)\\",\\"title\\":\\"([^"\\\\]{8,120})\\"',
        page)
    out, seen = [], set()
    for path, date, title in trips:
        if path in seen or not re.search(r"residen|open call|fellowship|call for", title, re.I):
            continue
        seen.add(path)
        out.append({"src": "e-flux", "title": html.unescape(title)[:80],
                    "deadline": None, "published": date,
                    "url": "https://www.e-flux.com" + path})
    return out[:10]


def grab_zippy():
    out = []
    # RSS（近期文章、含發布日）＋ deadline 頁
    try:
        rss = fetch("https://www.zippyframes.com/news?format=feed&type=rss")
        for t, u, d in re.findall(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>", rss, re.S):
            t = html.unescape(strip_tags(t))
            if not re.search(r"residen|open call", t, re.I):
                continue
            pub = None
            pm = re.match(r"\w+, (\d{1,2}) (\w{3}) (\d{4})", d.strip())
            if pm:
                mo = MONTHS.get({"jan":"january","feb":"february","mar":"march","apr":"april","may":"may","jun":"june",
                                 "jul":"july","aug":"august","sep":"september","oct":"october","nov":"november","dec":"december"}[pm.group(2).lower()])
                pub = datetime.date(int(pm.group(3)), mo, int(pm.group(1))).isoformat()
            out.append({"src": "Zippy Frames", "title": t[:80], "deadline": None, "published": pub, "url": u.strip()})
    except Exception:
        pass
    try:
        page = fetch("https://www.zippyframes.com/festivals/next-deadlines")
        for t, u in links(page, r"/(news|festivals)/.", base="https://www.zippyframes.com"):
            if re.search(r"residen|open call", t, re.I):
                out.append({"src": "Zippy Frames", "title": t, "deadline": None, "url": u})
    except Exception:
        pass
    return out[:8]


def grab_artconnect():
    # Next.js SSR 資料：含類型、截止日與公布日期
    out = []
    for pageno in (1, 2, 3):
        url = "https://www.artconnect.com/opportunities" + (f"?page={pageno}" if pageno > 1 else "")
        try:
            page = fetch(url)
        except Exception:
            break
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
        if not m:
            break
        try:
            data = json.loads(m.group(1))["props"]["pageProps"]["opportunities"]["data"]
        except (KeyError, json.JSONDecodeError):
            break
        if not data:
            break
        for o in data:
            if o.get("type") != "ART_RESIDENCY":
                continue
            place = "、".join(x for x in (o.get("city"), o.get("country")) if x)
            title = (o.get("title") or "")[:70] + (f"（{place}）" if place else "")
            out.append({
                "src": "ArtConnect", "title": title,
                "deadline": (o.get("deadline") or "")[:10] or None,
                "published": (o.get("createdAt") or "")[:10] or None,
                "url": "https://www.artconnect.com/opportunity/" + o["id"],
            })
    return out[:12]


def grab_stupin():
    page = fetch("https://stupin.org/press")
    return [{"src": "STUPIN", "title": t, "deadline": None, "url": u}
            for t, u in links(page, r"/stupin-press/.", min_len=6)][:8]


def grab_artemperor():
    page = fetch("https://artemperor.tw/tidbits")
    out = []
    for m in re.finditer(r'<a href="(https://artemperor\.tw/tidbits/\d+)">\s*<h2>([^<]+)</h2>', page):
        u, t = m.group(1), html.unescape(m.group(2)).strip()
        if not re.search(r"駐村|進駐|徵件|徵選|open ?call|residen", t, re.I):
            continue
        # 條目附近的「日期：… ~ YYYY-MM-DD」當截止參考
        tail = page[m.end():m.end() + 300]
        dm = re.search(r"~\s*(20\d\d-\d\d-\d\d)", tail)
        out.append({"src": "非池中", "title": t[:80], "deadline": dm.group(1) if dm else None, "url": u})
    return out[:10]


# ── 過濾、去重、輸出 ─────────────────────────

# 判斷是否為「駐村徵件」：要有駐村關鍵字，且不是展覽/競賽/導覽雜訊
RESIDENCY_KW = re.compile(
    r"駐村|進駐|駐地|駐留|residen|artist[- ]in[- ]residence|\bair\b|retreat|coliving|studio",
    re.I)
NON_RESIDENCY_KW = re.compile(
    r"個展|聯展|雙個展|開幕|exhibition|competition|競圖|onchain|nft|"
    r"suggested (artists|countries|cities)",
    re.I)

def is_residency(title):
    return bool(RESIDENCY_KW.search(title)) and not NON_RESIDENCY_KW.search(title)


def tokens(title):
    t = re.sub(r"^\[[^\]]*\]", "", title).lower()
    latin = set(re.findall(r"[a-z0-9]{3,}", t))
    cjk = re.sub(r"[^一-鿿]", "", t)
    grams = {cjk[i:i + 2] for i in range(len(cjk) - 1)}
    return latin | grams


def dedupe(items):
    kept = []
    for it in items:
        sig = tokens(it["title"])
        dup = False
        for k in kept:
            ksig = k["_sig"]
            inter = len(sig & ksig)
            if inter and inter / max(1, min(len(sig), len(ksig))) >= 0.6:
                dup = True
                break
        if not dup:
            it["_sig"] = sig
            kept.append(it)
    for k in kept:
        k.pop("_sig", None)
    return kept


def main():
    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}
    all_items = []
    # 中文/官方來源在前，去重時優先保留
    for fn in (grab_moc, grab_artemperor, grab_stupin, grab_airj, grab_transartists,
               grab_aca, grab_artconnect, grab_eflux, grab_zippy, grab_resartis):
        try:
            got = [it for it in fn() if is_residency(it["title"])]
            all_items += got
            print(f"  {fn.__name__}: {len(got)} 筆")
        except Exception as e:
            print(f"  {fn.__name__} 失敗：{e}")

    fresh_cut = TODAY - datetime.timedelta(days=FRESH_DAYS)
    grace_cut = TODAY - datetime.timedelta(days=GRACE_DAYS)
    items = []
    for it in dedupe(all_items):
        first = seen.get(it["url"]) or TODAY.isoformat()
        seen[it["url"]] = first
        # 有真實公布日期就用它判斷新舊，否則用首見日近似
        basis = (it.pop("published", None) or first)[:10]
        if datetime.date.fromisoformat(basis) < fresh_cut:
            continue
        if it["deadline"] and datetime.date.fromisoformat(it["deadline"]) < grace_cut:
            continue
        it["_first"] = basis
        items.append(it)

    far = datetime.date(2099, 1, 1).isoformat()
    def group(x):  # 0=未截止 1=無日期 2=剛截止
        if not x["deadline"]:
            return 1
        return 0 if x["deadline"] >= TODAY.isoformat() else 2
    # 公布（首見）日期新的在前；同日內未截止的先、依截止日近到遠
    items.sort(key=lambda x: (group(x), x["deadline"] or far))
    items.sort(key=lambda x: x["_first"], reverse=True)
    for it in items:
        it.pop("_first", None)
    items = items[:MAX_ITEMS]

    SEEN.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
    payload = {
        "updatedAt": TODAY.isoformat(),
        "source": "自動抓取：文化部藝術進駐網、非池中、STUPIN、AIR_J、TransArtists、ACA、e-flux、Zippy Frames、Res Artis（僅列近一個月內出現的消息）",
        "items": items,
    }
    OUT.write_text(
        "// 由 scripts/update.py 自動產生，勿手動編輯\nwindow.OPENCALLS = "
        + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"完成：{len(items)} 筆徵件 → {OUT}")


if __name__ == "__main__":
    main()
