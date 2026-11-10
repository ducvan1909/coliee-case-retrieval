# Prompt giao AG review M1 Revision 2

Bạn thực hiện review độc lập M1 Revision 2 trong repo `E:/Git/coliee-case-retrieval`. Hoàn tất review bằng evidence và artifact thật; không dừng ở kế hoạch.

## Phạm vi và tài liệu

Đọc `AGENTS.md`, `pipeline_v2/docs/M1_REVISION2.md`, `pipeline_v2/docs/M1_REVISION2_TEST_REPORT.md`, `pipeline_v2/configs/m1.json`, `pipeline_v2/source/`, `pipeline_v2/m1.py`, các test M1 và kế hoạch nguồn hiện hành.

- Nguồn khóa: `pipeline_v2/artifacts/m0_20261105_v2/`.
- Bundle mới: lấy **đúng đường dẫn bundle nghiệm thu ghi trong `M1_REVISION2.md`**, không tự chọn theo thời gian sửa file.
- Bundle cũ để đối chiếu: `pipeline_v2/artifacts/m1_20261105_v1/`.
- Findings cũ: `pipeline_v2/reviews/m1_review_v1/`. Không chạy nguyên script cũ trên schema mới nếu script còn giả định quotation phải nằm trong span paragraph cha.
- Chỉ đọc corpus `data/task1_train_files_2026/cases/`. Không đọc labels, test corpus, gold dossiers, nguồn ngoài hoặc credential. Không inference, tải model, index, M2 hoặc deploy.
- Production code, config, corpus, bundle và báo cáo lịch sử READ-ONLY. Chỉ ghi scripts/report vào thư mục mới `pipeline_v2/reviews/m1_review_v2/`; nếu đã tồn tại dùng phiên bản mới, không ghi đè.
- Kiểm tamper bằng fixture/bản sao, không sửa nguồn hoặc bundle thật. Dùng `.venv/Scripts/python.exe`.

## Contract mới phải kiểm

1. Marker `[số]` ở đầu dòng, cho phép whitespace phía trước, có vị trí riêng. Mỗi marker được chấp nhận là paragraph marker phải có unit riêng; không bị nuốt vào unit marker trước, kể cả marker thuộc quotation.
2. Literal citation như `[2012] FC 9` được phân biệt bằng ngữ cảnh citation. Không được loại mọi số trong khoảng năm hoặc bỏ marker standalone chỉ vì giá trị số. Trường hợp mơ hồ phải giữ địa chỉ và uncertainty.
3. `paragraph_role` là `current_case`, `quoted` hoặc `unknown`; đây là nhận định cấu trúc có evidence, không phải human gold. Không coi thiếu dấu quotation là đủ để khẳng định `current_case`. Các cụm `I find`, `THIS COURT` cũng có thể thuộc án được trích, nên voice cue đơn lẻ không chứng minh quyền sở hữu. Không yêu cầu phải có số lượng `current_case` lớn hơn 0 để gọi parser đạt.
4. Quan hệ attribution/quotation là liên kết giữa các unit độc lập. Không yêu cầu unit quotation nằm trong span của unit dẫn nguồn. Thiếu căn cứ thì link để null/unknown; không bịa quan hệ cha.
5. Không có `last_outer`, `expected`, reset theo `[1]` hoặc cơ chế tương đương dùng thứ tự số để quyết định role, gộp đoạn, duy trì quote state hoặc chuyển ngôn ngữ. Nếu số được dùng trong chẩn đoán thì không được ảnh hưởng phân đoạn/phân loại.
6. Ranh giới bản dịch dựa trên evidence chuyển ngôn ngữ, độc lập số marker. Bản tiếng Pháp có thể bắt đầu ở `[2]`; gặp `[1]` trong quotation không gây reset vùng.
7. Unknown vẫn giữ ranh giới, nguyên văn và context refs để M2 xử lý. Không thay lỗi nuốt paragraph bằng cách gán mọi phần còn lại là một vùng unknown khổng lồ.
8. Heading/header/headnote được phân biệt trong section refs theo contract mới. Kiểm các heading viết hoa `ORDER`, `INTRODUCTION`, `ARGUMENTS`, `DECISION` và việc header không làm bẩn context thân án.
9. Raw bytes, UTF-8 mapping, offsets, metadata evidence và source anchoring M0 vẫn phải đúng. Không cải thiện cấu trúc bằng sửa raw hoặc khôi phục suppressed text.

## Kiểm thử và quét độc lập

- Chạy toàn bộ test hiện hành và full validator bundle mới; ghi lệnh, exit code, thời gian, lỗi/retry. Không coi tái lập parser là bằng chứng độc lập về đúng cấu trúc.
- Quét toàn bộ 7.708 nguồn bằng script riêng: universe/hash M0, seal, partition không gap/overlap, UTF-8 spans/maps, uniqueness, metadata slices, references và summary counts.
- Tự phát hiện marker từ raw bytes, không gọi/import hàm nhận diện marker hoặc parser production làm oracle. So sánh toàn bộ vị trí marker với unit/observation artifact; mọi exception citation phải có căn cứ kiểm được. Kiểm không paragraph unit nào nuốt marker khác.
- Kiểm sự độc lập với số bằng metamorphic tests trên fixture: giữ nội dung, khoảng trắng, cue và độ rộng marker; đổi số thành nhảy tiến, lùi, lặp `[1]`. Ranh giới và role theo thứ tự xuất hiện phải giữ nguyên, ngoài khác biệt ID/hash/giá trị marker. Không dùng citation literal trong phép biến đổi này.
- Kiểm ambiguity tại điểm kết thúc quotation: cue ở một đoạn không được làm role `quoted` hoặc language sai lan vô hạn sang những đoạn sau; unknown có thể là kết quả đúng.
- Chạy regression cũ trên raw: `000758`, `050936`, `000432`, `014069`, `046028`, `061295`, `067620`, `062436`. Đối chiếu ranh giới riêng của các marker và raw context; không ép quan hệ cũ nếu contract mới chủ ý để unknown.
- Không coi con số 1.632 án của review cũ là số lỗi đã xác nhận. Nếu đo lại phạm vi, lưu algorithm, danh sách case/offsets và phân biệt risk flags với confirmed defects.
- Tự tính source hash/offsets từ raw và M0, không sao chép các trường provenance hoặc con số ghi sẵn từ findings cũ. Nếu chúng không khớp, ghi nhận sai lệch bằng chứng riêng.

## Đọc đối chiếu cấu trúc

Khóa `sampling_manifest.json` trước khi đọc raw nội dung để review:

- Seed `20261105`; đọc cohort M0 chỉ để loại discovery/holdout IDs khỏi mẫu đọc thủ công; không đọc labels. Kiểm integrity toàn corpus vẫn được phép.
- Giữ regression nêu trên thành nhóm exposed riêng.
- Lấy 12 án ngẫu nhiên đều sau exclusions, cộng tối đa 12 án rủi ro từ role unknown, quotation relations, translation cues, header/heading. Khử trùng và lưu tiêu chí/ngưỡng/seed/IDs, không chọn theo kết quả retrieval hoặc gold.
- Tối đa 3 vùng/án theo quy tắc khóa trước. Đọc đủ raw context trước/sau; ghi mọi lần mở rộng và lý do. Không đổi mẫu khi khó phân xử.
- Mẫu mới đọc trong lượt review trở thành exposed diagnostic; không gọi là holdout. Không tune parser trong review này.
- Tách kết quả mẫu ngẫu nhiên, mẫu rủi ro và regression. Giữ unresolved khi thiếu chứng cứ, không ép mọi vùng thành đúng/sai.

## Bàn giao và kết luận

Ghi `sampling_manifest.json`, `findings.json`, `reviewed_regions.json`, `commands_and_results.json`, scripts và `REPORT.md` trong thư mục review mới. Mỗi finding có severity, confirmed/suspected/accepted limitation, case/hash/unit, byte offsets, nguyên văn, lệnh tái hiện, tác động M2 và hướng sửa tối thiểu. Không sửa production.

Trả lời trực tiếp:

1. Lỗi nuốt dây chuyền, false reset và lẫn bản dịch cũ đã được khắc phục ở mức nào?
2. Việc bỏ bộ đếm có thực chất không, hay còn phụ thuộc thứ tự số dưới tên khác?
3. Có gán role/attribution thiếu evidence, lan trạng thái quá xa hoặc unknown làm mất ranh giới không?
4. Phần nào phải sửa trước M2; phần nào có thể chuyển sang M2 với giới hạn đã ghi?

Kết luận một trong `ready_with_documented_limits`, `fixes_required_before_M2`, `insufficient_evidence`. Nêu số nguồn kiểm tự động, số án/vùng thực sự đọc và số unresolved. Đây là AI-assisted structural review, không phải chứng nhận accuracy toàn corpus hoặc chất lượng noticed-case prediction.
