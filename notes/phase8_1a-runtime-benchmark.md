# Phase 8.1A｜Runtime benchmark

三組benchmark各使用不同deterministic 100-route subset與隔離cache，因此不是cache-speed比較。

| Workers | Routes/sec | Median sec/route | P90 | P95 | Errors |
|---:|---:|---:|---:|---:|---:|
| 1 | 8.0750 | 0.1078 | 0.1996 | 0.3057 | 0 |
| 2 | 7.4756 | 0.2416 | 0.4497 | 0.4951 | 0 |
| 4 | 9.1283 | 0.3998 | 0.6486 | 0.7260 | 0 |

選擇4 workers：它的aggregate throughput最高，且100/100 success、沒有failure regression。個別route latency隨concurrency增加，顯示BRouter／CPU contention確實存在，因此沒有再往上猜8 workers。

以4-worker實測總throughput為central estimate，另以＋15%吞吐作optimistic、70%吞吐作conservative：

- Optimistic：29.13小時
- Central：33.50小時
- Conservative：47.86小時

Gate cache為3,198,976 bytes／1,000 routes，約3,198.98 bytes/route。加15%為central disk約4.05 GB；加75%為conservative約6.16 GB。Preflight要求至少8 GiB free space，提供額外headroom。這些是sample-based工程估計，不是完成時間保證。

Benchmark以Python `tracemalloc`觀察到最高2,997,265 bytes traced allocation；這不含外部BRouter JVM、Python interpreter base RSS與OS page cache，因此只可視為runner增量記憶體下界。Production memory safety主要由Parquet batch streaming與不保留全量geometry保證，而不是把這個數字誤稱為整機peak RSS。
