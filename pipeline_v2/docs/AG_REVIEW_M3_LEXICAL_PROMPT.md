# AG review reader BM25 tối ưu

Repo `E:/Git/coliee-case-retrieval`, Python `.venv/Scripts/python.exe`. Đọc AGENTS.md, `pipeline_v2/docs/M3_LEXICAL.md` và `M3_LEXICAL_TEST_REPORT.md`. Đây là review phần reader lexical đã triển khai, không tự triển khai toàn draft M3 full search.

Đọc `full_search/lexical.py`, `m3_lexical.py`, `configs/m3_lexical.json` dưới pipeline_v2. Đối chiếu frozen `optimization_v2/index.py`, báo cáo latency diagnostic và `reviews/m3_lexical_validation_v1/`. SQLite/run full, pilot và source giữ nguyên; không đọc gold/labels/env, không gọi Modal/deploy/Qdrant, không sửa production/config/index/seals. Chỉ ghi tests/reports mới vào `pipeline_v2/reviews/m3_lexical_ag_review_v1/` hoặc suffix mới; fault injection trên tempcopy, SQLite readonly.

Kiểm độc lập:

- Công thức BM25 float64, sorted unique queryterms, analyzer/df/avg/n chuẩn; exclusion trước cap, zero/OOV/negation/Unicode, không float32 hoặc ngầm bỏ stopwords. SQL không JOIN documents trong vòng term. Bounded fetchmany, không fetchall toàn postings.
- NumPy indexed accumulation đúng vì unique (kind,term,id); nhiều chunks/terms, điểm reset mỗi request. Top-k partition giữ tất cả tie cần thiết rồi ID tie-break; unique-case mode chọn best hit toàn channel trước cap, không cộng phiếu sibling hoặc đổi rawhit semantics.
- Metadata chỉ lấy selectedIDs theo batch, đối chiếu actualcasecolumns; source/index drift và immutable snapshot semantics, guard invalidation sticky, cleanup nếu constructor fail. Không hứa phát hiện mọi live SQLite mutation giữa session. Revalidate full kiểm riêng, không chạy mỗi query.
- Startup/fullhash/preload khác querylatency; default cache128MiB/mmap512MiB không phải hardRAMcap. Kiểm PRAGMA thực nhận và RAM thực, tránh xem mapping size là resident memory. No-env/no-Modal CLI và các request local.
- Main benchmark so scalar độc lập trên cùng8queries đã exposed, cùngPRAGMA nhưng các lượt cache/I/O khác thời điểm. Xác minh rankedIDs/scores, điều kiện đo và repeat results; không cộng hoặc ngoại suy thành end-to-end hybrid speedup. Nếu cần thêm boundedbenchmark, khóamanifest/sốlượt và log trước; không chạy lại toàn lịch sử AG nặng nhiều giờ để lặp PASS.

Trả REPORT.md, findings.json, commands_and_results.json, independenttests/results và recomputed_metrics.json. Tách correctness, actualfullworkload parity, performance/coldwarm/resource limits và fullsearch readiness. Gặp productionbug gửi Codex repro/evidence, không patch hoặc sửa seal để vượt guard. Không chốt COLIEEF1/legalquality từ ranking parity.
