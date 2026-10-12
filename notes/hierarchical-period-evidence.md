# Phase 7.2｜Hierarchical clustering period evidence

## Resolution

**Period classification：A. Clearly 2022–2024。**

原報告不是只在單一位置偶然寫到2022。研究方法總覽與hierarchical正文各自明載2022–2024；正文同時交代每個月、平日／假日、逐時SNA及72個變數。附錄則提供平日與假日各自的dendrogram及趨勢圖。這是一組互相支持的證據，不能判成局部typo，也不能因目前reconstruction只有2023–2024 core metrics就改寫期間。

## Period evidence table

| Evidence | Period stated | Context | Classification | Confidence |
| --- | --- | --- | --- | --- |
| Report p.7研究方法 | 2022–2024 | 「2022至2024年間的數據」採hierarchical，平日／假日每小時建SNA | Report-specified | High |
| Report p.27 hierarchical正文 | 2022–2024 | 再次明寫2022至2024，平日／假日每小時建SNA | Report-specified | High |
| Report p.27 feature construction | 3年×月別脈絡 | 每站彙整Betweenness、Eigenvector、PageRank共72個變數 | Report-specified | High |
| Report附錄Figures 45–52 | 未在caption重寫年份 | 分別呈現平日／假日dendrogram及三種centrality的24小時群平均 | Report-specified outputs | High |
| Report p.7 general raw-data EDA | 2023–2025 | 整體租借EDA期間，不是hierarchical專屬期間 | Report-specified, different module | High |
| Report p.7 core network／accident | 2023–2024 | 核心路網與事故期間，不是hierarchical專屬期間 | Report-specified, different module | High |
| Report p.23–27 K-means | core network context；圖示2024 | 四個全期間SNA features的K-means；與hierarchical輸入設計不同 | Report-specified, different analysis | High |

## Why this is not a typo

1. 2022–2024在方法總覽與hierarchical正文至少出現兩次。
2. Hierarchical有自己獨立的資料建構：平日與假日分開、每小時建SNA、每站72維；不是沿用K-means的四個全期間features。
3. 附錄Figures 45–52與這個設計一致：兩個dendrogram，以及Betweenness／Eigenvector／PageRank的24小時趨勢圖。
4. 因此2023–2024 core network與2022–2024 hierarchical可以同時成立；前者不能覆蓋後者。

## 2022 raw availability

Source index以CP950解析後，2022/01–12共12個月份各有一個官方ZIP URL、無缺月、無重複月；既有2026/09/12 HEAD inventory顯示12個URL均回應HTTP 200。

本階段沒有下載全部12個月，只抽取邊界月份做內容驗證：

| Sample | ZIP bytes | Raw CSV rows incl. header | Header | Width | Encoding | Parser EOF result |
| --- | ---: | ---: | --- | ---: | --- | --- |
| 2022/01 | 16,134,695 | 1,371,396 | standard 6-column header | 6 | UTF-8 strict | 1,371,395 records；`v1_6col`；0 warnings |
| 2022/12 | 30,542,838 | 2,628,741 | standard 6-column header | 6 | UTF-8 strict | 2,628,740 records；`v1_6col`；0 warnings |

兩個sample皆完整讀至EOF、欄寬固定、第6欄是日期，沒有車種欄或非法UTF-8。這證明年初／年末sample與既有parser contract相容；**不能據此聲稱其餘10個月已逐檔驗證**。Raw ZIP與詳細audit保留在Git忽略的`data/raw/`及`data/interim/`。

## Availability conclusion

- **Observed**：官方source index及HEAD evidence支持2022全年raw files可取得。
- **Observed in sampled raw data**：2022/01與12為6欄＋header的`v1_6col`，既有parser可完整讀取。
- **Unverified**：2022/02–11的實際header、encoding、全檔schema與資料品質尚未內容掃描。
- **Implication**：2022 reconstruction在來源層具可行性，但仍須先做12個月schema gate、cleaning、OD eligibility、逐時平假日OD及SNA；目前不能直接執行report-complete hierarchical clustering。

## Phase 7.3 analyst reconstruction decision

Phase 7.2的source finding不變：原報告有多項證據支持2022–2024，不能宣稱原文明確使用2023–2024。

其後分析者在Phase 7.3明確決定把原報告的期間差異視為內部不一致／筆誤，並選擇與核心network一致的2023–2024作為**Analyst reconstruction decision**。本專案因此不補跑2022，而產生2023–2024 variant的weekday／holiday 72-feature matrices。這項選擇讓重建可接續既有core OD，但限制是正式hierarchical結果只能比較方法與描述性輪廓，不能宣稱完全重現原報告2022–2024母體。
