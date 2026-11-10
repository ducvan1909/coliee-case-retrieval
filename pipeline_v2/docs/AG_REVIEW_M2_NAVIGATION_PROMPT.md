# Prompt AG — Review rộng phần navigation/preview của M2

Hoàn tất review độc lập trong repo `E:/Git/coliee-case-retrieval`, trước khi chuyển sang phần M2 phụ thuộc tokenizer. Đọc `AGENTS.md` và đánh giá bằng code, artifact và raw evidence thật, không chỉ đồng ý với báo cáo PASS.

## Phạm vi đã được phép

- Đọc `pipeline_v2/docs/plan/SOURCE_CHUNK_INDEX.md`, đặc biệt Sections 3.3–3.5; `AGENT_AND_EVALUATION.md`; `docs/M2.md`; `docs/M2_TEST_REPORT.md`; `configs/m2.json`; `navigation/`; `m2.py`; tests M2.
- Nguồn M0: `pipeline_v2/artifacts/m0_20261105_v2/`; M1: `pipeline_v2/artifacts/m1_20261105_v2/`; bundle cần review: `pipeline_v2/artifacts/m2_navigation_20261105_v1/`.
- Chỉ đọc corpus train `data/task1_train_files_2026/cases/`. Không đọc labels/gold, test corpus, credential, nguồn ngoài hoặc dùng gold để chọn mẫu.
- Production, config, data, bundle và báo cáo lịch sử READ-ONLY. Tạo scripts/evidence/report mới tại `pipeline_v2/reviews/m2_navigation_ag_review_v1/`; nếu tồn tại dùng thư mục phiên bản mới, không ghi đè.
- Dùng `.venv/Scripts/python.exe`; không model/API, tải model, embedding, index, deploy hoặc tự triển khai phần tiếp theo.
- User đã hoãn embedding model/tokenizer và tokenizer agent. Không coi thiếu token-valid chunks là defect của stage navigation này; cũng không vì navigation PASS mà tuyên bố toàn M2/M3/M4 ready.

## Câu hỏi cần trả lời

Navigation có cho agent biết query chứa gì, mở đúng vùng cần đọc và truy lại nguyên văn không? Preview có ích cho quyết định đọc hay thường quá ngắn, thiếu câu dẫn, che khuất dấu hiệu hoặc gây hiểu nhầm? Phần nào cần sửa trước khi nối chunk theo token và harness agent?

## A. Kiểm tự động trên toàn bộ corpus

Chạy test suite và validate bundle hiện hành một lần, lưu commands/exit codes/elapsed/output. Có thể đọc receipt và kết quả independent audit đã có để tránh lặp thí nghiệm không cần thiết, nhưng phân biệt rõ kết quả tự chạy với kết quả kế thừa.

Viết hoặc port có kiểm tra script độc lập quét toàn bộ artifact, không dùng hàm builder production làm oracle:

1. Universe/hash M0/M1/M2, seals, profile/code fingerprints và references nhất quán.
2. Tất cả paragraph và unnumbered content M1 có đúng một nav row; không bỏ unknown/quoted hoặc nội dung tiếng Pháp. Whitespace/headings không bị xóa khỏi nguồn.
3. Handles đúng case/hash/profile; source order đúng cả khi marker nhảy/lặp. Paragraph neighbors bỏ qua whitespace/heading; unnumbered dùng đúng policy content-unit. Không nhảy file.
4. Toàn bộ previews khớp exact raw slices/hash/UTF-8 spans, tối đa 240 Unicode codepoints; không chèn ellipsis/tóm tắt vào raw. Tối đa hai snippet hiển thị không làm mất anchor catalog.
5. Placeholder anchors đầy đủ theo profile; full M1 quote cues và fragments qua nhiều unit khớp raw, không mất heading-only cues. Preview anchor refs/visibility full/partial trung thực.
6. Heading labels là literal có provenance, không tên mục sinh tự động. Role, uncertainties và evidence M1 không bị nâng thành identity/holding/ownership đã verified.
7. Pagination truy cập đủ records/anchors/source anchors, tổng số và next offset nhất quán. Không lẫn preview với trạng thái đã đọc hoặc ghi coverage runtime vào manifests.
8. Parent/context mapping đúng. `open` diagnostic trả nguyên văn full container và neighbors, gồm vùng giữa; không coi đó là bằng chứng M4 đã giao raw cho model.
9. Missing tokenizers giữ token counts null, chunk/token/dense/payload readiness not_ready; không có chunks giả theo ký tự. Không inference hoặc xử lý riêng tiếng Pháp.
10. Tamper/source drift/profile drift/reseal bị phát hiện. Chỉ sửa bản sao fixture để kiểm, không đụng bundle gốc.

Thống kê toàn corpus phải sinh từ script, có denominators và danh sách case/span cho bất thường. Risk flags không tự thành confirmed defects. Không coi cùng builder tạo lại cùng output là chứng minh chất lượng preview.

## B. Review chất lượng preview và context trên mẫu lớn hơn

Khóa `sampling_manifest.json` trước khi đọc raw để phân xử:

- Seed `20261105`. Dùng cohort M0 chỉ để loại 10 discovery và 10 holdout khỏi mẫu đọc thủ công; không mở nhãn. Quét integrity tự động toàn corpus vẫn được phép.
- 20 án ngẫu nhiên đều, cộng 20 án theo rủi ro. Khử trùng giữa và trong các nhóm bằng một selected-set chung; ghi cả số slots và số case duy nhất. Nếu thiếu nguồn đủ điều kiện thì báo thiếu, không tự điền trùng.
- Các nhóm rủi ro: nhiều anchors vượt display limit; cue dài/cross-unit hoặc heading-only; previews rất ngắn/nghi abbreviation/placeholder-only; context với marker lặp/quotation/unnumbered; nguồn rất dài/nhiều headings. Chốt tiêu chí và ngưỡng từ metadata trước khi đọc raw; không chọn theo retrieval hoặc gold.
- Chọn tối đa 3 vùng/án bằng quy tắc khóa trước: opening, anchor/partial cue và parent-neighbor window. Giữ cả vùng sạch và unresolved trong `reviewed_regions.json`, không thay mẫu vì khó.
- Các regression đã exposed có thể báo riêng: 061295, 067620, 062436, 000758, 050936, 000432, 014069, 046028; không gọi chúng là mẫu mới hoặc gold.

Với mỗi vùng, xem map/preview trước và ghi agent có thể biết gì từ đó; sau đó mở đủ raw context để đối chiếu:

- Preview có phải chỉ là `Mr.`, `J.`, số đoạn hoặc một mẩu vô nghĩa vì heuristic dấu câu không? Nếu có, lưu exact case/span và xác định navigation usability issue, không nhầm với source corruption.
- Việc skip placeholder-only line có đúng view-only, có làm mất câu có nội dung không?
- Dấu viện dẫn ở sâu trong paragraph có xuất hiện trong preview hoặc truy cập được rõ qua anchors không? Long cue bị cắt có được báo partial và mở full cue được không?
- Có đoạn preview khiến người đọc hiểu nhầm lời bên đương sự/quotation thành lời tòa hiện tại không? Không bắt M2 giải bài toán speaker, nhưng phải kiểm nhãn và context không tạo khẳng định sai.
- Full parent + trước/sau có giúp tìm câu dẫn, antecedent và phần tiếp nối không? Nếu vẫn thiếu, có refs để mở tiếp không? Không đòi cửa sổ cố định đủ mọi ngữ nghĩa.
- Khi nhiều units/hits chung vùng, mapping có đủ để M4 dedup và chỉ rõ hit so với context không? Child passage thật chưa tồn tại thì kiểm bằng fixture, không tự sinh chunks/token counts.
- Không coi chưa nhận đúng tiếng Pháp là blocker trong scope hiện tại; chỉ kiểm text còn đầy đủ và language label không dùng để lọc bỏ.

Tách kết quả mẫu ngẫu nhiên và mẫu rủi ro. Không suy tỷ lệ lỗi toàn corpus từ 40 case AI-assisted review. Không tự động gán tất cả PASS chỉ vì marker count khớp; phải có nhận định theo raw evidence về usefulness và ambiguity của preview.

## C. Kết quả bàn giao

Lưu sampling manifest, scripts, machine audit JSON, commands/results gồm lỗi/retry, reviewed regions và findings. Mỗi finding có type confirmed/suspected/accepted limitation, severity, case/source hash, IDs, byte offsets, nguyên văn, lệnh tái hiện, tác động tới agent và hướng sửa tối thiểu. Không sửa production trong review này.

`REPORT.md` phải trả lời:

1. Stage navigation/preview/mapping có đạt contract không?
2. Preview có đủ hữu dụng để agent chọn đọc trên mẫu đã kiểm không, còn dạng nào đáng sửa?
3. Có mất anchors/context/provenance hoặc khẳng định ngữ nghĩa quá mức không?
4. Có cần sửa trước phần M2 tiếp theo không?

Kết luận một trong `ready_with_documented_limits`, `fixes_required_before_next_stage`, `insufficient_evidence`. Nêu rõ đây chỉ là stage navigation; embedding tokenizer, token-valid chunks, retrieval và live agent vẫn chưa nghiệm thu. Không tự mở scope hoặc triển khai mốc tiếp theo.
