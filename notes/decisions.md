# 方法與決策紀錄

日期：2026-09-12。R、S、W 的定義與來源指紋見 [來源清單](../references/README.md)。R p. 表示主要 PDF 實體頁碼。

## 紀錄規則

- **Report-specified**：原報告明文／公式／圖表呈現的內容；「報告有記載」不等於已由原始資料重算或已確認方法正確。
- **Reconstruction decision**：本次為可重現性所作選擇，須寫明理由與驗證方式；可分「已採用的管理決策」及「未執行的分析提案」。
- **Assumption**：缺少證據時暫採的假設，須標示狀態、影響及何時驗證。未決項目不能自動變成套件預設值。

第一階段尚未對任何實際資料採用分析假設。以下分析選擇多為待決；執行對應模組前補上日期、替代方案、理由、參數、證據與驗證結果，保留變更歷程。

## D00｜管理、來源與範圍（已採用）

- Report-specified：R 封面日期為民國115年1月3日；W 及 S 為輔助原件。
- Reconstruction decision：現有 `Youbike/` 直接作 Git 根目錄，不另套空的同名專案。R 作主要定位來源，S/W 補足資訊但不覆蓋矛盾。只追蹤主要 PDF 與來源摘要，較大的 Word／簡報留在本機且忽略；不刪除原件。README 持續更新，資料夾以最少 `.gitkeep` 保留。
- Reconstruction decision：原始資料不改寫、不 commit；中間表優先 Parquet，空間表優先 GeoParquet；實作及依賴逐模組新增。第一階段只做文件及本機 commit，不建立 GitHub 遠端、不執行分析。
- Assumption：無。驗證：檔案 hash、來源頁數、Git ignore／staged 清單與文件連結。
- Git狀態變更紀錄：開始時 `git status` 回報非repository；收尾時觀察到 `a5d45f0 Initial commit` 與既有origin。保留其歷史、`.gitattributes`及遠端，不推測建立者；只停止追蹤輔助原件／暫存圖。本機原件保留，舊commit仍含這些檔案，未做歷史改寫。

## D01｜資料期間與分群網絡範圍（未決）

- Report-specified：R p.7、S p.6 指 EDA 2023/01–2025/03、核心2023–2024；R p.7及27兩度寫 hierarchical 使用2022–2024。S p.7 明示 Louvain/K-means 不分平假日／小時，階層式才依平假日逐時；R p.7另提平假日獨立 SNA。
- Reconstruction decision：分別記錄全期分群、平假日網絡、逐時網絡用途，不將所有圖當成同一次運算。主研究核心期間依2023–2024規劃，但階層模組不得默認已解決2022年的衝突。
- Assumption：2022可能誤植僅為待證可能，不採用。驗證：資料涵蓋日期、可追回檔案或作者說明；若最後選2023–2024階層分析，須標為新的期間選擇。

## D02｜旅次、站點、日曆與資料清理（未決）

- Report-specified：R p.7 由借還紀錄彙成 OD，臺北市站點；R p.9 每日各小時平均借用次數。
- Reconstruction decision：M0先檢查欄位與每列粒度；再定義穩定站點鍵與來源到分析欄位映射，保留排除理由。
- Assumption：未採用。未記載事項包括站名清理、跨市起迄篩選、歷史座標、重複判斷、負時長／超長旅次、同站還車、自迴圈、缺日、借車或還車小時、時區、國定假日／補班。不可把缺資料日補成零、把相同起迄時間列全部當重複，或將現在站點直接當歷史站點。
- 驗證：全檔筆數、缺失與異常摘要、日期涵蓋、站點 join、清理前後守恆。

## D03｜方向、總流量與路徑語意（部分管理選擇已定）

- Report-specified：R p.7、12 定義 i→j 的流量與加權入／出度公式，但文字把「借車」稱 In、把「還車」稱 Out。
- Reconstruction decision：未來資料契約遵循 O→D：借出為 out、歸還為 in，明確記錄對文字錯置的修正；總加權度仍是二者之和。OD 網絡的最短路徑不直接等同實際道路軌跡。
- Assumption：自迴圈保留／移除仍未定，不以對齊舊數值決定。
- 驗證：用單一 A→B 旅次手算入出度，合計 degree 與旅次量對帳，另檢查同站還車。

## D04｜Louvain 有向實作與 Q（阻擋 M5 的未決項）

- Report-specified：R p.12–13 聲稱有向 Louvain 並列有向 Q 公式；p.16寫R套件igraph。未列函式、版本、seed、resolution、停止條件、是否先轉無向。公式中 m 的文字稱「總邊數」，與加權流量語意需區分。
- 外部查證（2026-09-12）：目前 [R igraph cluster_louvain 官方文件](https://r.igraph.org/reference/cluster_louvain.html) 的輸入圖要求無向。這只確認該函式現有契約，**不能證明原研究用過此函式、轉成無向或使用哪個版本**。
- Reconstruction decision：實作前比較可支援有向目標函數的選項，或明示加權無向投影作不同版本分析；保留選擇與 Q 定義。禁止悄悄轉圖後稱原有向實作已復原。
- Assumption：尚未選版本／套件／resolution／seed。11群與Q=0.665僅validation reference。
- 報告內部核對：p.17圖6的11個Q貢獻加總為0.66574，不等同正文顯示的0.665；截位或不同執行等原因未確認，保留兩者。
- 驗證：小圖手算Q、多seed穩定性、總權重與degree一致，記錄群數及差異；不反覆找seed湊數。

## D05｜Betweenness（未決）

- Report-specified：R p.13 最短路徑介數公式，但文字以「流量」解釋 sigma；p.53–54提Gephi指標相關協作，未指明每個指標出自何工具。
- Reconstruction decision：先釐清最短路徑採無權重、距離或由flow轉換的成本；保存 `flow` 與 `distance/cost` 不同欄位。不能假定原研究做過1/flow。
- Assumption：有向模式、正規化、端點是否計入、精確或抽樣、不可達點處理、軟體設定均未採用。
- 驗證：小型鏈／分岔圖手算，避免將大流量解讀為更長路徑；抽樣時記錄精度與seed。

## D06｜Eigenvector、PageRank、Clustering（未決）

- Report-specified：R p.14 Eigenvector公式說A為0/1；p.14–15 PageRank說明d=0.85、來源按目的地數分攤；p.15 Clustering列 `2E/[k(k-1)]`。這些說明與有向加權圖的具體實作不完整對應。
- Reconstruction decision：逐指標定義加權與否、方向、正規化及零度節點處理；PageRank 0.85可作報告參數線索，但不能連帶假定其餘預設。
- Assumption：Eigenvector左右向量／權重與收斂、PageRank權重／dangling／personalization、Clustering有向或無向投影／加權變體均未定。
- 驗證：toy graph、PageRank和與非負性、未收斂與NA明確記錄；禁止靜默補成0。

## D07｜生活圈摘要與跨年標籤（未決）

- Report-specified：R p.16–19定義Cohesion、跨群流量、Q contribution與群級OD；p.53按地區由北至南、東至西編號。R p.17圖6提供11列統計。
- Reconstruction decision：將演算法membership與呈現標籤分開保存，群ID可置換；比較群組結構而非編號。
- Assumption：Cohesion分母是否包含in+out、內部旅次是否雙計、Inter_Flow方向、跨年新站點配群／重新訓練未定。
- 驗證：群級OD總流量守恆、Q貢獻加總與精度、每站點唯一membership，未匹配站點另列。

## D08｜K-means 前處理與角色編號（未決）

- Report-specified：R p.23四特徵為Weighted Degree、Betweenness、Clustering Coefficient、PageRank；WSS Elbow選k=4；p.25原Role_Group 2是核心、1是社區。圖15的呈現圖例另將核心列01、社區列03。
- Reconstruction decision：保留原群編碼與角色名稱的對照；不能假定原Role_Group等於圖例順序。候選k與尺度方案需在看分群成果前寫下。
- Assumption：標準化、log轉換、缺失／離群處理、初始化、重跑次數、seed及候選k範圍未知。不得由平均流量數字或WSS圖推定原作者有／無標準化。
- 驗證：比較有理由的尺度方案、WSS及群摘要、穩定性；k=4為原參考，不必保證新的Elbow仍在4。

## D09｜階層式72特徵與重要站點（未決）

- Report-specified：R p.27–28每個日類型24小時×Betweenness/Eigenvector/PageRank，共72變數，歐氏距離＋Ward.D2。p.50–52圖例可見平日5群、假日4群，樹圖標註 `hclust(*, ward.D2)`；p.28說藍色為重要站點。
- Reconstruction decision：把圖面的群數視為結果參考；執行前先解決D01與特徵尺度，再定切群與重要站點準則。各日類型72欄，不把兩者拼成一份72欄。
- Assumption：實際日期、標準化、缺小時／缺站點補法、切樹高度／選群數依據、重要站點規則未知；不能從高曲線猜出完整重要站點名單。若換套件，不假定同名Ward就等價，也不重複平方輸入距離。
- 驗證：特徵矩陣站點對齊、shape、距離與linkage小案例、群均值和地圖核對。

## D10｜BRouter OD 子集與模擬版本（阻擋全量路由）

- Report-specified：R p.29使用Trekking profile、OD流量賦予模擬路徑；p.44僅用預設路徑。前文重要站點篩選與送路由的OD集合關係未說明。
- Reconstruction decision：先定OD納入規則，再少量試跑；保存引擎／profile／路網日期與hash、座標、請求、回應、失敗與重試、覆蓋旅次權重。
- Assumption：是否只路由重要站點間、只要任一端重要、全OD、是否有流量門檻、每對是否只一條路徑均未知。不能把最終道路中位數篩選當成前置OD門檻。
- 驗證：端點／方向與幾何、加權覆蓋率、失敗不當作零流量；沒有GPS則只能稱模擬路徑。

## D11｜共同 road segments（阻擋道路風險表）

- Report-specified：R p.29只寫重疊路段流量加總。
- Reconstruction decision：在M9選定canonical segment識別及 route-segment 對照，保留方向、幾何版本及每個flow來源。
- Assumption：切於相鄰路由點或路口、OSM邊ID或幾何匹配、座標捨入／snap tolerance、線段方向合併、重疊但不同高程／車道、重複通過同路段計次均未知。
- 驗證：部分重疊、反向、交叉不相接與不同高程的人造案例；一筆旅次可經多段，不能要求全部segment flow和等於OD flow和。

## D12｜事故事件粒度與空間配對（未決）

- Report-specified：R p.7與31–34用2023–2024自行車A1/A2事故；p.33的「最近自行車道直線距離」是EDA定義，不是事故到模擬道路的配對實作。
- Reconstruction decision：事故事件與當事人資料先分清，保留event ID、原始車種與嚴重度；事故到road segment的規則獨立決定，保存距離／歧義／未匹配。
- Assumption：自行車種類篩選碼、座標系、事故去重鍵、nearest／buffer、距離門檻、路口多路段、橋面上下層及配對權重均未知。
- 驗證：人工看點線疊圖、距離敏感度、事件不重計；若多配對需要分攤守恆，未配對不能默認無事故。

## D13｜EPDO類別、純財損與單位（未決）

- Report-specified：R p.35為 `EPDO=193×死亡事故次數+117×受傷事故次數+1×僅財損事故次數`；係數依原報告改採其他財損成本基準，表3金額為1999年幣值。R p.36與41–42另呈現每千旅次EPDO。
- Reconstruction decision：分開保存EPDO原量與 `1000*EPDO/flow`；係數作歷史研究設定，不宣稱為目前官方通用標準，也不當作當前新臺幣損失。
- Assumption：原作者以A1/A2映射死亡／受傷事故的方式、混合死傷處理、純財損來源均未知。只有A1/A2時不得假設純財損為0；可在後續明示範圍後另算僅A1/A2的部分指標，但不是完整EPDO。不能把死傷人數直接當事故次數。
- 驗證：事件層級互斥類別、手算案例、財損缺值狀態、flow=0或缺失處理。

## D14｜CBI分母、篩選與高風險門檻（未決）

- Report-specified：R p.36：`SRI=N_segment/max(N)`、`SSI=EPDO_segment/max(EPDO)`、`CBI=SRI+SSI`；平假日各自流量中位數以上路段特別討論。
- Reconstruction decision：保存事故量、EPDO、兩個最大值分母、流量及當次參考路段集合；將中位數篩選放在道路流量層，而非OD送路由層。
- Assumption：max是在全路網還是篩選後集合、平假日分別計或共用、事故有否相同日類型切分、中位數等號／計算方法、高CBI數值門檻與色階分段均未知。無事故的全零集合需明定零分母政策。
- 驗證：同一分母下SRI/SSI界限、CBI在0–2（有正分母且非負資料時）、零分母案例、篩選前後敏感度。不能只用紅色猜固定門檻。

## D15｜推論界線與報告矛盾（已採用表述原則）

- Report-specified：R p.32明言缺天氣曝險量；p.33距離不判定事故在車道上；p.38–41提出設計／速差等解釋。p.8提統計顯著性，但未留相應檢定或識別設計。
- Reconstruction decision：全部自行車事故／模擬YouBike流量僅在清楚標示母體差異下呈現為代理指標，不稱實測YouBike事故率；高CBI、每千旅次EPDO與嚴重度分布分開，不由兩張圖色差推論低嚴重度。圖面相關不等於因果，也不代表已證實現場危險機制。
- Report-specified：R p.41有「北部特定路段（如信義一帶）」定位疑義；R p.43表4 Broadway車道數2，S p.29為1；R p.5文獻年份2016、p.44書目2017；同表英尺公尺換算亦需另核。
- Reconstruction decision：上述只記錄為原報告內部不一致／待查，不用它們驗收重建，也不在本階段延伸道路工程建議。報告明文與圖面若不一致，兩者並列；不自動挑與新結果較近的版本。
- Assumption：沒有實證因果假設被採用；未來若要政策／因果結論，另行規劃資料與研究設計。

## 後續填寫格式

每個分析選擇新增：日期、條目ID、狀態、Report-specified依據、Reconstruction decision與替代方案、Assumption及影響、驗證指令／結果、相關commit。這些內容只在相應模組實際執行時補上，不能先填虛構驗證結果。


## Phase 2 新增紀錄（2026-09-12；D00–D15保持原樣）

新增分類 **Observed in raw data**：只表示這次來源檔實際觀察；不表示原研究一定用過相同檔案版本或做過相同處理。

### D16｜Source index與抽樣（本階段已採用）

- Report-specified：核心期間2023–2024，原報告提供資料集索引線索。
- Observed in raw data：使用者提供的索引實為CP950相容CSV，76列6欄，2020/04–2026/07無內部缺月或重複月；全部76個URL的HEAD回應200，同一ZIP URL樣式。工作表名稱不適用。
- Reconstruction decision：依本次要求選2023/11一般月份候選，避開年節及暑假，只下載一月。此為Phase 1「優先2023/01」提案的本階段選月調整，並非變更研究核心期間。小型索引可進Git，raw旅次ZIP仍忽略。
- Assumption：不能假設HEAD成功代表全部月檔完整，亦不能推定2022資料曾用於原研究hierarchical。2023/11不代表無任何天氣或活動影響。

### D17｜無表頭歷史schema（觀察與audit介面已確認）

- Report-specified：報告由起訖租借紀錄建OD，未提供完整資料字典。
- Observed in raw data：2023/11檔案2,941,065列、全部6欄、無表頭、UTF-8；目前官方頁的7欄含車種說明與此歷史檔不一致。沒有ID／座標／車種欄；第6位置實際為日期字串。
- Reconstruction decision：audit標c1–c6作位置參考；語意以官方說明與值型態判讀，並非原始欄名。全檔保留、不套目前7欄表頭、不進正式cleaning。
- Assumption：一列近似單筆租借、名稱近似場站標籤仍需歷史字典支持；不能宣稱唯一旅次鍵已確認。其他年schema未下載，不推定變更時間。

### D18｜名稱、重複與研究範圍（原清理決策仍未決）

- Observed in raw data：132列任一站名缺失；非空借名1,317、還名2,275種；958種只出現在還車，共62,371列。6種名稱含原生替代字元（10,457列）、7種含問號（14,456列）、16種帶數字後綴，其中14種有無後綴並存。
- Observed in raw data：全六欄完全重複的超額列5,101，涉及10,160列／5,059組；沒有trip ID，無法判定為真重複旅次。ID→name及name→ID一致性不適用，不能寫成無衝突。
- Reconstruction decision：只記錄候選問題，不補站名、不刪重複、不去後綴、不以站名猜行政區作正式篩選。原D02／D03政策未決狀態保留。
- Assumption：市外名稱線索不等同已完成跨市分類；`�`與括號缺口可能源自上游損壞／截斷，但未確認原因。原作者處理方式未知。

### D19｜時間精度與完整性（觀察已確認；時間政策未決）

- Observed in raw data：借車30天及720個日小時格都有資料；借還時間全部整點，c6皆等於借車日期，借還均界於11月；秒級獨立時長與整點差不可互換。零時長9列、超24小時167列、差異≥1小時5列。
- Reconstruction decision：完整性表述只限日期／小時覆蓋；正式交易完整性標為未證實。借還時間相減不當作精確時長。未套平假日日曆或決定借還歸屬。
- Assumption：去識別化捨入方式、時區、月底跨月旅次與發布端篩選規則未知。保留D01／D02及相關未知，不把本次觀察推回原實作。

### D20｜Audit實作與輸出（已採用）

- Reconstruction decision：Python標準函式庫（目前以3.11.0驗證）、嚴格CSV解碼、SQLite暫存精確比對重複列、JSON保存小型階層式audit與來源metadata；避免為metadata引入新依賴。尚未產生清理中間表，因此未新增Parquet依賴；未來分析表仍優先Parquet。
- Observed in raw data：ZIP 34,774,679 bytes；CSV 311,810,011 bytes；hash與完整計數見data-audit及audit-evidence。
- 驗證：合成案例測試、全檔守恆、獨立換行計數、HTTP MD5／bytes、ZIP CRC、audit前後SHA-256與重跑；不下載其他月本體、不輸出逐旅次清理資料。
- Assumption：沒有藉audit採納正式cleaning／station reconciliation／去重規則。下一步僅建議歷史站表來源及少量問題名稱的唯讀對照。


## Phase 2.5 新增紀錄（2026-09-13；D00–D20保持原樣）

本節新增 **Current official metadata** 標籤，僅表示目前官方頁面描述；不得回溯當作所有歷史檔schema。

### D21｜歷史schema版本與transition（觀察已確認）

- Report-specified：原報告未列月檔欄位版本、header或encoding規則。
- Current official metadata：目前官方頁描述7欄，順序為借車時間、借車場站、還車時間、還車場站、借用時長、車種、借用日期。
- Observed in raw data：完整掃描的2023/01、2023/11、2024/01、2024/06、2024/09、2024/10皆固定6欄，第6欄為日期；2024/11、2024/12、2025/03、2026/07皆固定7欄，第6欄為一般車／電輔車、第7欄為日期。2024/10為最後已確認6欄月，2024/11為第一個已確認7欄月。
- Reconstruction decision：正式parser至少分6欄／7欄兩版並以實際欄寬和值型態schema gate；月份只作候選提示，未知shape須fail closed。這是parser contract方向，不是正式cleaning實作。
- Assumption：上游精確切換日與原因未知；不把7欄出現原因直接歸因於2.0E，也不推定未抽樣月份一定遵守相同邊界。

### D22｜Header與encoding drift（觀察已確認）

- Observed in raw data：2023/01有6欄英文header、2026/07有7欄英文header，其餘8個樣本無header。2024/09–12含22,268–28,756個不可嚴格UTF-8解碼bytes，但以surrogateescape保留後，CSV欄寬及日期／時間／時長結構仍全部通過；樣本亦不能嚴格CP950解碼。
- Reconstruction decision：parser須辨識並驗證header，不固定跳首列；非法bytes須保留原值、定位並警示，不能`errors=replace`靜默創造替代字元。schema parsing與文字修復分層。
- Assumption：非法bytes成因與原字未知，不以目前站名猜字。

### D23｜Station metadata可用性（部分可用，歷史主檔仍未決）

- Current official metadata：官方目前即時feed列出station ID、名稱、行政區、地址及經緯度，但沒有`valid_from`／`valid_to`。
- Observed in raw data：2026/09/13官方快照1,800站與第三方保存的2024/05/31官方feed快照1,415站，快照內核心欄位均非空且ID／名稱各自唯一。兩快照共有1,411個ID，其中13個名稱不同、31個座標字串不同；兩點無法確定變更日期。
- Observed in raw data：Phase 2的16個`_數字`名稱在兩快照均exact match；14個同時存在無後綴base且對應不同ID。含`�`、`?`、不平衡括號均無exact match；958個destination-only名稱對臺北兩快照亦無exact match。
- Reconstruction decision：後綴不得直接移除；目前快照不得回填歷史；第三方快照只作可追溯的日期點證據。仍不建立正式station reconciliation或虛構有效期間。
- Assumption：destination-only可能含跨市站是待查線索，不是已完成分類；尚未找到完整2023–2024官方historical station master。

### D24｜Phase 2.5輸出與驗證（已採用）

- Reconstruction decision：保存schema compatibility matrix、小型JSON evidence、下載來源與hash；raw ZIP及站點快照維持Git忽略。以Python標準函式庫全檔串流檢查，不產生逐旅次轉換檔。
- 驗證：10個月份共49,405,032筆CSV records完成掃描，10個合成測試通過；詳細指紋與限制見`notes/schema-compatibility.md`。
- Assumption：沒有藉相容性audit決定清理、去重、站名合併、日曆、OD或分析方法。


## Phase 2.6 新增紀錄（2026-09-13；D00–D24保持原樣）

### D25｜Raw parser contract與canonical schema（已採用）

- Observed in raw data：Phase 2.5已確認6／7欄、有／無header與局部非法UTF-8組合；本階段不再掃全量月檔。
- Reconstruction decision：以首筆實際內容及逐筆結構gate辨識`v1_6col`／`v2_7col`，不依年月hard-code。統一輸出`borrow_time, origin_station_raw, return_time, destination_station_raw, duration_raw, bike_type, borrow_date`；v1的`bike_type`為null，不假設一般車。
- Reconstruction decision：另保留`_source_file`、CSV record序號`_source_row`、`_schema_version`與`_parse_warnings`；檔案層保留SHA-256。值保持原始字串，不在parser轉型或清理。
- Assumption：無。支援範圍只限已觀察schema；新header、欄寬或車種必須先審查契約。

### D26｜非法UTF-8與serialization gate（已採用）

- Reconstruction decision：以`surrogateescape`無損保留非法bytes，warning保存欄位、byte數與CSV解引號後field bytes Base64；禁止`errors=replace`。raw檔仍為完整位元組證據。
- Reconstruction decision：含warning的record不得直接交給PyArrow／Parquet string欄；`require_serialization_safe`須fail closed並留在staging／quarantine。串流只有完整到EOF無錯才可原子接受。
- Assumption：沒有採用任何亂碼修復或站名推測；pandas object可暫存不等於可安全序列化。

### D27｜Parser與cleaning邊界（已採用）

- Reconstruction decision：parser只做CSV／ZIP結構、schema與必要格式驗證、canonical mapping、provenance及warning。站名修復／合併、去重、缺值與duration處理、地理／日曆篩選及OD均留給後續明示決策。
- 驗證：7個可提交fixture及相應測試涵蓋四種schema/header組合、非法UTF-8、未知欄寬、malformed header；另測未知車種、中途欄寬改變、ZIP及serialization gate。詳細契約見`notes/parser-contract.md`。
- Assumption：沒有因parser實作解決D02、D03或其他既有unknown／unresolved方法問題。


## Phase 3 新增紀錄（2026-09-14；D00–D27保持原樣）

### D28｜Issue分類與重疊計數（已採用）

- Observed in raw data：2023/01–2024/12共92,700,026個data records；Invalid union為0，Quality-issue union為1,878,361（2.0263%），Suspicious union為1,870,420（2.0177%），兩類重疊26,618。完整規則與分月結果見`notes/data-quality-profile.md`及JSON。
- Reconstruction decision：Invalid、Quality issue、Suspicious分開定義，同一record可同時命中多個issue；總體只用union與cross-count，不直接加總individual issue counts。`clean-with-respect-to-current-rules`只代表未命中本階段規則，不代表已清理或絕對正確。
- Assumption：沒有由profile推定上游成因，也沒有把本次raw觀察回寫成原研究處理方式。

### D29｜Repeated identical records全部保留（已採用）

- Observed in raw data：316,265個完全相同record群組涉及637,221 records，excess copies為320,956；完整multiplicity與月別分布見profile。
- Reconstruction decision：Repeated identical records獨立盤點，不分類為Invalid、Quality issue或cleaning candidate；全部保留，不執行`drop_duplicates()`。只有未來取得可證明重複匯入的外部證據，才能另立決策重審。
- Assumption：完全相同不等於同一真實旅次；現有資料無trip ID，借還時間只有整點精度。

### D30｜罕見／極端與structural missing（已採用）

- Observed in raw data：duration P99.9為15,759秒，>24h有6,988 records，最大315,533,802秒；全期只出現一次的raw OD pair有299,458 records。6欄schema共有80,305,284 records，本來沒有bike type欄。
- Reconstruction decision：rare／extreme只作Suspicious或描述性標記，不自動等同error；6欄schema的`bike_type=None`是structural absence，不算missing-data issue。`_數字`站名後綴同樣只盤點、不視為error。
- Assumption：本階段未設定duration刪除門檻，也未判定rare OD的實體真偽。

### D31｜Encoding與站名現象保持分離（觀察已確認；修復未決）

- Observed in raw data：非法UTF-8共229,167 bytes、189,089 affected fields、181,703 affected records；只出現在起終點站欄。完整掃描發現受影響月份為2023/03–07與2024/07–12，擴充Phase 2.5代表月份抽樣結果。另有原生`�`、`?`與不平衡括號等不同現象，不與illegal byte混用。
- Reconstruction decision：繼續以raw exact value及Base64證據保留，不做encoding repair或站名reconciliation。Cleaning policy必須在profiling後另行制定。
- Assumption：不同文字現象的上游原因及正確站名均未知；不得因字串外觀看似截斷就自行補字。

### D32｜Extended report period補充（2026-09-14；觀察已確認）

- Report-specified：原報告初步EDA期間為2023/01–2025/03；2023–2024仍為核心network／accident analysis期間。
- Observed in raw data：2025/01–03新增17,013,873 records；三月皆為7欄、無header，車種仍只有一般車／電輔車，Invalid union皆為0。2025/01有20,420個illegal-UTF8 affected records，2025/02–03為0；沒有新增affected field、raw illegal-byte value或既有station anomaly以外的新pattern／raw值。
- Observed in raw data：完全重算2023/01–2025/03後，extended denominator為109,713,899；Quality union 2,046,728（1.8655%）、Suspicious union 2,132,663（1.9438%）、clean-with-respect-to-current-rules 105,562,684（96.2163%）。Duration長尾仍為既有型態，max未變；詳細比較見profile。
- Reconstruction decision：JSON根層繼續代表2023–2024 core period，extended結果另存`extended_report_period`；period-global的destination-only與rare OD各自在24月／27月範圍重新計算，不直接相加。既有D28–D31定義與cleaning未決狀態不變。
- Assumption：沒有因2025新增月份採用任何repair、刪除、reconciliation或新的異常門檻；「沒有新pattern」只限本階段既有規則能辨識的型態。


## Phase 3.1 新增紀錄（2026-09-14；D00–D32與Phase 3 evidence保持原樣）

### D33｜站名候選的證據門檻（已採用於forensics，尚未授權repair）

- Observed in raw data：extended period共有8個illegal-byte patterns、7個原生`�`、10個`?`、31個不平衡括號／疑似截短值；完整次數、月份與起終點分布見`notes/station-name-forensics.csv`。
- Reconstruction decision：fuzzy／wildcard／prefix只負責產生候選；只有metadata中的`(name, station ID, city)`唯一時才標`unique_supported`。多候選必須標`ambiguous`，零候選標`unresolved`，不得在本階段寫回資料。
- Assumption：Level B單一候選是否足以成為Phase 3.2 deterministic repair規則仍由分析者決定；本階段不把candidate稱為corrected value。

### D34｜非法bytes與文字可恢復性分離（已採用）

- Observed in raw data：8個illegal UTF-8 patterns都可由Base64／surrogateescape無損重現原始bytes，但嚴格UTF-8解碼仍失敗；8個均有唯一metadata候選。
- Reconstruction decision：byte-recoverable固定記為0；唯一metadata候選只標`text-recoverable with external evidence`。禁止把「保存了原bytes」誤寫成「可由bytes自行恢復正確文字」。
- Assumption：上游截斷原因與遺失bytes未知；不以反覆試encoding選取看似合理中文。

### D35｜Destination-only重新詮釋建議（不回寫Phase 3）

- Observed in raw data：extended period的1,528個destination-only非空名稱中，1,311個exact-match新北市政府2026/09/14官方snapshot的唯一站點，涵蓋1,784,172 records；217個名稱／21,940 records仍未解。現有臺北兩snapshot沒有額外exact-only match。
- Reconstruction decision：建議將1,311個已命中新北站的值視為cross-city／station-universe issue而非dirty station name；Phase 3原始flag與denominator維持immutable。`_1`／`_2`仍原樣保留，repeated records仍不處理。
- Assumption：目前官方snapshot沒有`valid_from`／`valid_to`，不能單憑2026快照證明各站在2023–2025每月的營運狀態；217個未解值不得自行歸類或修復。


## Phase 3.2 新增紀錄（2026-09-14；D00–D35與既有evidence保持原樣）

### D36｜Deterministic repair evidence gate（政策已採用，尚未執行repair）

- Reconstruction decision：current metadata unique match單獨不足以進Tier 1。Tier 1必須同時具備唯一name／ID／city候選、無競爭候選，以及至少一項時間證據：2024/05/31 dated snapshot，或完整候選名稱在damaged value同月／相鄰月的raw station universe出現。
- Reconstruction decision：Tier 2為current metadata唯一候選但缺時間證據；Tier 3包含多候選及零候選。Fuzzy、prefix、地理合理性、OD頻率或人工外觀均不能單獨升格。
- Assumption：是否把Tier 1提高為「兩種時間證據皆須具備」仍待分析者決定；本階段採使用者指定的至少一項獨立temporal／historical corroboration。

### D37｜Allowlist coverage與未決mapping（觀察已確認）

- Observed in raw data：56個anomaly raw mappings中，29個Tier 1、14個Tier 2、10個ambiguous、3個unresolved。Extended classified station-anomaly union共2,046,061 records，Tier 1涵蓋1,115,020（54.4959%）、Tier 2涵蓋4,377、ambiguous 926,106、unresolved 558。
- Reconstruction decision：10個ambiguous truncated values與3個unresolved values維持原狀；allowlist對ambiguous保留全部candidate，不選最長、不補括號。`approved_repair`只代表未來可套用的政策輸入，本階段沒有替換任何值。
- Assumption：另一端站名缺失而不在OD聚合的少數records不被擅自分派decision；Phase 3正式issue count仍為原始分母。

### D38｜Station universe與repair provenance（政策已採用，尚未建立cleaned trips）

- Observed in raw data：1,311個destination-only names精確命中新北目前官方站點，涵蓋1,784,172 records；217 names／21,940 records仍未解。
- Reconstruction decision：前者標`not_an_error`／cross-city station-universe expansion，與repair mapping分離；`name_validity=confirmed`不等於`historical_operational_status`，後者全數保持unresolved。Phase 3／3.1 evidence不回寫。
- Reconstruction decision：未來cleaned layer須並存raw／clean／station ID／repair status，另保存rule version、evidence tier/source、repair timestamp及pipeline version；未知或衝突規則須fail closed。`_1`／`_2`與repeated records政策不變。
- Assumption：本階段沒有建立full cleaned dataset，也沒有宣稱2026 snapshot可證明2023–2025逐月營運狀態。


## Phase 3.3 新增紀錄（2026-09-15；D00–D38與既有evidence保持原樣）

### D39｜Tier 1最終門檻與subtype（已採用，未執行repair）

- Reconstruction decision：最終Tier 1維持「唯一metadata候選＋至少一項historical／temporal evidence＋無競爭候選」。1A同時有dated snapshot與raw temporal；1B只有dated snapshot；1C只有research-period raw temporal。三者均approved，current metadata alone仍不足。
- Observed in raw data：29個既有approved entries逐筆重審時，發現同一raw bytes在`illegal_utf8`與`unbalanced_parentheses`規則分別指向兩個station ID；相關2 entries（同一raw value、52 records）降為ambiguous。最終Tier 1為27個：1A 8、1B 6、1C 13；subtype individual record unions為611,294、471,391、34,350，彼此可能重疊，不可相加，正式approved union為1,114,968（54.4934%）。
- Assumption：1B／1C的證據強度差異只作provenance標記；本階段沒有另行調整修復優先順序。

### D40｜Exact-match execution與quarantine contract（設計已採用）

- Reconstruction decision：runtime只允許raw bytes／Base64 exact match；allowlist版本缺失／混用、同raw多個approved identity、evidence缺失或rule conflict一律fail closed。禁止runtime fuzzy、prefix、地理或OD fallback。
- Reconstruction decision：Tier 2、ambiguous、unresolved及unknown全部保留raw value並記錄相應status，不刪record；destination-only `not_an_error`只走station-universe分流，不觸發repair。是否納入OD留待後續analysis policy。
- Assumption：Phase 3.3只用小型contract tests，沒有建立完整cleaned trips或quarantine dataset。

### D41｜版本、撤銷與rollback（設計已採用）

- Reconstruction decision：allowlist不可原地覆寫；mapping新增、修正、撤銷或evidence更新均發新rule version並保留舊artifact。錯誤mapping以新版本標`revoked`／`superseded`，再由raw source of truth重建cleaned layer，不原地修補歷史cleaned data。
- Reconstruction decision：每次future run須保存allowlist hash、rule version、pipeline version、execution timestamp及raw hashes；raw station value永遠保留。
- Assumption：尚未選定cleaned／quarantine的實際儲存格式、partition策略與發布流程。


## Phase 3.4 新增紀錄（2026-09-16；D00–D41與既有evidence保持原樣）

### D42｜雙端cleaned schema與raw bytes保存（已採用於synthetic execution）

- Reconstruction decision：origin／destination使用同構欄位，並存raw serialization-safe display、exact raw Base64、clean name、station ID、city、repair status、rule version、evidence tier及Tier 1 subtype；parser provenance原樣保留。Clean值不得覆寫raw evidence。
- Reconstruction decision：6欄schema的`bike_type=None`原樣寫入Parquet；`_1`／`_2`不變。Tier 2、ambiguous、unresolved與unknown值均可進cleaned output，不因未修復而quarantine。
- Assumption：synthetic fixture的站名、ID、city與時間全為測試資料，不構成任何真實station mapping新證據。

### D43｜Illegal-byte cleaned-layer gate（已採用於synthetic execution）

- Reconstruction decision：raw bytes以Base64保留，非法byte另以`\\xNN`安全display呈現，禁止replacement。只有exact approved mapping且canonical clean string可嚴格UTF-8 serialization時可進cleaned Parquet；未核准非法值進quarantine，不執行repair。
- Reconstruction decision：PyArrow缺失、Parquet寫入失敗或讀回不一致均fail closed；不以其他格式冒充成功。
- Assumption：這項gate只驗證serialization責任邊界，不判定非法bytes的上游成因或正確文字。

### D44｜Quarantine、record conservation與partition atomicity（已採用於synthetic execution）

- Reconstruction decision：逐record serialization／invariant failure可quarantine並保留完整安全raw envelope與provenance；allowlist conflict、version mismatch或malformed approved rule則整個partition載入失敗。兩者都不是刪除。
- Reconstruction decision：`input = cleaned accepted + quarantined`為必要gate。Cleaned Parquet、quarantine與receipt全部先寫staging並驗證，成功才atomic accept；失敗不得留下半份正式partition。
- Reconstruction decision：receipt保存input／output hashes、版本、各status count、起訖時間及validation；固定synthetic輸入與時間戳時結果必須可重現。
- Assumption：本階段只有13筆synthetic records；尚未證明任一完整真實月份的資源需求或成功率。


## Phase 3.5 新增紀錄（2026-09-16；D00–D44與既有evidence保持原樣）

### D45｜2023/11 real-month execution結果（觀察已確認）

- Observed in raw data：來源hash、單一CSV member、2,941,065 records、6欄無header、strict UTF-8及全null structural `bike_type`均與Phase 2／3 evidence一致。全部2,941,065筆進入cleaned Parquet，quarantine為0，record conservation成立。
- Observed in raw data：approved repair套用於origin 17,956 sides、destination 19,105 sides，共37,061 sides；至少一端repair為35,446 trips（1.2052%），其中origin only 16,341、destination only 17,490、both 1,615。Subtype為1A 16,593、1B 20,306、1C 162 sides。
- Assumption：這些是finalized allowlist對2023/11的execution coverage，不代表修復後站點一定適合所有後續分析範圍或歷史有效期間推論。

### D46｜空白站名、非approved狀態與repeated records（execution決策已確認）

- Reconstruction decision：空白station raw value是可安全序列化的既有品質問題，不是contract failure；raw欄與Base64欄存在即可，空字串不得因此quarantine。這項修正不回填站名。
- Observed in raw data：candidate-only、ambiguous、unresolved與not-an-error均依契約保留；Parquet reread確認非approved clean變更、approved缺provenance與非approved identity assignment皆為0。
- Observed in raw data：Phase 3的5,059 repeated groups／10,160 involved records／5,101 excess copies完整保留；preflight與output raw multiset fingerprint一致。既有retain-all及禁止`drop_duplicates()`決策不變。

### D47｜單月atomic Parquet可行，但全期間尚未授權（已採用）

- Observed in raw data：27欄Zstandard Parquet為37,567,504 bytes，完整重讀2,941,065筆成功；wall clock 269.10秒、約10,929 records／秒、peak working set約616 MB。Staging驗證完成後才atomic finalize。
- Reconstruction decision：2023/11證明6欄strict-UTF8月份的execution path可行，但不直接外推為7欄或illegal-byte月份已驗證。下一個最小風險驗證應選一個同時涵蓋7欄與非法UTF-8的單月，再決定是否授權full-period cleaning。
- Assumption：以單月速度線性外推全期間時間／空間成本只能作粗略容量提示；不同schema、字串分布與磁碟狀態可能改變效能。


## Phase 3.6 新增紀錄（2026-09-16；D00–D47與既有evidence保持原樣）

### D48｜2024/11七欄與illegal-byte execution結果（觀察已確認）

- Observed in raw data：2024/11來源hash、5,883,102 records、7欄無header、一般車5,733,169／電輔車149,933與Phase 2.5／3 evidence一致；blank、null及unknown bike type皆0。
- Observed in raw data：25,720 illegal bytes影響20,944 station fields／20,217 records；origin 10,029 sides、destination 10,915 sides、兩端同時727 trips、unique Base64 pattern union 7。Approved 20,930 sides／20,203 records安全進入Parquet；3個Tier 2 sides與11個ambiguous sides使14筆records整筆quarantine。
- Assumption：這些是2024/11 execution observations，不推定其他月份有相同比例或相同raw pattern組合。

### D49｜Quarantine-aware denominator與multiset contract（最小修正已採用）

- Observed in raw data：第一次2024/11 run在finalize前因validator把完整input bike-type counts誤套到accepted-only Parquet而fail closed；Phase 3.5 quarantine=0，故未暴露此denominator問題。該run沒有留下正式partition或receipt。
- Reconstruction decision：input、accepted與quarantine的bike-type denominator分開保存並驗證；accepted與quarantine fingerprint各自計算，再合併對照完整input。Illegal raw identity由Base64還原bytes，不以serialization-safe display代替。新增regression test後，第二次完整run通過。
- Reconstruction decision：未核准unsafe side使整筆record quarantine；不產生半修復record。Serialization-safe的Tier 2／ambiguous／unknown仍留在cleaned output。

### D50｜Full-period cleaning execution gate（READY，尚未執行）

- Observed in raw data：2024/11最終為5,883,088 accepted＋14 quarantine，筆數守恆；71,575 station sides／68,884 trips套用approved repair。Parquet與quarantine完整讀回，raw combined multiset、兩種bike type、provenance及repair invariants全部通過；repeated groups 17,918完整保留。
- Reconstruction decision：6欄／strict UTF-8已由2023/11驗證；7欄／bike type／illegal UTF-8／approved repair／unapproved quarantine已由2024/11驗證。沒有未解的silent-corruption execution defect，full-period cleaning gate標為READY。
- Reconstruction decision：下一個最小任務為執行2023/01–2025/03 full-period cleaning；本階段不自動開始，也不改repair policy、analysis inclusion或其他Phase 1 unresolved方法問題。


## Phase 3.7 新增紀錄（2026-09-16；D00–D50與既有evidence保持原樣）

### D51｜Full-period cleaning守恆與輸出狀態（已完成）

- Observed in raw data：2023/01–2025/03共27個月份、109,713,899 input records，正式執行結果為109,713,772 accepted與127 quarantine，每月及全期間的`input = accepted + quarantine`均成立。Core period 2023/01–2024/12為92,700,026 input = 92,699,907 accepted + 119 quarantine。
- Observed in raw data：127筆quarantine皆為`serialization_unsafe_unapproved_destination_station_raw`；這些records保留exact raw Base64、source provenance與原始canonical fields，不是刪除。Cleaned Parquet共1,471,049,497 bytes，quarantine JSONL共180,707 bytes，大型輸出均留在本機並由Git忽略。
- Reconstruction decision：每月為獨立atomic partition；只有source、pipeline/parser/allowlist version、allowlist hash、output hashes與validation status全部相符時才可安全續跑重用。單純檔案存在不足以宣告月份完成。

### D52｜Full-period repair、encoding與repeated-record execution結果（觀察已確認）

- Observed in raw data：1,163,935 station sides套用approved repair，涉及1,118,165 trips至少一端修復；Tier 1 subtype sides為1A 637,743、1B 490,507、1C 35,685。Candidate-only 4,305 sides、ambiguous 947,098 sides、unresolved 279 sides均依既有政策保留，未自行升格或猜測repair。
- Observed in raw data：254,831 illegal bytes影響210,267 station fields／202,123 records；210,139 affected sides／201,996 affected records由approved exact-byte mapping安全進入accepted output，127筆未核准unsafe records進quarantine。原始bytes以Base64保留，未使用replacement repair。
- Observed in raw data：397,971 repeated groups／803,160 involved records／405,189 excess copies全數保留；raw multiset fingerprint在每月cleaning前後相符，未使用`drop_duplicates()`。

### D53｜Execution defect、global validation與後續邊界（已解決）

- Observed in execution：2024/08首次執行在preflight因monthly sparse issue map省略0-count key而觸發`KeyError`；前面19個月份已atomic finalize，失敗月份沒有partial finalized partition。最小修正將省略的monthly issue key依Phase 3 profile語意讀為0，新增regession test後安全續跑。
- Observed in execution：27月完成後，第一版global manifest將整數彙總值與Phase 3 profile的`{count, percentage}`物件直接比較，因型別不同而fail closed；實際monthly sums與`count`完全一致。最小修正只讀取aggregate `count`，新增regession test後重驗27個partition hashes，最終Phase 3A cross-check全部為true。
- Reconstruction decision：Full-period cleaning標記COMPLETE，但不自動將quarantine、missing endpoints、candidate-only、ambiguous、unresolved或cross-city station納入或排除OD。下一個最小任務應先由分析者明確OD inclusion policy；本階段不建OD matrix、graph或任何SNA／clustering／routing。
- Assumption：Phase 1與後續分析尚未解的station historical validity、市界、時間精度與methodology問題保持unknown／unresolved；Phase 3.7的execution成功不構成對這些問題的解答。


## Phase 4.0 新增紀錄（2026-09-16；未建立OD edge或network）

### D54｜Primary OD identity與node key（已採用）

- Evidence-supported reconstruction：鎖定current與2024/05/31 snapshots為1,817個exact names提供唯一ID，station-universe evidence為1,311個New Taipei raw Base64 values提供ID；本次沒有觀察到exact name多ID collision。
- Reconstruction decision：primary trip兩端均必須解析為唯一canonical station ID；OD node key只使用station ID，name只作label。Approved repair、exact station-universe `not_an_error`與exact unique-metadata `unchanged_no_rule`可eligible。
- Reconstruction decision：安全名稱但無唯一ID者不進primary，只留於sensitivity；candidate-only、ambiguous、unresolved與name collision均fail closed，不強塞ID。

### D55｜Network city boundary與historical operation（已採用）

- Reconstruction decision：primary boundary為full observed uniquely identifiable station universe，不限Taipei-only。已唯一辨識的New Taipei endpoints與cross-city trips納入，city只作node attribute。Taipei-only只是sensitivity variant。
- Observed in cleaned/evidence profile：ID-required primary中Taipei→Taipei為106,302,441 records，Taipei→New Taipei為1,774,979；沒有觀察到New Taipei-origin primary trips。
- Reconstruction decision：raw trip occurrence可作為source在當時點記錄該endpoint的operational evidence，與unique identity合用時足以納入reconstructed OD；但不寫成官方active interval或`valid_from/valid_to`證明。

### D56｜Exclusion precedence、repeated rows與duration（已採用）

- Reconstruction decision：互斥主理由順序為quarantine→missing→ambiguous→unresolved→candidate-only→name collision→no unique ID→eligible；secondary flags另行保留，不把overlapping counts相加。
- Reconstruction decision：quarantine與missing endpoint不可進OD，但保留於QA dataset。Repeated identical records全數計入OD weight，不deduplicate。Duration=0、>24h、>7d與cross-midnight不影響OD eligibility。
- Assumption：routing、accident或其他模組若需要duration/geographic filters，必須另立後續決策；Phase 4.0不預先代替它們決定。

### D57｜Primary impact與sensitivity plan（觀察與設計已確認）

- Observed in cleaned/evidence profile：primary ID-required policy預計保留108,077,420／109,713,899 records（98.508412%）。Precedence-resolved exclusions為127 quarantine、667 missing、926,108 ambiguous、279 unresolved、4,297 candidate-only、0 name collision與705,001 no unique ID。
- Reconstruction decision：保留四個未執行的sensitivity variants：hybrid safe-name fallback 108,782,421；hybrid + candidate 108,786,718；broad raw pseudo-nodes 109,713,105；Taipei-only ID-required 106,302,441。
- Reconstruction decision：Phase 4.1 builder必須讀取`od-inclusion-policy-v1`，不可重新hard-code政策。Phase 4.0只做eligibility profiling，沒有groupby origin/destination、OD matrix、graph或任何SNA。


## Phase 4.1 新增紀錄（2026-09-17；只完成OD aggregation）

### D58｜資料觀測邊界（已確認）

- Observed dataset boundary / source mechanism：票證資料由臺北市政府提供，觀測起點皆為臺北市站點，目的地可延伸至新北市。
- Reconstruction decision：`New Taipei→Taipei=0`與`New Taipei→New Taipei=0`不得解讀為現實行為零流量；這兩個方向不在來源的完整觀測範圍。

### D59｜OD aggregation contract（已採用）

- Reconstruction decision：只聚合`od-inclusion-policy-v1`的`od_eligible` records，以station ID作唯一node key；directed edge為origin→destination，weight只計`trip_count += 1`。
- Reconstruction decision：self-loops與repeated identical records全數保留。Duration、bike type、距離、百分比或其他normalization不參與weight。
- Observed in execution：27個monthly outputs、2023、2024、core與full aggregates均守恆；full為108,077,420 trips／1,211,515 edges。

### D60｜期間與node label（已採用）

- Report-specified scope：原報告核心network期間為2023/01–2024/12；本次core aggregate為91,138,763 trips／1,125,519 edges。
- Reconstruction execution scope：full available scope為2023/01–2025/03；2025/01–03保留作延伸，不默默混入原報告核心SNA。
- Reconstruction decision：同一ID的多個observed labels不拆node。Deterministic display label依current official metadata、historical snapshot、station-universe evidence的順序選取；2個label conflicts保留於audit，不自行改identity。

### D61｜Phase 4.1執行與後續界線（已確認）

- Observed in execution：32個output hashes在獨立重跑完全一致。首次aggregate reader因Hive-style path inference型別衝突而fail closed且未留下finalized partial output；單檔reader修正與回歸測試後通過。
- Reconstruction decision：Phase 4.1只有descriptive edge／node inventory與exclusion accounting；沒有graph construction或任何centrality、Louvain、clustering、routing、事故分析。
- Assumption：self-loops是否在後續SNA排除，以及directed／weighted graph的各指標定義，留待Phase 4.2 contract決定。


## Phase 4.2 新增紀錄（2026-09-17；未執行core centrality）

### D62｜Core graph construction（已採用）

- Report-specified：核心network期間為2023–2024，網絡描述為directed weighted。
- Reconstruction decision：以Phase 4.1 `core_2023_2024` OD為唯一input；NetworkX 3.4.2 `DiGraph`、station ID作node、origin→destination作edge、`trip_count`作flow strength。Data-layer保留self-loop。
- Observed in execution：2,782 nodes、1,125,519 edges、weight sum 91,138,763、1,504 loop edges／6,023,568 loop trips，與Phase 4.1完全一致；0 duplicate OD keys、0 null IDs。只做integrity check，沒有core metric ranking。

### D63｜Weighted Degree與Betweenness（已採用）

- Report-specified：Weighted Degree為in＋out且分列公式，但借／還方向文字顛倒；Betweenness只列shortest-path公式，weighted implementation未指定。
- Reconstruction decision：依O→D將借出定義為out-strength、歸還為in-strength，另輸出total；loop在in與out各計一次。Betweenness primary採directed unweighted、normalized、endpoints=false並排除loops。
- Reconstruction decision：`trip_count`不可直接作shortest-path distance。Phase 5 sensitivities保留`1/trip_count`與`1/log1p(trip_count)`distance transforms。

### D64｜Eigenvector、PageRank與Clustering（已採用）

- Report-specified：Eigenvector adjacency為0/1但未指定left/right；PageRank明載alpha=.85、incoming-link及uniform dangling邏輯但flow weighting未說清；Clustering列`2E/[k(k-1)]`但未指明directed／weighted實作。
- Reconstruction decision：Eigenvector primary為directed unweighted left／predecessor influence，排除loops；PageRank primary為directed、`trip_count` weighted transition、alpha=.85、uniform personalization/dangling並保留loops；Clustering primary為移除loops後的undirected simple unweighted local coefficient。
- Reconstruction decision：Eigenvector保留weighted-left與reverse/right sensitivity；PageRank保留unweighted sensitivity；Clustering保留directed-unweighted與undirected-weighted sensitivity。

### D65｜Library validation與scope guard（已確認）

- Observed in synthetic validation：self-loop對total strength計兩次；unweighted與inverse-flow shortest path在toy graph選到不同路徑；NetworkX directed eigenvector的left與reverse/right結果不同；weighted／unweighted PageRank不同且weighted sum=1；undirected clustering手算1與1/3均吻合。
- Reconstruction decision：Phase 5必須讀取`network-metric-contract-v1`，未知version／direction option fail closed；未收斂或NA不得靜默補0。
- Assumption：上述choices是重建決策，不能聲稱為原研究實作。Phase 4.2禁止core centrality、Louvain、modularity、K-means、hierarchical clustering、routing與事故matching。


## Phase 5.0 新增紀錄（2026-09-17；只執行core SNA metrics）

### D66｜Core SNA execution與數值守恆（已確認）

- Primary result：依`network-metric-contract-v1`在2,782 nodes／1,125,519 edges上完成全部正式metrics；in與out strength各加總91,138,763，total strength加總182,277,526。所有欄位無NaN／Inf，PageRank和、Eigenvector norm及centrality ranges均通過。
- Reconstruction decision：依O→D方向維持borrow=out、return=in；原報告文字方向錯置不沿用。Self-loop只按既定metric contract處理，沒有全域刪除。

### D67｜Exact betweenness與checkpoint（已採用）

- Observed in execution：primary、inverse-flow及inverse-log-flow三組Betweenness均以exact computation完成，未抽樣；各自耗時226.88、678.24與582.06秒。
- Reconstruction decision：checkpoint必須同時符合contract hash、core OD hash、NetworkX版本與checkpoint output hash才能續用；不相符即重算或fail closed。

### D68｜Sensitivity interpretation（已確認）

- Sensitivity result：七組比較的Spearman介於-0.543700至0.984156；Top 20 overlap介於0/20至12/20。Weighted clustering與primary為負相關且Top 20零重疊；weighted eigenvector及unweighted PageRank雖全體相關高，Top 20仍分別為0/20與3/20。
- Assumption：這些差異量化reconstruction choice的敏感度，不能據此宣稱原研究採用任一variant，也不能為配合舊結果更改primary contract。

### D69｜Phase 5完成與後續界線（已確認）

- Primary result：deterministic Top 20已輸出，值降冪且station ID升冪tie-break；節點Parquet SHA-256為`a31ade358f59529ca8d5784bd0151aa17be6894b3a39194322534659dd27fe72`。
- Reconstruction decision：Phase 5.0標記COMPLETE；本階段未執行Louvain、modularity、K-means、hierarchical clustering、routing或事故matching。下一個最小任務最多為Phase 6.0 Community detection／Louvain reconstruction contract。


## Phase 6.0 新增紀錄（2026-09-17；未在完整core graph執行Louvain）

### D70｜Louvain library與projection（已採用）

- Implementation unspecified：原報告沒有留下directed／undirected、reciprocal merge、library或version。
- Observed in library：NetworkX 3.4.2內建`louvain_communities`支援Graph與DiGraph；無向化並非library限制。
- Reconstruction decision：Primary以sum projection建立undirected simple weighted graph，`w({i,j})=w(i→j)+w(j→i)`；單向edge保留原weight。這表示total observed interaction，不保留方向語意。

### D71｜Self-loop、modularity與參數（已採用）

- Reconstruction decision：Data-layer self-loop保留，但primary Louvain-layer在projection前移除；retain-loop只作sensitivity。Primary使用weighted undirected Newman–Girvan modularity、resolution=1.0、NetworkX 3.4.2、threshold=1e-7、max_level=None與seed=42。
- Assumption：resolution=1.0是library-standard reconstruction baseline，不代表原研究參數。原報告Q≈0.66574及約11群只作事後comparison reference，不是acceptance或調參目標。

### D72｜Projection QA、isolates與labels（已確認）

- Observed in execution：1,125,519 directed edges形成375,424 reciprocal pairs及373,167 one-way pairs，共748,591 projected edges；85,115,195 non-loop weight加6,023,568 removed loop weight等於91,138,763。完整projection有0 isolates，沒有執行core Louvain。
- Reconstruction decision：契約仍保留所有source nodes；若移除loop後成為isolate，指定singleton community。Community label依每群最小station ID升冪後給1-based integer，library原始群號無語意。

### D73｜Reproducibility與sensitivity plan（已採用）

- Observed in validation：synthetic projection、獨立weighted modularity、fixed-seed partition與20-node bounded real implementation check通過；bounded partition只保存fingerprint，不解讀群數或Q。
- Reconstruction decision：Phase 6.1須比較primary seed 42與7／19／73，回報community count、modularity、ARI與NMI；另保留max／unweighted projection、retain-loop及resolution 0.5／1.5 sensitivities，不得為貼近報告數字反向fitting。


## Phase 6.1 新增紀錄（2026-09-18；未執行K-means或其他後續分析）

### D74｜Primary Louvain結果與守恆（已確認）

- Reconstruction primary result：依finalized sum projection、remove-loop、weighted modularity、resolution=1與seed=42得到8個communities，Q=0.6344295412486247；2,782 nodes全部且只assign一次，community IDs連續為1–8。
- Observed in execution：獨立contribution sum=0.6344295412486246，與NetworkX Q在1e-12內一致；primary與完全相同設定重跑的partition fingerprint一致。

### D75｜Seed、projection與self-loop敏感度（已確認）

- Sensitivity result：seeds 7／19／73得到10／9／9群，Q只在0.636958–0.640464間，但相對primary ARI為0.552628–0.631930、NMI為0.721935–0.758982。Q穩定不等於membership穩定。
- Sensitivity result：max projection為9群、ARI 0.869371；unweighted為3群、ARI 0.228749；retain-loop為10群、ARI 0.674302。Flow weighting與self-loop policy都會實質影響partition。
- Reconstruction decision：seed 42仍為pre-registered primary，不因其他seed Q較高而替換。

### D76｜Resolution與報告比較（已確認）

- Sensitivity result：resolution 0.5／1.5分別得到5／12群；這只是scale sensitivity，不以接近報告11群選參數。
- Report result vs reconstruction：原報告約11群與0.66574；本重建8群標為materially different，Q差0.03131046、僅標為broadly similar numerically。因原implementation未知，不宣稱exact reproduction。

### D77｜Community語意與後續界線（已採用）

- Reconstruction decision：目前只稱network communities；代表站依既有SNA metric作描述，不命名為商業區、住宅區或通勤圈。Directed mobility flow與undirected modularity quantities分欄保存。
- Reconstruction decision：seed sensitivity是後續解讀的重要caveat，但沒有station assignment或數值完整性缺陷阻止Phase 7.0。下一個最小任務最多為K-means reconstruction contract，不自動執行。


## Phase 7.0 新增紀錄（2026-09-18；未在完整core dataset fit K-means）

### D78｜K-means feature set（已採用）

- Report-specified：p.23明列Weighted Degree、Betweenness、Clustering與PageRank四項變數；沒有指定Weighted Degree的in／out／total版本。
- Report-implied：p.24–25以Avg_Flow描述平均借還規模，支持整體flow語意但不足以證明原實作欄位。
- Reconstruction decision：使用Phase 5的`total_strength`、`betweenness_primary`、`clustering_primary`與`pagerank_primary`；不得加入Louvain ID、座標、city／district、bike type或其他features。

### D79｜Scaling、invalid與outlier policy（已採用）

- Observed in metrics：2,782 nodes四欄完整且finite；raw ranges跨多個數量級，total strength為1–1,723,023，clustering為0–1；betweenness skewness=11.7212。
- Implementation unspecified：報告未說standardization、normalization、log、imputation或outlier處理。
- Reconstruction decision：Primary使用StandardScaler，不做log、imputation、winsorization、trimming或outlier removal；invalid values與node grain不符一律fail closed。Log1p total strength只作sensitivity。

### D80｜KMeans與elbow contract（已採用）

- Report-specified：圖13可見k=1–10，文字以elbow支持k=4；k=4是report reference，不是重建acceptance target。
- Reconstruction decision：scikit-learn 1.8.0 `KMeans`、k-means++、n_init=50、max_iter=300、tol=1e-4、Lloyd、random_state=42。Elbow保存inertia curve，另以normalized point-to-chord maximum作deterministic diagnostic；silhouette只作k=2–10 secondary evidence。
- Reconstruction decision：不得更改scaling、range或seed使k=4更明顯。

### D81｜Labels、validation與後續界線（已採用）

- Reconstruction decision：Cluster依每群最小station ID升冪重新編1-based label；label無高低或功能語意。正式輸出須同時提供scaled及inverse-transformed centroids。
- Observed in validation：synthetic與12-row bounded real parameter validation通過；完整2,782 rows只做feature／scaling audit，沒有fit K-means。首次Unicode relabel與JSON NumPy bool相容性問題均fail closed並以最小修正解決。
- Reconstruction decision：下一個最小任務最多為Phase 7.1 full-core elbow與k=4 clustering；本階段不自動開始。


## Phase 7.1 新增紀錄（2026-09-18；full-core K-means已完成）

### D82｜Elbow與silhouette結果（已觀察）

- Report-specified：原報告以elbow採k=4；沒有提供silhouette selection。
- Observed in reconstruction：finalized StandardScaler contract下，deterministic knee=k=3；silhouette最高為k=2（0.561518），k=4為0.509820。
- Reconstruction decision：仍依report reference正式執行k=4，但不得寫成由本次diagnostic選出的最佳k；k-selection comparison為materially different。

### D83｜Primary k=4 partition（已採用）

- Observed in reconstruction：四群為60、347、939、1,436 nodes；2,782 nodes全數且只被指派一次。Primary inertia=3,518.353045，silhouette=0.509820。
- Reconstruction decision：Cluster IDs依群內最小station ID升冪重新編1–4，只作識別，不帶功能或高低語意。Feature-profile descriptive labels只依centroid／quantile描述。
- Observed in reconstruction：`total_strength`與`pagerank_primary` Pearson=0.951308；兩者不可解讀為完全獨立的雙重證據。

### D84｜Stability interpretation（已採用）

- Observed in reconstruction：seed 7／19相較seed 42只有一個邊界node改群，ARI=0.999306、NMI=0.997485；seed 73完全一致。Fixed seed 42重跑完全一致。
- Observed in reconstruction：no scaling、MinMax與log-strength sensitivity的ARI分別為0.515937、0.754273、0.646477，顯示partition對scaling有實質敏感性。
- Reconstruction decision：objective、size與membership stability分開回報；不同scaling space的inertia不得直接比較優劣。

### D85｜報告比較與後續界線（已採用）

- Report-specified：報告描述Role Group 2平均flow約61萬、Role Group 1平均clustering約0.752，但未提供可稽核的完整assignment、cluster sizes或centroids。
- Reconstruction decision：原報告Role Group不可直接映射到本次Cluster ID；除k值外，cluster result equivalence標記為cannot verify，不以報告數字反向調參。
- Reconstruction decision：Phase 7.1完成後停止；下一個最小任務最多為Phase 7.2 hierarchical clustering reconstruction contract，且不自動執行。


## Phase 7.2 新增紀錄（2026-09-18；未執行full hierarchical clustering）

### D86｜Hierarchical期間與分析grain（已確認）

- Report-specified：p.7與p.27兩處明載hierarchical期間為2022–2024；平日／假日分開、每小時建立SNA。這不是單一typo，期間分類為`clearly_2022_2024`。
- Report-specified：每站彙整Betweenness、Eigenvector、PageRank共72變數；附錄Figures 45–52亦呈現兩套dendrogram及三項centrality逐時趨勢。
- Reconstruction decision：不得用現有2023–2024全期間node metrics冒充此分析；目標grain為每個day type各一份station×72 matrix。

### D87｜Distance、linkage、scaling與cut（已採用／待執行）

- Report-specified：Euclidean distance＋Ward.D2；附錄plot label支持R `hclust` family，但R版本與code未知。
- Report-specified output：Figure 45平日顯示5群、Figure 49假日顯示4群；exact cut height／function unspecified。
- Implementation unspecified：scaling、centrality direction／weight／self-loop版本、missing／outlier處理。
- Reconstruction decision：Primary以SciPy 1.17.1 Ward／Euclidean及StandardScaler；不impute、不刪outlier。平日fixed maxclust=5、假日=4；labels依群內最小station ID重編。

### D88｜2022 raw availability與execution blocker（已確認）

- Observed in source index：2022/01–12共12個官方ZIP URL，無缺月／重複；既有HEAD inventory皆HTTP 200。
- Observed in sampled raw data：2022/01與12皆為UTF-8 strict、6欄＋header；既有parser完整讀至EOF為1,371,395及2,628,740 records，均`v1_6col`且0 warnings。其餘10個月尚未內容驗證。
- Observed in processed data：目前沒有2022 cleaned、OD、逐時SNA或station×72 matrices。
- Reconstruction decision：readiness為blocked；下一個任務必須先做2022 network reconstruction extension，不得直接執行report-complete hierarchical clustering。

### D89｜K-means comparison與dendrogram邊界（已採用）

- Report-implied：Ward與K-means概念相似；未說hierarchical是K=4 validation。
- Reconstruction decision：因期間、features與群數不同，現階段禁止直接比較membership ARI／NMI。只有母體與feature contract一致才允許ARI、NMI及cross-tab。
- Reconstruction decision：正式執行須保存full linkage matrix、full leaf order sidecar及hash；顯示圖可隱藏全部站名，但抽樣不得冒充full hierarchy。Cophenetic correlation只作secondary diagnostic。


## Phase 7.3 新增紀錄（2026-09-18；hourly SNA features已完成，未執行hierarchical clustering）

### D90｜Hierarchical reconstruction period override（分析者決策）

- Report-specified：p.7與p.27仍明載2022–2024；Phase 7.2對原文的判讀不撤回。
- Analyst reconstruction decision：分析者明確將此視為報告內部期間不一致／筆誤，hierarchical reconstruction改採核心network period 2023–2024，不補跑2022。
- Limitation：後續分群只能稱為2023–2024 reconstruction variant，不得宣稱完全重現報告所寫的2022–2024母體。

### D91｜Calendar與day-type contract（已採用）

- Analyst-provided source：唯一calendar來源為`2020_2025假日.fst`，SHA-256=`a10889e9a656d9f9c06975f0e1adb36b3b6d93955365bd91fc49308a2dd37bc5`。
- Observed in calendar：`Date`為R Date；`IsHoliday`、`NaturalDisaster`為numeric 0/1。2023–2024共731天，無缺日／重複／未知IsHoliday；233 holiday、498 weekday、6 NaturalDisaster days。
- Reconstruction decision：`IsHoliday==1`為holiday、0為weekday；NaturalDisaster只作QA，不覆寫day type。禁止weekday heuristic或自建假日表。

### D92｜Hourly graph、station universe與metrics（已採用）

- Reconstruction decision：48個graph固定使用core primary OD union的2,782 nodes；inactive Betweenness與Eigenvector為0，PageRank在full-node graph保留uniform teleportation／dangling mass。
- Reconstruction decision inherited from network-metric-contract-v1：Betweenness為directed、unweighted、normalized、endpoints=False、self-loop excluded、exact；Eigenvector為directed left／unweighted／self-loop excluded；PageRank為directed、trip-count weighted、alpha=0.85、uniform、self-loop retained。
- Implementation decision：exact Betweenness採python-igraph 0.11.9編譯型Brandes，依directed NetworkX normalization縮放；synthetic及兩個real gate buckets與NetworkX逐站最大絕對差0.0。不得解讀為approximation。

### D93｜Phase 7.3 outputs與下一步界線（已完成）

- Observed in reconstruction：91,138,763筆全部且只進一個day-type×hour bucket；weekday=66,096,385、holiday=25,042,378。Repeated identical records全部保留。
- Observed in reconstruction：48/48 exact Betweenness完成、48/48 Eigenvector收斂、48/48 PageRank通過sum-to-one；兩份2,782×72 matrices無NaN／Inf且未scaling。
- Reconstruction decision：Phase 7.3完成後停止；下一個最小任務最多為Phase 7.4 StandardScaler＋Ward.D2 clustering與dendrogram，不自動執行。


## Phase 7.4 新增紀錄（2026-09-18；hierarchical reconstruction已完成）

### D94｜Primary Ward reconstruction（已完成）

- Analyst reconstruction decision：本次仍為2023–2024 variant；原報告2022–2024文字與期間限制持續保留。
- Reconstruction decision：weekday／holiday分別fit StandardScaler，使用Euclidean＋SciPy 1.17.1 Ward；不宣稱與未知R `ward.D2`環境bit-identical。
- Observed：兩份linkage皆為2,781×4、finite、distance單調、final merge count=2,782；cophenetic correlation為weekday 0.642493、holiday 0.642285。

### D95｜Report-reference cuts與outlier retention（已完成）

- Report-specified output：附錄weekday顯示5群、holiday顯示4群；此群數不是scaler／linkage optimization target。
- Observed：weekday sizes=45／550／767／1,419／1；holiday sizes=65／537／2,179／1。`500103044`在兩者皆為單站群。
- Reconstruction decision：單站群保留並描述為極端network-role pattern，不視為錯誤、不移除、不反向調整方法。

### D96｜Sensitivity與跨日型比較（已觀察）

- Observed：complete／average相對Ward primary之ARI皆低於0.04；no-scaling ARI為weekday 0.514025、holiday 0.620627，顯示linkage與scaling sensitivity實質存在。
- Observed：weekday k=5與holiday k=4的ARI=0.381598、NMI=0.456015；因群數不同，只作exploratory membership comparison，不期待一對一群對應。
- Reconstruction decision：cophenetic correlation不作method selection；不得因complete／average數值較高而取代report-specified Ward.D2。

### D97｜Reproducibility與後續界線（已完成）

- Observed：weekday／holiday重算的linkage、leaf order與assignment hashes完全一致；full dendrogram均涵蓋2,782 leaves。
- Reconstruction decision：prototype只代表距standardized centroid最近，不代表重要性；群組只用客觀72-feature pattern描述，不自行命名功能類型。
- Reconstruction decision：Phase 7.4完成後停止；下一個最小任務最多為Phase 8.0 BRouter／road-segment routing reconstruction contract，不自動執行routing或事故分析。


## Phase 8.0 新增紀錄（2026-09-18；road-routing contract）

### D98｜Routing universe與self-loop（契約已定、尚未full routing）

- Report-specified：R p.29以BRouter Trekking模擬各起訖點，將旅次流量權重賦予路徑並加總重疊路段；R p.44只稱預設路徑。報告未列送路由OD集合與self-loop政策。
- Reconstruction decision：`road-routing-contract-v1`使用core 2023–2024、`od-inclusion-policy-v1`的unique directed OD pairs；1,504個self-loop edges／6,023,568 trips不送路由但明確列帳。非self routing universe為1,124,015 edges／85,115,195 trips。

### D99｜Station coordinate contract（BLOCKED）

- Observed：2,782 IDs中1,384個有2024-05-31保存快照座標；31個在2024與2026快照間座標衝突；1,367個只有2026 current coordinate。沒有all-source missing、bounds violation或7-decimal exact-coordinate duplicates。
- Reconstruction decision：只以exact station ID join；dated snapshot優先，conflict fail closed；current-only不得被寫成historically valid。禁止名稱geocoding、平均座標或靜默選最新值。

### D100｜BRouter、graph與profile identity（已固定並通過bounded validation）

- Current official metadata：官方BRouter release／repository顯示v1.7.10、tagged `trekking.brf`、本地server與5°×5° `.rd5` tiles；2026-09-18官方index顯示臺北範圍需`E120_N20`與`E120_N25`。
- Implementation unspecified in report：原報告沒有BRouter版本、profile版本、OSM／`.rd5` snapshot、routing日期、snapping或failure policy。
- Reconstruction decision：正式執行只接受hash固定的local BRouter v1.7.10、未修改tagged Trekking profile與兩個graph tiles。release ZIP、JAR、profile與兩個tiles均已hash固定；公共線上endpoint未使用。
- Reconstruction limitation：Road topology may differ from the graph available to the original study.

### D101｜Directed segment、flow與cache contract（已定義、待真實sample驗證）

- Reconstruction decision：reciprocal OD獨立routing。優先graph-native edge ID；標準GeoJSON若無stable edge ID，fallback為六位小數fixed serialization的ordered adjacent coordinate pair，反向為不同segment。
- Reconstruction decision：每次segment traversal累加完整OD `trip_count`，同route重複通過同segment按次累加；不得除以segment數。Cache key涵蓋IDs、coordinates、BRouter、graph、profile與contract，且resume須再驗output hash。
- Observed in bounded execution：20個non-self routes重跑之status、distance與canonical geometry hash完全一致；sample內未見同route重複directed segment。這支持sample上的determinism，但不把geometry key宣稱成graph-native ID。

### D102｜Phase 8.0 readiness（BLOCKED）

- Observed：deterministic 20個non-self＋1個self-loop sample已完成兩次；20/20成功、454,883 sample trip weight全覆蓋、最大snap offset 16.410m、route hash／distance完全一致。單worker估計約15.8–92.3小時，raw GeoJSON約6.03GiB，僅為sample extrapolation。
- Reconstruction decision：環境blocker已解除，但31個coordinate conflicts及1,367個current-only temporal-unresolved coordinates仍不符合full-routing coordinate contract。狀態改為`ROAD ROUTING: BLOCKED — STATION COORDINATES UNRESOLVED`。
- Reconstruction decision：本階段沒有全量routing、road-flow aggregation或accident matching；下一個任務只能解決station-coordinate historical validity blocker。

## Phase 8.0A 新增紀錄（2026-09-19；historical coordinate resolution）

### D103｜Historical evidence tier與temporal coverage

- Current official metadata：臺北與新北官方公開頁目前列出的資源是即時站點介面；TDX文件顯示站點函式可用日期參數查歷史資料，但需要個人API憑證。本階段沒有憑證，也沒有把文件範例當成已取得資料。
- Observed：以project-preserved 2024-05-31 Taipei official-feed capture、2026 Taipei current及2026 New Taipei current建立4,193-row ledger。2,782 core nodes中只有5個station的observed interval被相同座標前後夾住；2,777個仍未完整覆蓋。
- Reconstruction decision：Tier 1 direct historical與Tier 2 temporally bracketed才可接受；Tier 3 single-sided、current-only與change date不明的conflict均fail closed。Exact station ID是唯一identity key，距離只作QA。

### D104｜Conflict與coordinate era

- Observed：31個2024／2026 conflicts位移p50=59.190m、p95=155.299m、max=207.544m；全數缺少變更日期。現有證據未建立precision-only、after-period relocation或within-period relocation。
- Reconstruction decision：31個全數維持`unresolved_conflict`；不得靠距離或站名自動裁決。Within-period relocation count記為0只表示「尚未建立」，不可寫成不存在。現在不建立eras；若後續證據建立period內搬站，routing unit必須升級為OD × coordinate-era並bump contract v2。

### D105｜Phase 8.0A readiness（仍BLOCKED）

- Observed：accepted artifact有5 nodes（0.1797%），但其間沒有non-self OD，因此edge與trip-weight coverage皆為0。Current-only 1,367個中New Taipei 1,276、Taipei 91；沒有一個取得新增historical support。
- Reconstruction decision：`HISTORICAL COORDINATES: PARTIALLY RESOLVED — ROAD ROUTING STILL BLOCKED`。沒有執行full routing；下一個任務只能取得dated 2023/2024 official station metadata，優先是TDX歷史站點匯出或兩市正式歷史快照。

## Phase 8.0B 新增紀錄（2026-09-19；legacy coordinate recovery）

### D106｜Legacy source provenance與encoding

- Observed in raw data：`active_station_all.csv`有64,413 rows、7,322,758 bytes、27個月份；strict UTF-8失敗，含106 illegal bytes／75 affected records。Repository、Git history與exact filename web search均未找到產生程式或官方source。
- Reconstruction decision：以UTF-8 `surrogateescape`及exact field Base64無損解析；raw file不修改。Source authority固定為`provenance_unverified_supporting_only`，不得提升Tier 1。

### D107｜Legacy identity mapping

- Observed in raw data：`站點編號`沒有任何`500xxxxxx`值；有效座標rows中它與站名相同。3,015 legacy names中1,411以historical exact name、1,358以trip-name exact evidence唯一接回，共2,769 canonical IDs；0 alias、0 ambiguous、246 unmatched。
- Reconstruction decision：只有exact既有identity／versioned alias可建立mapping；current-only、fuzzy、substring、nearest coordinate與suffix stripping均不可auto-accept。

### D108｜Static-coordinate backfill risk

- Observed in raw data：2,769 mapped IDs跨月全部只有一組exact coordinate；31 conflicts中20個legacy timeline等於2026位置、8個等於2024位置、3個皆非。
- Reconstruction inference：資料形狀較像monthly active-name list事後join靜態座標，而非逐月official snapshots。因缺產生程式，這不能寫成已確認流程，但足以阻止把month當coordinate validity。
- Reconstruction decision：不確認within-period relocation、不建立eras、不升routing contract v2。

### D109｜Phase 8.0B readiness

- Observed：1,367 current-only中1,358可identity-map、1,352具完整legacy monthly support；New Taipei分別為1,267／1,262。但來源門檻未通過，routing-ready仍5 nodes、0 edges、0 trips。
- Reconstruction decision：狀態為`LEGACY HISTORICAL COORDINATES: NOT SUFFICIENTLY TRACEABLE`；不執行Phase 8.1。下一個任務只能針對remaining provenance與unmatched／ambiguous historical identity blockers。

## Phase 8.0C 新增紀錄（2026-09-19；analyst override與routing coordinate finalization）

### D110｜Legacy monthly coordinate analyst override

- Affected stage：Phase 8.0C及其後road routing。Evidence limitation：`active_station_all.csv`的官方upstream未驗證，可能是事後static coordinate lookup回填；D106–D109與`NOT SUFFICIENTLY TRACEABLE`結論不變。
- Analyst reconstruction assumption：只為完成本次重建，將exact-mapped legacy monthly record所附coordinate視為該月routing coordinate。`evidence_status=supporting_unverified_provenance`與`routing_acceptance=accepted_by_analyst_assumption`分欄保存；不得描述成verified historical fact或Tier 1。
- Rationale：exact station identity coverage足以提供 operational reconstruction value，而provenance不確定性以顯式假設揭露，不以事實口吻隱藏。
- Downstream consequence：Phase 8.1只能讀固定artifact，不得重新查current API；所有排除需保留edge／trip denominator。Reversibility：未來取得verified 2023–2024 metadata時，保留本decision與raw source，產生新版artifact、比較差異、使受影響route cache失效並重跑受影響OD。

### D111｜Coordinate precedence、conflicts與時間精度

- Reconstruction decision：precedence為verified direct historical evidence → legacy monthly coordinate under D110 → existing accepted temporally bracketed coordinate → unresolved；current-only不得偷偷fallback。
- Observed in reconstruction：2,769 identity-mapped core IDs中2,756具有有效legacy coordinate；13個mapped IDs所有legacy coordinate皆缺失。31個舊conflicts中28個以analyst assumption接受且保留flag，3個因legacy coordinate全缺而保留unresolved。31/31仍在provenance accounting。
- Reconstruction decision：month只解釋為`YYYY-MM`，不虛構日級validity。Accepted source內2,756站皆只觀察到一組exact coordinate，故collapse為single stable routing coordinate；只能陳述「accepted legacy source未觀察到period內coordinate change」，不可陳述「沒有搬站」。

### D112｜Final coordinate coverage與disclosed exclusions

- Observed：final artifact涵蓋2,756/2,782 nodes（99.0654%）；可route 1,100,919/1,124,015 non-self OD（97.9452%）及83,693,979/85,115,195 trips（98.3302%）。26 nodes、23,096 OD、1,421,216 trips保留unroutable；self-loop仍為1,504 edges／6,023,568 trips且不送BRouter。
- Reconstruction decision：這些排除並未被證明沒有系統性偏誤；Phase 8.1必須並列routed與unroutable denominators並揭露26站集中性。Observation boundary不變：資料不代表完整New Taipei-origin YouBike population。

### D113｜Routing contract v1.1與readiness

- Reconstruction decision：routing unit仍是unique directed OD pair、沒有coordinate eras，因此不升為era-routing v2；coordinate acceptance、immutable artifact與cache identity發生實質變更，contract以相容性小版本升為`road-routing-contract-v1.1`。
- Reconstruction decision：狀態為`ROUTING COORDINATES FINALIZED — PHASE 8.1 READY WITH DISCLOSED EXCLUSIONS`。這不是任意coverage threshold；理由是所有缺口已逐OD保存、流量分母明確、沒有未處理era問題，且contract允許failure/unroutable accounting。Phase 8.0C沒有執行BRouter全量路由。

## Phase 8.1A 新增紀錄（2026-09-19；production routing gate）

### D114｜Production manifest與day-type weights

- Reconstruction decision：routing unit維持unique directed OD pair；geometry只route一次，total／weekday／holiday是同一geometry的三組flow weights。
- Observed：manifest精確為1,100,919 routes／83,693,979 trips；Phase 7.3 authoritative buckets聚合得weekday 61,065,093、holiday 22,628,886，逐OD與全域皆exact decomposition。Self-loop與23,096 coordinate-gap edges都不進manifest。

### D115｜Cache、resume與storage contract

- Reconstruction decision：使用SQLite WAL compressed payload cache，per-route保存cache key、content hash、terminal status與routing environment；batch以transaction atomic commit，progress以temporary＋atomic replace。Manifest採Parquet batch streaming，不建立1.1M散落GeoJSON。
- Reconstruction decision：geometry cache identity不含weights，但含coordinates、BRouter、profile、RD5、contract、coordinate artifact與routing parameters；weights變動只refresh record metadata。Retry只限timeout／BRouter process errors且最多3次，沒有fallback engine。

### D116｜Worker selection與工程估計

- Observed：隔離100-route benchmarks的1／2／4 workers吞吐為8.0750／7.4756／9.1283 routes/sec，全部0 errors；4 workers throughput最高，雖per-route latency顯示contention，仍無failure regression，故選4。
- Reconstruction estimate：full run optimistic／central／conservative為29.13／33.50／47.86小時；disk central／conservative為4.05／6.16 GB。這是sample projection，不是完成保證；preflight要求8 GiB free disk。

### D117｜Production Gate readiness

- Observed：1,000-route gate全success；rerun 1,000/1,000 cache hits且0 executions；interruption/resume、48,989-segment extraction、OD／trip／day-type守恆均通過。整階段actual BRouter executions=1,320，未超過5,000。
- Reconstruction decision：`PHASE 8.1A COMPLETE — LOCAL FULL ROUTING READY`。Full run必須由使用者在Phase 8.1B以explicit flag於本機terminal啟動；本階段`full_routing_executed=false`。

## Phase 8.1B-M 新增紀錄（2026-09-19；cloud migration bundle）

### D118｜最小cloud runtime payload

- Observed：production runner執行期直接依賴三支Python modules、三份versioned config／contract、production manifest、final coordinate與core OD artifacts，以及hash固定的BRouter JAR、Trekking profile與兩個RD5。月租借raw data、notebooks、Git objects與舊分析輸出不是resume所需runtime inputs。
- Reconstruction decision：cloud bundle只封裝上述執行依賴、最小Python requirements、Linux launcher、provenance receipts／runbook，以及一份可驗證的cache快照；不納入raw trip data或無關作品集檔案。

### D119｜Live cache snapshot與migration界線

- Observed：production cache使用SQLite WAL；直接複製單一database file可能無法包含打包瞬間仍在WAL中的一致狀態。
- Reconstruction decision：live packaging只准透過read-only source connection的SQLite online backup API產生獨立一致快照，並以`PRAGMA integrity_check`、status counts、schema hash與檔案hash驗證。不得複製live WAL／SHM，也不得停止、signal、restart或修改目前production job。
- Reconstruction limitation：bundle內cache是point-in-time snapshot；若未來正式切換到cloud，需在受控停止後依同一程序重建final snapshot，避免遺漏打包後新增的routes。

## Phase 8.1B-M2 新增紀錄（2026-09-19；migration hardening）

### D120｜BRouter runtime dependency與real-route preflight

- Observed in deployment：原bundle缺`lookups.dat`與canonical RD5 runtime filenames；RouteServer socket可連線，但route分別因lookup與graph filename錯誤失敗。這證明socket-only preflight會false positive，原M結果保留為當時本機audit結論而非事後改寫。
- Reconstruction decision：`lookups.dat`以SHA-256 `bf8fc3b2c052b7204e9c5a8d78e4d6ab6b125d3236a943f34583b838c477f419`列為locked dependency；dated RD5仍是唯一hash-locked payload，canonical names由Linux launcher以validated relative symlink重建。Preflight必須執行Phase 8.1A已成功route並用production parser驗證，不寫cache／progress。
- Engineering decision：HTTP error body最多保存4,096 bytes並以UTF-8 replacement解碼，只改善可診斷性，不改route classification或retry policy。

### D121｜Cloud benchmark與execution environment選擇

- Observed：Google Cloud `e2-standard-2` Spot（Debian 13、2 vCPU／8 GB）1 worker為4.7039979 routes/s、2 workers為6.1726190 routes/s；兩組皆1,000/1,000成功且0 cache hit。既有本機i5-12500 sample約為1 worker 8.075、4 workers 9.128 routes/s。
- Reconstruction decision：此特定VM／workload／configuration的validated throughput實質較慢，故不選`e2-standard-2`承接Phase 8.1B full production；本機production繼續authoritative。這不是「cloud VMs一般較慢」的主張，也沒有啟動full cloud production。

## Phase 8.1C 新增紀錄（2026-09-21；production closeout）

### D122｜Final production authority與完成狀態

- Runtime observation：manifest、SQLite cache與final progress皆為1,100,919 routes；cache僅含1,100,919 success，0 failure／0 remaining，successful trip weight為83,693,979。348,100 cache hits＋752,819 executions精確等於manifest routes。逐筆route ID／cache key／content hash／trip weight validation為0 invalid，SQLite integrity為`ok`。
- Reconstruction decision：通過identity與content validation的SQLite current route states是production completion authority；progress只作一致性cross-check。狀態為`PHASE 8.1 ROUTING PRODUCTION: COMPLETE`，但這不授權Phase 8.2。

### D123｜Runtime incidents與resume evidence

- Runtime observation：較早BRouter service曾停止監聽並留下1,646個retryable `brouter_error`；精確消失原因未建立，不作推測。Windows canonical RD5 names缺失則由preflight明確建立，Windows以hash相同的NTFS hard links修復；Linux launcher沿用validated symlinks。
- Runtime observation：1,646 records在service恢復後全數成功重算。其後Windows Update由Event ID 1074／6006證實為planned restart，沒有觀察到Kernel-Power 41／6008；348,100 cached successes於重啟後復用並完成全量，構成實際resume-safety驗證。

### D124｜Retry state transition accounting

- Observed defect：舊runner從cache載入retryable failure後，重算成功只累加success而未扣除同route舊failure，造成top-level counters暫時同時包含historical failure與current success；cache current state始終是authority。
- Engineering decision：summary改以validated per-route `old state → new state` transition更新status counts及success／failure weights；initial counters忽略corrupt／unknown payload。Terminal／retryable分類、routing、retry、WAL、Ctrl+C與preflight semantics不變。

## Phase 8.2 新增紀錄（2026-09-21；directed road-segment usage）

### D125｜有向路段識別與儲存契約

- Reconstruction decision：`directed-segment-usage-v1`以相鄰canonical座標的有序pair作segment identity；經緯度固定六位小數並以`int32` microdegrees儲存，A→B與B→A分離。所有計數與權重使用`int64`。
- Engineering decision：以獨立on-disk SQLite composite-key UPSERT分塊累加，再排序、streaming寫出Zstd Parquet；production route cache全程read-only。大型work DB與Parquet保持Git ignored。

### D126｜Traversal、unique route與權重語意

- Reconstruction decision：同一路線重複通過同一有向segment時，每次traversal都保留並各自傳遞total／weekday／holiday OD權重；`unique_route_count`則每route–segment最多計一次。不得route-level deduplicate。
- Reconstruction decision：相鄰點在六位小數canonicalization後相同時先collapse，避免zero-length segment；若整條success route剩不到兩個distinct canonical points則fail closed。Production cache只保留已驗證canonical segments，原始GeoJSON full-precision points不在本階段反向虛構。

### D127｜Phase 8.2完成與解讀邊界

- Runtime observation：1,100,919條success routes聚合為149,234個唯一有向segments與195,336,834次有效traversal；加權總和為total 4,674,227,848、weekday 3,307,530,105、holiday 1,366,697,743。逐segment與全域守恆、composite-key唯一性及獨立Parquet重讀均通過。
- Reconstruction limitation：這些值是BRouter模擬路徑上的使用量／暴露量，不是GPS實測自行車流量，也不是事故風險分數。Phase 8.3事故配對、EPDO與CBI均未開始。

## Phase 8.3A 新增紀錄（2026-09-22；accident and road-reference audit）

### D128｜事故資料grain與identifier

- FACT：112／113年明細分別有56,139／51,810列；欄位含`當事人序號`與逐當事人車種、性別、年齡、傷勢及行為，因此row grain是party-level，不是one row per accident。兩檔均沒有明確可靠accident ID。
- Reconstruction decision：日期時間＋地點＋座標只能作heuristic grouping evidence，不得在沒有另行核准的entity contract前成為正式accident ID或事故件數。

### D129｜事故座標與年度schema

- FACT：112／113年完整座標率為99.9947%／99.9961%，其數值落在臺北longitude／latitude範圍；官方metadata只稱X/Y座標點位，沒有明載CRS。112有`光線`、`旅次目的`，113改見`道路照明設備`，不可blind stack。
- Reconstruction decision：事故座標暫列`WGS84 / EPSG:4326 candidate`，不得在正式空間配對前寫成confirmed CRS；`光線`與`道路照明設備`也不得未經codebook證據直接視為alias。

### D130｜道路reference scope與field limitations

- FACT：`8mroadup`含完整Shapefile components，13,419 features全為Polygon；`.prj`確認TWD97 / TM2 zone 121（EPSG:3826）。`ROAD_ID`有1筆空白，其餘13,418個非空值唯一。官方來源明確只涵蓋寬度超過8公尺道路。
- UNRESOLVED：`TT`／`INTERSECT`缺正式field semantics；binary structural geometry checks為0 invalid，但full OGC topology validity未由topology engine驗證。不得把road polygons描述成centreline或完整臺北道路universe。

### D131｜Phase 8.3B與EPDO readiness

- FACT：兩年均有死亡、2–30日死亡、受傷人數及party-level受傷程度，但沒有正式accident ID、財損欄位或已證實A3 population。
- Reconstruction decision：Phase 8.3A audit完成；Phase 8.3B維持BLOCKED，直到事故CRS、accident entity contract及>8 m道路coverage policy獲得明確證據／分析者決策。不得在此之前設定距離門檻或計算EPDO、CBI與風險排名。

## Phase 8.3A-2 新增紀錄（2026-09-23；accident entity reconstruction）

### D132｜Spot-map candidate backbone與exact crosswalk

- FACT：112／113年斑點圖各有24,272／22,368列、固定5欄、CP950 strict decoding；兩年各有1筆完全重複spot row，因此raw spot row不能無條件視為唯一事故。
- Reconstruction decision：primary key固定為exact minute datetime＋比較用NFC／outer-trim地點＋exact numeric decimal X/Y。只有1 spot candidate對1 party group且內容一致時才建立事故實體；不得使用row order、coordinate rounding、fuzzy／substring／nearest match或forced tie-break。
- Observed：exact 1:1為2023年24,220件、2024年22,366件，合計46,586件；另有50個unmatched spot keys、111個unmatched party groups及2個duplicate spot keys，全部保留在crosswalk而非猜測處理。

### D133｜Reconstructed ID與severity promotion

- Reconstruction decision：事故ID為`reconstructed_accident_`加canonical event key compact UTF-8 JSON的SHA-256；它是deterministic reconstruction artifact，不是官方accident ID，也不依source row order。
- Reconstruction decision：`死亡人數`、`2-30日死亡人數`、`受傷人數`只有在accepted group內每筆party record一致時才提升一次；全空白保留missing，混合或不一致則fail closed。Repeated party rows不得直接加總。
- Observed：Phase 8.3A唯一severity-conflict party group位於2023 duplicate spot key，故維持ambiguous exclusion；沒有修復或以row order裁決。Accepted entities中11件severity missing、2件保留party-sequence quality flag。

### D134｜事故CRS analyst assumption

- FACT：原始事故檔與既有官方metadata沒有明載EPSG code；Phase 8.3A只建立WGS84 longitude／latitude的高信心candidate。
- Assumption：為本次reconstruction，將事故X/Y operationally視為WGS84 longitude／latitude（EPSG:4326）；這不是verified source fact。轉EPSG:3826後與>8 m道路reference bbox重疊只作study-area sanity check，不構成道路配對證據。
- Reconstruction decision：若後續取得authoritative CRS metadata，需保留本assumption、比較結果並使受影響空間產物失效；不得把assumption回寫成原始資料事實。

### D135｜Phase 8.3B readiness與coverage界線

- Observed：46,586個accepted entities皆有唯一非空reconstructed ID；crosswalk共46,749列且所有unmatched／ambiguous狀態均machine-readable。兩年handling type與promoted severity的一致性檢查未見衝突。
- Reconstruction decision：事故entity blocker對exact 1:1 subset已解除，狀態為`PHASE 8.3B READY WITH DISCLOSED EXCLUSIONS`。後續必須並列50／111／2類排除、CRS assumption及>8 m road coverage limitation；不得silent drop或將outside-reference事故當成不存在。
- Scope boundary：Phase 8.3A-2沒有執行point-in-polygon、nearest-road、BRouter segment matching、distance-threshold selection、EPDO、CBI或risk ranking。

## Phase 8.3B 新增紀錄（2026-09-24；accident-to-road reference coverage validation）

### D136｜OGC validity與boundary semantics

- FACT：locked `Road.shp`有13,419個EPSG:3826 Polygon；Shapely完整OGC validation結果為13,419 valid、0 invalid、0 empty。13,418個非空`ROAD_ID`唯一，另有1個blank `ROAD_ID`；未做任何geometry repair。
- Analytical decision：containment以`polygon.covers(point)`判斷，boundary point視為covered。候選排序deterministic；不得依spatial-index traversal、first match、`TT`、`INTERSECT`、`ROADWIDTH`、`ROADNAME`或polygon area選winner。

### D137｜CRS、缺座標與coverage denominator

- Reconstruction assumption：事故X/Y繼續operationally視為EPSG:4326，先轉EPSG:3826再做所有polygon及meter distance運算；此EPSG判斷不是source metadata fact。
- Observed：46,586個accepted entities中1件X/Y皆空白。它保留為`coordinate_unavailable`，不虛構座標也不歸入`contained_zero`；spatially evaluable denominator為46,585，完整artifact仍維持46,586列守恆。
- Observed：37,884件`contained_unique`、0件`contained_multiple`、8,701件`contained_zero`。Unique中37,859件polygon有valid `ROAD_ID`，25件落在blank-ID polygon；geometry coverage與identifiable-road coverage必須分開。

### D138｜Nearest-distance evidence不是matching policy

- Observed：8,701件outside points的nearest distance p50／p90／p95／p99為37.6753／138.5570／256.7226／922.6797 m；second-nearest p50為51.8622 m，gap p50為5.3293 m，30件具有exact nearest-distance tie。
- Analytical decision：1／3／5／10／20／30／50 m只作descriptive sensitivity bins。本階段不選threshold、不assign nearest road、不建立confidence class，也不以道路名稱或未定義欄位補判。
- Reconstruction limitation：`contained_zero`只表示outside this >8 m road reference coverage，不代表事故錯誤、不在道路上或應刪除；後續不得silent drop，因其占spatially evaluable accidents 18.6777%。

### D139｜Phase 8.3C readiness與硬邊界

- Observed：相同輸入重跑完全重現containment counts、candidate sets、distance values、QA sample與Parquet hash；100個deterministic outside points的full Cartesian QA也精確重現nearest及second-nearest distance。
- Analytical decision：狀態為`PHASE 8.3C READY FOR HUMAN POLICY DECISION WITH DISCLOSED COVERAGE LIMITATIONS`。這只表示已有足夠evidence供人類決定nearest fallback、threshold、blank-ID與outside-reference policy，不代表任何政策已選定。
- Scope boundary：Phase 8.3B沒有正式`assigned_road_id`、Phase 8.2 flow join、事故到BRouter segment matching、EPDO、CBI、risk score或hotspot ranking。

## Phase 8.3C 新增紀錄（2026-09-24；accident road-context finalization）

### D140｜正式road-context controlled vocabulary

- Analytical decision：固定五種狀態為`contained_valid_road`、`contained_blank_road_id`、`outside_reference_coverage`、`coordinate_unavailable`、`contained_multiple`。只有direct unique polygon coverage且nonblank `ROAD_ID`才是可辨識road context。
- Observed：正式件數為37,859／25／8,701／1／0，精確合計46,586；canonical ID set與Phase 8.3A-2完全相同，沒有drop、duplicate、regenerate或補回既有exclusions。
- Reconstruction decision：blank-ID不得用ROADNAME、row number、geometry hash或nearest valid polygon生成替代ID；`contained_multiple`即使未來出現也不得first-match或依ROADWIDTH／ROADNAME／TT裁決。

### D141｜不採general nearest-road fallback

- Analytical decision：nearest-road fallback正式disabled，distance threshold為none。Phase 8.3B的1／3／5／10／20／30／50 m bins只是diagnostic sensitivity evidence，不進canonical road-context schema。
- Rationale：8,701件outside points的nearest distance P50／P75／P90為37.6753／74.0675／138.5570 m，只有1,521件在5 m內；加上Road.shp只涵蓋>8 m道路，強迫配到最近included road會把reference coverage缺口變成false precision。
- Limitation：上述證據不表示所有outside points一定位於小路；正式語意只是不被本研究採用的>8 m官方road-polygon reference覆蓋。

### D142｜Road context與BRouter flow角色分離

- FACT：Road.shp是EPSG:3826；事故EPSG:4326仍是明確reconstruction assumption，不得改寫成source fact。`TT`／`INTERSECT`語意仍UNRESOLVED且未使用。
- Analytical decision：Road.shp只提供事故的physical road context；Phase 8.2的149,234個有向BRouter segments仍是estimated bicycle-flow layer。Phase 8.3C不join flow、不aggregate至ROAD_ID，也不替換BRouter geometry。

### D143｜Phase 8.4 interface readiness

- Reconstruction decision：`contained_valid_road`未來可作BRouter candidate的road-context constraint；blank-ID需獨立政策；outside-reference不可排除且未來可在沒有Road.shp constraint下進candidate policy；缺座標則需另行geocoding contract。
- Readiness：`PHASE 8.4 READY WITH FORMAL ROAD-CONTEXT STATES AND DISCLOSED REFERENCE LIMITATIONS`只代表interface ready。Phase 8.4、事故至BRouter segment matching、EPDO、CBI與risk analysis均未開始。

## Phase 8.4A 新增紀錄（2026-09-24；accident-to-BRouter candidate validation）

### D144｜事故候選搜尋採方向中立 physical microsegment view

- Observed：Phase 8.2 的149,234個有向segments依兩端點整數microdegree tuple無方向化後，形成106,049個physical segments；62,864個只有單方向member、43,185個同時有正反方向member，沒有>2或同方向重複的unexpected multiplicity。
- Analytical design：事故缺乏可靠行進方向，因此空間候選搜尋使用lexicographically canonicalized direction-neutral microsegment；Phase 8.2原始有向flow與方向member metadata維持不變。
- Unresolved：事故無方向資訊時是否將A→B與B→A flow合併成正式direction-neutral exposure，留待後續分析者決策。本階段不得先行建立雙向風險分母。

### D145｜Road-context constraint只定義候選集合

- Analytical design：`contained_valid_road`與可重建stable feature identity的`contained_blank_road_id`，以`LineString.intersects(Road polygon)`建立constrained candidate set；包含segment位於、穿越或接觸polygon，不能改成midpoint或endpoint containment。valid `ROAD_ID`必須唯一回查polygon，multiple context一律fail closed。
- Observed：37,859件valid-road事故中35,290件global/context最近候選相同、1,328件不同、1,241件context set為空；25件blank-ID事故均可重用Phase 8.3B feature identity且global/context最近候選相同。
- Analytical limitation：candidate不同不表示global或context任一方錯誤；context-empty也不得silent drop。上述證據只供後續選定matching policy。

### D146｜距離、ties與流量的界線

- Analytical design：距離固定為EPSG:3826事故Point至direction-neutral LineString的最小公尺距離；nearest與second-nearest必須是不同physical key。exact ties完整保存，0.1／0.5／1／2／5 m gap只作descriptive sensitivity。
- Observed：46,585件可評估事故global nearest P50／P90／P95／P99為2.4057／13.8594／35.5169／857.6740 m；988件有exact minimum-distance ties。200件deterministic full Cartesian QA與STRtree結果完全一致。
- Reconstruction decision：Phase 8.4A不設定distance threshold、不建立`assigned_segment_id`或success match status，也不讀取total／weekday／holiday flow來排序、解tie或決定confidence。

### D147｜Phase 8.4B readiness僅限政策決定

- Readiness：`PHASE 8.4B READY FOR ANALYST MATCHING POLICY DECISION ONLY`。可供人類決定distance threshold、ambiguity、Road-context、outside-reference與direction-neutral exposure政策，但這些決策尚未制定。
- Scope boundary：Phase 8.4A未做正式事故→segment attribution、雙向flow aggregation、EPDO、CBI、risk score、hotspot或Phase 8.4B執行。

## Phase 8.4B 新增紀錄（2026-09-24；formal accident-to-flow-segment matching）

### D148｜10 m primary threshold與敏感度

- Analytical decision：事故Point至direction-neutral BRouter LineString的primary threshold固定為10.0 m；5 m與20 m只作sensitivity。10 m不是官方標準，也不表示來源座標的真實誤差必為10 m。
- Observation：5／10／20 m的matched counts為34,106／39,711／41,926，match rates為73.2108%／85.2423%／89.9970%。只有10 m產生canonical output。

### D149｜Context、exact tie與near tie正式政策

- Analytical decision：valid／blank-ID polygon context一律使用constrained candidate；context-empty不得global fallback。Outside-reference只使用global candidates並保留其語境狀態。
- Analytical decision：10 m內exact minimum tie為`ambiguous_exact_tie`且不選winner；>10 m由`unmatched_distance`優先。Near tie只保留diagnostics，唯一最近候選仍可match。
- Observation：Primary結果為34,460 matched_context、5,251 matched_global、1,241 context-empty、5,443 distance-unmatched、190 exact-tie ambiguous及1 coordinate-unavailable，精確守恆46,586。

### D150｜Direction-neutral exposure正式化

- FACT：Phase 8.2有向segment weighted traversal totals為total 4,674,227,848、weekday 3,307,530,105、holiday 1,366,697,743。
- Analytical decision：事故沒有可靠方向資訊，因此後續exposure採direction-neutral physical segment member-flow sum；雙向member相加，one-direction-only使用既有member。One-direction-only BRouter output不得解讀為真實道路必然單行。
- Observation：106,049列exposure完全守恆上述三項總量，且逐列weekday+holiday=total；所有matched segments total exposure>0。
- Analytical safeguard：exposure只在spatial assignment凍結後join，不得參與winner、tie、confidence或distance policy。

### D151｜Phase 8.5 readiness與禁止提前解讀

- Readiness：`PHASE 8.5 READY FOR SEPARATELY AUTHORIZED RISK CONTRACT`只表示matching與exposure denominator input可供下一階段設計。
- Scope boundary：Phase 8.4B沒有計算accidents/exposure、severity/exposure、EPDO、CBI、risk score、percentile、hotspot或排名。BRouter flow仍是模擬使用量，不是GPS實測流量；正式風險語意必須另行授權與定義。

## Phase 8.5A 新增紀錄（2026-09-26；severity reconstruction and segment risk inputs）

### D152｜Accident-level severity與PDO coverage

- FACT：Phase 8.3A-2已將一致的party-source死亡、2–30日死亡與受傷欄位提升為accident-level canonical values；Phase 8.5A不加總party rows。
- Analytical decision：死亡或2–30日死亡>0歸fatal；兩者為0且受傷>0歸injury；fatal precedence。2–30日死亡納入fatal是研究重建決定，不改寫成官方A1分類事實。
- Observation：149 fatal、46,424 injury、13 unavailable、0 inconsistent，精確守恆46,586。
- Data coverage limitation：A3/PDO-only事故不可用；PDO coefficient雖保留原研究的1，但component status是`unobserved`，不得寫成observed zero。

### D153｜EPDO、共同CBI universe與day-type

- Analytical decision：直接採原研究EPDO coefficients fatal=193、injury=117、PDO=1，不重新fit。實際可計算component只有193D+117I，但欄位依研究契約保留`epdo`名稱並附coverage metadata。
- Analytical decision：SRI與SSI只在完整106,049 segment共同universe上normalization一次；weekday／holiday不各自重算max。CBI=SRI+SSI且不含exposure。
- Analytical decision：事故day type完全沿用Phase 7.3 FST calendar `IsHoliday`；weekday／holiday EPDO rates只能配對相同day-type exposure。
- Observation：39,705件matched classified accidents產生EPDO 4,654,909，其中weekday 3,527,364、holiday 1,127,545，精確守恆。

### D154｜Median flow flags與零分母

- Analytical decision：weekday／holiday high-flow分別定義為完整106,049 segment universe中day-type exposure `>= median`；median為4,352／1,983，high-flow segments為53,032／53,025。
- Analytical decision：total／weekday／holiday denominator為0時rate=null；不得填0、infinity或使用epsilon。此階段不設定最低exposure cutoff。
- Data coverage limitation：BRouter exposure是reconstructed estimated traversal exposure，不是GPS observed counts、unique cyclists或官方交通量。

### D155｜Unsmoothed microsegment output與Phase 8.5B界線

- Observation：19,874 segments有事故、86,175無事故；max accident count=38、max EPDO=4,446、max SRI=max SSI=1且CBI介於0與2。
- Analytical limitation：raw microsegment rates對低exposure敏感；Phase 8.5A不做corridor merge、Road.shp aggregation、spatial smoothing、任意低流量排除、排名或hotspot。
- Readiness：`PHASE 8.5B READY FOR SEPARATELY AUTHORIZED STABILITY AND PRESENTATION POLICY`，不表示任何危險路段結論已成立。

## Phase 8.5B 新增紀錄（2026-09-26；microsegment risk stability and presentation audit）

### D156｜既有median high-flow filter的描述性穩定效果

- OBSERVATION：平日high-flow subset的P95／P99／max相較full可計算universe下降15.41%／78.85%／99.861%；假日P99／max下降57.35%／99.800%，但P95因大量零值與分布組成改變而上升87.83%。這是描述性穩定效果，不是門檻統計最適性的證明。
- OBSERVATION：High-flow P99 tail的exposure中位數為平日6,548、假日2,667；事故件數中位數為4／3。Raw full-universe極端值主要與低exposure denominator有關，但high-flow後仍有尾端，不能將filter描述成消除所有不穩定性。
- OBSERVATION：High-flow P99 tail的segment length中位數為46.773／33.461 m，高於全體19.675 m；length quartile最高P99亦未落在最短Q1。現有證據不支持極短BRouter microsegments是主要驅動因素。

### D157｜CBI稀疏與下一階段界線

- OBSERVATION：CBI=0為86,175段（81.2596%），CBI>0為19,874段（18.7404%）；非零CBI的P50／P95／P99為0.0526／0.2632／0.4737。0–2 linear color scale可能壓縮多數非零差異，但本階段未採用nonlinear mapping、quantile legend或clipping。
- OBSERVATION：既有median high-flow universe取得`stability_conclusion=supported`的描述性證據；目前`additional_stability_policy_required=false`。這不是新增analytical cutoff或hotspot policy，未來若要排名、著色或標示hotspot仍須另行決策。
- Scope boundary：沒有危險路段排名、Top-N、hotspot、新exposure cutoff、corridor aggregation、spatial smoothing、per-distance risk、CBI redefinition或Phase 8.5C執行。

## Phase 8.5C 新增紀錄（2026-09-27；risk presentation contract）

### D158｜正式presentation universe與不新增hotspot門檻

- ANALYTICAL DECISION：平日／假日正式呈現universe沿用Phase 8.5A既有`day_type exposure >= full 106,049-segment universe median` flags；結果為53,032／53,025列。Phase 8.5B描述性證據支持此用途，但不表示中位數是統計最適門檻。
- ANALYTICAL DECISION：不新增minimum exposure、minimum accident／EPDO／CBI、length cutoff或binary hotspot。CBI=0 segments仍保留於相應high-flow universe。
- OBSERVATION：weekday-only／holiday-only／both／neither為1,665／1,658／51,367／51,359，精確守恆106,049個physical segments；此overlap不是risk分類。

### D159｜CBI與rate共同視覺契約

- PRESENTATION DECISION：CBI／SRI／SSI canonical值完全不變且不依day type重新normalise。完整universe中CBI>0的global Q50／Q75／Q90／Q95只建立兩張圖共用的`cbi_display_class`；ties不jitter，display class不是analytical risk category。
- PRESENTATION DECISION：平日／假日EPDO-per-1,000 maps使用pooled positive high-flow long-form observations的共同Q50／Q75／Q90／Q95／Q99 display thresholds。Raw rates不clip、不winsorize，class只控制style。
- PRESENTATION DECISION：CBI=0採neutral state；正式語意是目前研究fatal/injury population下沒有matched classified accident，不能寫成安全、事故為零或完全沒有事故。

### D160｜Geometry、解讀與持續限制

- PRESENTATION DECISION：正式GeoParquet以EPSG:4326 WKB LineString保存方向中立BRouter canonical endpoints；不換Road.shp、不合併corridor、不平滑。
- DATA LIMITATIONS：A3/PDO-only unavailable、BRouter exposure為estimated而非GPS／官方交通量、geometry仍是routing microsegments、matching exclusions與10 m analytical threshold持續存在；CBI及EPDO/exposure均不可作道路設計造成事故的因果證據。
- Scope boundary：沒有rank、Top-N、binary hotspot、new cutoff、corridor aggregation、smoothing、per-distance risk或Phase 8.6執行。

## Phase 8.6A 新增紀錄（2026-09-27；CBI-guided case candidate review pack）

### D161｜候選池只繼承既有視覺metadata

- PRESENTATION DECISION：主要人工檢視池只採Phase 8.5C既有`cbi_display_class`的`q90_q95`與`above_q95`，並要求至少在平日或假日一方屬於既有high-flow universe。`q75_q90`只作secondary map context，不進主要worksheet。
- INTERPRETATION：這些class只用來縮小人工看圖工作量，不是risk category、新CBI cutoff、binary hotspot或排名。資料不能替研究者選定最終案例。
- OBSERVATION：主要檢視池為1,283個唯一physical segments，其中`q90_q95` 516段、`above_q95` 767段；平日候選1,270、假日1,255，兩者皆是1,242、僅平日28、僅假日13。Secondary context為2,592段。

### D162｜人工檢視清冊與選案責任邊界

- PRESENTATION DECISION：worksheet維持一列一個physical segment，保留canonical CBI／SRI／SSI、事故與EPDO、兩種day type exposure／rate、geometry endpoints，另留空白`review_status`與`researcher_note`。不產生rank、hotspot、corridor或automatic recommendation欄位。
- ANALYTICAL SAFEGUARD：候選是BRouter physical microsegment，不是官方道路路段或自然道路corridor；本階段不自動合併相鄰段、不作街景判讀、不提出道路改善建議。
- HUMAN DECISION REQUIRED：最終案例須由研究者人工檢視地圖並留下明確理由。Phase 8.6A完成不等於任何案例已入選，也不授權Phase 8.6B。
- DATA LIMITATIONS：A3／PDO-only unavailable、BRouter exposure為estimated、事故matching exclusions與10 m analytical threshold持續存在；CBI及rate不得作道路設計因果證據。

### D163｜互動地圖只支援人工檢視

- WORKFLOW DECISION：Phase 8.6A-2以Folium／Leaflet呈現Phase 8.6A既有primary candidates與`q75_q90` secondary context；平／假日圖層只表示既有high-flow presentation membership，CBI本身不因day type改變。
- PRESENTATION DECISION：顏色沿用Phase 8.6A，線寬不編碼metric。地圖不含rank、hotspot、新cutoff、corridor、reverse geocoding、ROADNAME推定或自動case selection。
- HUMAN DECISION REQUIRED：互動HTML不寫回worksheet。最終案例仍須由研究者人工檢視道路脈絡、更新worksheet並留下明確理由；Phase 8.6A-2不授權Phase 8.6B。

### D164｜Phase 8.6A／8.6A-2 呈現層繁體中文化與固定線寬

- PRESENTATION DECISION：使用者可見文字採台灣繁體中文；程式內部欄位名稱、schema、controlled vocabulary 與 canonical values 維持英文。
- PRESENTATION DECISION：`q90_q95` 與 `above_q95` 使用相同 5.5 px base width，`q75_q90` 使用 3.0 px；hover 僅改變暫時顯示樣式，不依 CBI、EPDO、事故數或 exposure 計算線寬。
- INTERPRETATION：「視覺化級距僅用於縮小人工檢視範圍，不代表熱點定義或危險程度排名。」
- VALIDATION：candidate membership、canonical data、worksheet schema 與 map data fingerprint 不因本地化而改變；未新增 ranking、hotspot、cutoff 或 selected-case 狀態。
