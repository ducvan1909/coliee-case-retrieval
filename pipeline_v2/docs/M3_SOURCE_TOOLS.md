# Công cụ tìm và đọc nguồn M3

Các công cụ local được bổ sung theo [quyết định S0](plan/M3_SOURCE_TOOLS_S0.md). Chúng dùng raw nguồn, cấu trúc M1 và navigation/passages M2 đã seal. BM25 toàn corpus và hybrid vẫn đi qua `m3_sparse`; source tools dùng CLI `m3_search` và profile `configs/m3_search.json`.

| Công cụ | Kết quả |
|---|---|
| `case-map` | Bản đồ phân trang với previews, headings, handles và raw provenance |
| `case-anchors` | Anchors theo case/handle hoặc source anchors với `--source` |
| `search-case` | Định vị trong case đã biết, gồm query case; lexical dùng BM25 thống kê trong case, literal dùng raw phrase |
| `search-phrase` | Raw exact hoặc Unicode casefold có mapping, kể cả xuyên heading/chunk/line |
| `search-identity` | Vị trí xuất hiện nguyên văn/casefold cùng anchors, method version và trạng thái identity chưa xác minh |
| `open-source` | Raw context có source hash, hit mapping, components và requested/delivered/pending intervals |
| `revalidate` | Kiểm lại snapshot bằng guard hiện có |

CLI local hỗ trợ `--help` ở mỗi subcommand. Các ví dụ chạy từ repo root.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m3_search case-map --case-id 095448.txt --limit 5
& .venv/Scripts/python.exe -m pipeline_v2.m3_search case-anchors --case-id 095448.txt --source --limit 5
& .venv/Scripts/python.exe -m pipeline_v2.m3_search search-case --case-id 095448.txt --text "standard of review" --limit 5
& .venv/Scripts/python.exe -m pipeline_v2.m3_search search-phrase --case-id 095448.txt --text "Federal Court" --limit 5
& .venv/Scripts/python.exe -m pipeline_v2.m3_search search-identity --case-id 095448.txt --text "Federal Court" --limit 5
```

`open-source` yêu cầu source hash từ map/search response. Với cùng snapshot hiện hành, ví dụ mở paragraph đã biết như sau.

```powershell
& .venv/Scripts/python.exe -m pipeline_v2.m3_search open-source --case-id 095448.txt --source-hash 78a77dfff8c30f6f99f458104bb1ccd51f7c0e319f995476c5cc627e7a2052ee --handle p000005 --byte-budget 4096
```

Open nhận nhiều `--handle`, `--passage-id` hoặc `--hit-span START:END`. Hit spans dùng UTF-8 byte offsets. Khi đọc tiếp, giữ nguyên tập refs, case/hash và truyền `--cursor` từ response. Có thể điều chỉnh byte budget giữa các trang. Source drift hoặc cursor khác request/snapshot bị từ chối. Byte budget từ 1 đến 65.536; budget chưa đủ chứa codepoint kế tiếp cần được tăng.

Phrase hỗ trợ `--matching-mode exact_case_sensitive` và `unicode_casefold_mapped`. Overlapping matches được giữ, thứ tự theo case ID và byte offsets. Matching giữ nguyên whitespace và Unicode normalization của raw nguồn. Corpus scan mỗi page có `--case-scan-limit`, mặc định 128; page không có hit vẫn có thể trả cursor và phần scope còn chờ. Giữ nguyên tool/query/scope/matching mode khi tiếp tục cursor.

Session kiểm snapshot khi mở nên standalone CLI có chi phí startup. Khi tích hợp nhiều tools, tái sử dụng `SourceToolsSession` và snapshot tương thích; caller tiếp tục sở hữu snapshot được truyền vào. Mỗi lần đọc case vẫn kiểm raw/sealed content hashes. Hot path đọc JSON đã seal và raw bytes.

Open chọn bytes theo ưu tiên hit, hoàn tất parent rồi context lân cận. Phần được giao trong page được trình bày theo source order. `delivered_spans` là page hiện tại, `cumulative_delivered_spans` là tiến độ traversal, và `pending_spans` là vùng còn thiếu. Cursor là transport resume. M4 sẽ quản lý token budget và việc model thực sự nhận các nguồn trong payload.

Việc kiểm query embedding thật dùng manifest và runner riêng trong `pipeline_v2/reviews/m3_completion_v1/`. Người dùng hoặc AG thực thi bước này theo phân công hiện hành. Các local tools và cached diagnostics được nghiệm thu riêng với gate đó.
