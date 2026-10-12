# Final production cache snapshot procedure

目前bundle可用SQLite Online Backup API安全取得live consistent snapshot。但若要把本機工作完整移交VM，建議在controlled stop後建立最後一次snapshot：

1. 在production terminal按一次`Ctrl+C`，等待runner回到prompt；不要使用`kill -9`。
2. 執行`python src/run_brouter_production.py --status`，記錄completed／success／failure與last flush。
3. 確認沒有production Python runner正在新增routes；不必刪除WAL/SHM，也不要手動copy它們。
4. 執行`python src/build_cloud_migration_bundle.py`。程式用SQLite Online Backup API由read-only connection建立獨立snapshot。
5. 核對`notes/cloud_migration_bundle_receipt.json`中的snapshot rows、`integrity_check=ok`、archive hash。
6. 在上傳前再次執行clean-room tests；只上傳archive與`.sha256`sidecar。

若第4步失敗，保留live DB不動並停止搬移；不得退回直接copy DB＋WAL＋SHM。
