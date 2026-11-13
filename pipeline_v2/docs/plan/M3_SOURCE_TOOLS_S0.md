# Quyết định triển khai phần còn lại M3

Ngày 11/11/2026. Main chốt S0 theo yêu cầu triển khai nốt M3, sau khi phục hồi Qdrant và full verify đủ 415.693 points. Bản này điều chỉnh draft `M3_FULL_SEARCH.md` theo review AG và phần code đã nghiệm thu. Checkpoint nền là commit `17c6d3c` cùng các artifact đã seal.

## Phần đã nghiệm thu và tiếp tục sử dụng

BM25 case và passage dùng sparse sidecar hiện hành. Dense giữ Qwen3-Embedding-4B revision đã pin, exact search một request lấy tối đa 4.096 hits, kiểm payload toàn bộ hits và cosine của retained leads/boundary. Mỗi kênh tối đa 100 unique cases trước RRF k=60, output mặc định 20. Query case exclusion, budget shortfall và boundary-tie reporting giữ policy đang chạy.

Các finding F-PLAN-01 đến F-PLAN-04 được tiếp nhận qua implementation sparse/hybrid và các review đã có. Các đề xuất adaptive RPC nhiều vòng và tối ưu reader SQLite trong draft đã được thay bằng code hiện hành. Case budget là cấu hình engineering đã có, chưa được tối ưu bằng gold.

F-PLAN-05, F-PLAN-06 và phần query-reading của F-PLAN-07 là phạm vi bổ sung lần này. Code/config đã bind hash được giữ nguyên bytes. Triển khai trong các module mới dưới `full_search/`, CLI mới `m3_search.py` và profile mới `configs/m3_search.json`. Local source tools dùng cùng validated snapshot với reader hiện có; caller có thể mượn một session tương thích.

## Contract nguồn và tìm kiếm

- Mở snapshot kiểm full plan, compatibility, universe và seals bằng guard hiện có. Bind thêm profile/code của công cụ mới và seal/manifest upstream cần đọc. Mỗi lần dùng case kiểm raw hash và sealed per-case JSON. Cache record có giới hạn, explicit revalidate làm mới toàn snapshot và invalidate nếu drift.
- Đọc navigation/passages JSON đã seal trực tiếp trên hot path. Dùng raw bytes và offsets đã có để mở nguồn. Các hàm rebuild navigation/passages và tokenizer thuộc đường kiểm dựng bundle, được giữ ngoài hot path mới.
- `case_map` và `case_anchors` trả phân trang records/preview/anchors có provenance. Query case được phép đọc như mọi case đã biết.
- `search_case` lexical dùng BM25 hiện có với thống kê trong case, khai báo policy riêng cho việc định vị trong case. Literal dùng phrase reader. Giới hạn output được áp sau khi xét toàn scope case.
- `search_phrase` quét raw stream, gồm headings, whitespace, CRLF và BOM. Hai matching modes là `exact_case_sensitive` và `unicode_casefold_mapped`. Giữ overlapping matches và thứ tự case ID rồi raw byte start/end. Full Unicode casefold có mapping về nguyên codepoint; mọi match phải round-trip đúng raw substring. Baseline giữ nguyên whitespace và Unicode normalization của nguồn.
- Corpus phrase scan có số case/page hữu hạn, mặc định 128, tối đa universe 7.708. Response ghi case đã quét, cursor và phần còn lại, kể cả page không có hit. Limit hits từ 1 đến 100. Exhaustion chỉ được báo khi thực sự hết scope.
- `search_identity` trả observed literal/casefold leads và anchor refs phù hợp. Method version và identity-unverified status đi cùng nguồn. Placeholder được giữ nguyên văn.

## Open và cursor

`open_source` nhận case ID, expected source hash và tập handles/passage IDs/raw hit spans trong cùng nguồn. Raw spans cho phép mở cả phrase nằm trong heading hoặc xuyên nhiều units. Khi có paragraph parents, context gồm full parent cùng paragraph neighbors theo refs/source order. Heading/whitespace-only hit giữ raw span cùng content context quan sát được, không gán parent giả.

Requested raw intervals được khử trùng trước khi giao. Components liệt kê đầy đủ paragraph, unnumbered, headings và whitespace xen giữa, giữ marker, paragraph role, uncertainties, evidence refs và language metadata từ nguồn đã seal. Expanded context giữ quan hệ với hit ban đầu.

Byte budget từ 1 đến 65.536, kiểm integer nghiêm ngặt. Với middle hit, bắt đầu từ hit, hoàn tất parent rồi đến neighbors. Prefix và suffix còn thiếu là các pending intervals độc lập. Mỗi page tôn trọng biên codepoint UTF-8. Nếu budget chưa đủ cho codepoint tiếp theo, trả lỗi có thể xử lý bằng cách tăng budget, giữ nguyên tiến độ.

Response phân biệt requested intervals, raw intervals giao trong page hiện tại, cumulative traversal coverage và pending intervals. Byte count dựa raw UTF-8 text. `token_safe_agent_payload=false` và `M4_delivery_recorded=false` đi cùng response.

Cursor là stateless resume transport có version/schema/checksum, bind operation, query/request, source scope và snapshot/profile/code. Open cursor dùng tiến độ traversal được kiểm tra để dựng lại requested/priority/delivered/pending intervals từ request gốc. Cursor không cấp quyền truy cập và không thay delivery ledger của M4. Các fields tự khai delivered/pending không được dùng làm bằng chứng model đã đọc.

## Kiểm thử và nghiệm thu

Tester sở hữu test files và evidence riêng, kiểm code cuối sau triển khai. Fixtures bao gồm Unicode expansion/partial fold, overlapping/cross-unit matches, cursor tamper/binding/drift, marker lặp, quoted/unknown, unnumbered/heading, middle-hit large-parent pagination, UTF-8 no-progress và dedup nhiều refs. Kiểm corpus hữu hạn dùng các edge cases đã công bố trong review AG, gồm `041666.txt` và `055641.txt`, cùng case diagnostic `095448.txt`.

Local engineering gate cần CLI help, fixtures/regressions, corpus raw-span round-trip, pagination coverage và old fingerprint guards đạt. Báo cold/session và warm tool latency, output bytes, lỗi và usage chưa biết. Test mới tập trung vào regressions cụ thể của contract này.

Codex chuẩn bị manifest/lệnh cho một query embedding thật trên corpus đã phục hồi. Người dùng hoặc AG thực hiện Modal theo phân công trong AGENTS.md. Đề xuất sáu query trong draft được thay bằng một query theo handoff hiện hành; request scope phải được khóa trước chạy, giữ lỗi/retry/unknown usage. M3 vẫn chờ gate này và nghiệm thu cuối nếu chưa có evidence thực thi. M4 model/tokenizer/budget, controller, selector và COLIEE evaluation thuộc các mốc sau.
