# residency — 全球藝術駐村資料庫網站

一個單頁靜態網站，整理全球 120 個藝術駐村計畫（分類方式沿用「駐村列表.xlsx」：名稱、單位、國家城市、期間、金額、名額、資格、截止、網站、備註），外加自動抓取最新徵件的腳本。

## 用法

- **看網站**：直接用瀏覽器打開 `index.html`，不用架伺服器。
- **更新最新徵件**：
  ```bash
  python3 scripts/update.py
  ```
  只用 Python 標準函式庫，不用裝套件。腳本會抓十個來源（文化部藝術進駐網、非池中、STUPIN、AIR_J、TransArtists、Artist Communities Alliance、ArtConnect、e-flux、Zippy Frames、Res Artis）寫進 `data/opencalls.js`，重新整理網頁就會看到。規則：
  - 每筆會進詳情頁抓截止日期，標題格式 `[來源-YYYY/MM/DD截止] 名稱`。
  - 只保留駐村徵件（展覽、競圖、講座自動剔除）。
  - 只留「第一次出現在 30 天內」的消息（首見日記在 `data/seen.json`），截止超過 7 天剔除；7 天內首見的標 NEW。
  - 跨來源用標題相似度去重，中文來源優先保留。
  - 徵件比對到現有卡片時，自動更新該卡的「最近截止」；比對不到的寫進 `data/uncarded.md`，GitHub Actions 會開 issue「待補卡片清單」提醒人工補卡。
  - 每月 1 日另有連結檢查（`linkcheck.py`），官網失效的會開 issue「官網連結失效清單」。

## 檔案結構

| 檔案 | 內容 |
|------|------|
| `index.html` | 網站本體（篩選、搜尋、排序都在這） |
| `scripts/linkcheck.py` | 每月檢查卡片官網連結是否失效 |
| `data/residencies.js` | 主資料集：120 筆駐村，人工整理，欄位對齊原 Excel |
| `data/seen.json` | 每個徵件連結第一次出現的日期（給 30 天過濾用） |
| `data/opencalls.js` | 最新徵件，由 `scripts/update.py` 自動產生 |
| `scripts/update.py` | 抓取腳本 |
| `.github/workflows/update.yml` | GitHub Actions 排程（推上 GitHub 後每週自動更新） |

## 資料原則

- 徵件月份是「常態週期」整理，每年會變，`deadlineNote` 一律以官網為準。
- 查不到的欄位寫「未公告」，不猜。
- 「評價」不自建評分：每張卡片的「查評價」連到 Google 搜尋該駐村的 review／經驗談，卡片上另用可查證的訊號輔助判斷（創立年份、補助形態、名額）。歐美駐村可再查 [Reviewed by Artists](https://www.reviewedbyartists.com)。

## 讓它「全自動更新」

三選一，由淺入深：

1. **手動**：想到就跑一次 `python3 scripts/update.py`。
2. **本機排程**：crontab 加一行，例如每週一早上 9 點：
   ```
   0 9 * * 1 cd /Users/chinghsiang/Desktop/Brain/residency && /usr/bin/python3 scripts/update.py
   ```
3. **GitHub Pages（建議）**：把這個資料夾推成 GitHub repo、開 Pages，`update.yml` 會每週一自動抓資料並 commit，網站就是全自動更新，手機也能看。

## 新增駐村

直接在 `data/residencies.js` 加一筆物件（欄位照現有格式），存檔重整即可。`deadlineMonth` 填常態截止月份（1–12），不定期填 0。

## 已知限制

- 截止日期靠關鍵字附近的日期解析，各站格式不一，抓不到就留空（顯示只有來源沒有日期）。
- theApro（韓國）與 NYFA（美國）擋爬蟲或連不上，只放在頁尾連結，沒進自動抓取。
- Threads（@opencallfinder）與 Instagram（@opencallforartists_）的貼文要登入後由 JS 載入，自動抓取拿不到內容，同樣只放頁尾連結，需要手動點進去看。
- e-flux 抓的是頁面內嵌的近期公告資料（含公布日期，不只當天）；Zippy Frames 走 RSS＋deadline 頁。兩者都只在近期列表出現駐村關鍵字時才有結果，0 筆是正常的。
- ArtConnect 走 Next.js SSR 資料，含真實公布日期與截止日，是外語來源中品質最好的。
- 這台機器的 Python 沒裝根憑證，腳本在驗證失敗時會退回不驗證的 HTTPS 連線（只讀公開頁面）。若要移除這個 fallback，先安裝 certifi 或執行 Python 附的 `Install Certificates.command`。
- 公布日期多數網站不提供，用「第一次被腳本看到的日期」近似；第一次執行時全部項目都算新的。
