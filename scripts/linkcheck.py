#!/usr/bin/env python3
"""檢查卡片資料庫（data/residencies.js）裡所有官網連結是否還活著。

失效清單寫進 data/brokenlinks.md（給 GitHub Actions 開 issue 用）；
全部正常時該檔為空。只用標準函式庫。
用法：python3 scripts/linkcheck.py
"""
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "data" / "residencies.js"
OUT = ROOT / "data" / "brokenlinks.md"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def check(url):
    req = urllib.request.Request(url, headers=UA)
    for ctx in (None, ssl._create_unverified_context()):
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                return url, r.status, None
        except urllib.error.HTTPError as e:
            # 401/403/999 常是擋爬蟲或登入牆，不代表網站掛了，不列失效
            if e.code in (401, 403, 405, 999):
                return url, e.code, None
            err = f"HTTP {e.code}"
        except Exception as e:
            err = str(e)[:80]
    return url, None, err


def main():
    src = CARDS.read_text(encoding="utf-8")
    urls = sorted(set(re.findall(r'website: "(https?://[^"]+)"', src)))
    print(f"檢查 {len(urls)} 個官網連結…")
    with ThreadPoolExecutor(10) as ex:
        results = list(ex.map(check, urls))
    broken = [(u, err) for u, st, err in results if err]
    if broken:
        lines = ["每月自動連結檢查：下列卡片官網連不上，請確認是否搬家或關站：", ""]
        for u, err in broken:
            names = re.findall(r'\{ name: "(.+?)",(?:(?!\{ name:).)*?website: "' + re.escape(u) + '"', src, re.S)
            label = "、".join(names[:3]) or "（未知卡片）"
            lines.append(f"- {label}：{u}（{err}）")
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        OUT.write_text("", encoding="utf-8")
    print(f"失效 {len(broken)} 個 → {OUT if broken else '（全部正常）'}")
    for u, err in broken:
        print(f"  ✗ {u}  {err}")


if __name__ == "__main__":
    main()
