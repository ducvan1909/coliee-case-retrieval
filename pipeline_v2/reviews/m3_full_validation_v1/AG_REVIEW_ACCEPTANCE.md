# Main nghiệm thu M3 full ingestion

Ngày09/11/2026. Main đọc artifacts/receipts và SQLite ledger readonly; không chạy lại inference, deploy hoặc full verify.

Chấp nhận full ingestion và DB/cache integrity cho415.693passages/7.708cases, collection `coliee_m3_full_ef2f4d6950a5b9fd`. Independent verify receipt exit0,415.693points,PASS,walltime1.525,54s. Giữ cả lượt ReadTimeout trước đó. Modern Standby là giải thích được AG hỗ trợ bằng event log; Main chưa tự xác minh chuỗi nguyên nhân nên không chứng nhận đó là nguyên nhân duy nhất.

Main kiểm trực tiếp: code aggregate `e4b8b358697c67073134fe5c5929e770d5c9c1e0b30f2cd98fc686b1227e3503` khớp manifest; profile hash `448a14cf545769cd0eb4c34db790b168f7b63b68e0d429c7e2d555c12d6caa84`. Ledger có6.496unique successful batches,6.496committed,1started giữtokens/elapsednull. Tổng successful input55.346.360,padded55.360.576 khớp plan. Usage thật tổng cộng vẫn có một request chưa rõ, không gọi55.346.360 là toàn bộ billed usage đã biết chính xác.

Main stat trực tiếp6.496JSON sidecars=43.219.233bytes và6.496NPZ=4.422.922.572bytes; tổng4.466.141.805bytes. Phần F-M3FULL-04 trong findings.json AG ghi số cache cũ khác với recomputed_metrics.json và actualfiles; dùng số đã đối chiếu này. Đây là lỗi báo cáo không chặn ingestion, không sửa artifact AG lịch sử. Mức giảm free disk toàn ổ không đủ quy chính xác mọi byte cho Qdrant; WSL virtualdisk/HNSW/hoạt động khác có thể góp phần. Bounded memory là contract/code + batchverification; không suy chỉ từ diskstat.

Các kết quả30tests +7faultinjection, full source/schedule audit và147baselinefiles do các báo cáo kiểm thử/AG cung cấp, tách khỏi thao tác Main vừa đối chiếu. Không cần chạy lại run/verify chỉ để lặp PASS.

Chưa hoàn tất toàn bộ M3: full hybrid search adapter, search-level checks và snapshot/restorefull còn chưa nghiệm thu; COLIEEgoldF1/M4 chưa triển khai. Bước kế tiếp là full hybrid search trên BM25/collection đã có, query-case exclusion, unique-case fusion và evidence open theo sourceprovenance; không cần embed lại corpus.

Operational debt đã thấy trong run thật: cache-skip loop và verify cuối chưa cập nhật progress nên có thể trông như treo. Sửa ở revision kế tiếp có namespace/fingerprint riêng hoặc migration rõ; không sửa code đã bind run để làm mất khả năng đọc/resume artifacts hiện tại.
