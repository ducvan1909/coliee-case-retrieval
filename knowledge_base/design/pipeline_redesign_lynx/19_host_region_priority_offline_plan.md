# Kế hoạch xếp hạng vùng nguồn và kiểm tra offline KOS-5

## Mục tiêu và phạm vi

Host quyết định **thứ tự đọc**, không xác nhận AU và không kết luận `no_AU` cho phần chưa đọc. Thử một bộ chọn vùng nhiều kênh để đưa proposition, application, điều kiện và ngoại lệ đến model sớm hơn với ngân sách đọc thấp hơn.

Đợt này chỉ chạy offline trên **toàn nguồn** năm án `013009`, `013948`, `011904`, `045155`, `099980`. Không dùng universe 30 target của pilot H/P để tuyên bố whole-case coverage. Không gọi LLM, Modal hoặc endpoint, không tải/train model, không thay extraction contract, runtime mặc định, `.env`, reranker, NN–AU joining hay Issue gate. KOS chỉ là tập đối chiếu, không phải gold và không phải đầu vào xếp hạng.

Module thử riêng: `knowledge_base/pipeline_v1/region_priority_offline/`. Báo cáo riêng: `knowledge_base/pipeline_v1/outputs/region_priority_offline_20261013/`. Giữ nguyên source, artifact V13–V15, các run H/P và báo cáo lịch sử.

## Tài liệu đầu vào

- `04_pipeline_spec.md`: nguồn/offset/provenance và kiến trúc P2 mặc định. Kế hoạch này là nhánh thử, chưa thay exhaustive default.
- `18_selective_reading_pilot.md` và `outputs/selective_trial30_fix1_20261013/RESULT.md`: H bỏ nhiều positive reference; P phát sinh overhead planning. Reference model không phải gold.
- `pipeline_v1/manifests/selected_kos_manifest.v1.json`: khóa đúng năm án và hash các file KOS.
- `pipeline_v1/outputs/source_store_v1/`: CaseSource bất biến.
- `outputs/plan03_source_blocks_v1/sourceblock_build_manifest.json`, `outputs/plan04_sentence_atoms_v1/sentence_atom_build_manifest.json` và policy tương ứng: bản đồ nguồn đã kiểm tra.
- `G:/Legal-AI/kos_sample/cases/{case_id}/authority_units/*.md`: Claim/Evidence/Limits để đối chiếu sau khi đã khóa lịch đọc; không dùng `kind`, `issue_ids`, `para_idxs`, query/candidate role hoặc gold links để chấm điểm.
- `pipeline_v1/kos_comparison/comparison.py`: alignment exact/whitespace-only; không gán offset theo `para_idxs` hay paraphrase Claim.

## Cơ sở và giới hạn bằng chứng

- [DoSSIER@COLIEE 2021](https://arxiv.org/pdf/2108.03937), §3.1, bảng 2: biểu diễn paragraph và phối hợp tín hiệu. Đây là nghiên cứu retrieval có query, không chứng minh ưu tiên AU trong KB.
- [Segment First, Retrieve Better](https://arxiv.org/pdf/2508.00679), §5.1, §7.2, §7.5: rhetorical roles cung cấp thông tin cấu trúc; báo hạn chế chuyển classifier từ án Ấn Độ sang COLIEE Canada. Không dùng role dự đoán làm veto.
- [Corpus for Automatic Structuring of Legal Documents](https://aclanthology.org/2022.lrec-1.470.pdf), §3: argument, analysis, statute, precedent và ratio khác nhau; không ánh xạ role trực tiếp thành AU kind.
- [Lynx 2019](https://aclanthology.org/W19-2207.pdf), §§3.7–3.9: reference, structure và salience/ redundancy là các feature độc lập có thể truy nguồn. Sentence salience không phải xác nhận AU.
- Bài UB trong [COLIEE 2025 proceedings](https://coliee.org/documents/Proceedings/2025-Proceedings.pdf), tr.23–26, chỉ kiểm tra được các đoạn được lập chỉ mục; tải toàn văn timeout. Không dùng làm bằng chứng hiệu quả.
- Chưa xác minh đúng nhan đề “Prior Case Retrieval with Rhetorical Roles”; không gán kết quả các bài trên cho nhan đề này.

## Logic thử nghiệm

### 1. Inventory và feature toàn nguồn

Kiểm tra hash nguồn và parent binding của SourceBlock/SentenceAtom trước khi tính feature. Inventory phủ 100% ký tự, kể cả heading và đoạn ít tín hiệu; nguồn vẫn mở được dù vùng chưa được chọn.

Chấm toàn nội dung block, giữ anchor và occurrence theo offset; không chấm dựa vào preview. Dedup occurrence theo vị trí nguồn, chặn đếm lặp/cộng vô hạn cùng pattern. Không lấy trung bình khiến proposition ngắn chìm trong block dài. Block dài vẫn có địa chỉ và trạng thái; không âm thầm loại vì quá cap.

| Feature | Cách trích ở bản rule đầu | Vai trò |
|---|---|---|
| Quyền/nghĩa vụ/tiêu chuẩn | Pattern cụm diễn đạt, chủ thể/predicate khi có thể nhận diện | Kênh proposition, không xác nhận AU |
| Điều kiện/ngoại lệ/phủ định | `where`, `unless`, `subject to`, `not sufficient`, `does not`… | Qualification và context hint |
| Standard of review | Cụm review/correctness/reasonableness/deference | Kênh riêng cho proposition ngắn |
| Application/hệ quả | Tình huống + đánh giá/hệ quả pháp lý | Tín hiệu cho fact-pattern reasoning; `in this case` đơn lẻ không đủ |
| Reporting voice/quotation | Speaker cue, quote state, chuyển voice | Hint tìm attribution và court response; NER không suy speaker |
| Citation/reference/marker | Rule nhận diện mention và suppression marker | Kênh authority, không hard filter |
| Statute gắn với proposition | Reference đi cùng nghĩa vụ/quyền/diễn giải | Khác với mật độ số điều luật |
| Rationale/phân biệt | `because`, `policy reasons`, `for that reason`, `unlike`… | Lý do và distinguishing |
| Structure/vị trí/độ dài | Cấu trúc thật, source order, atom count, bytes | Đóng gói và khám phá; không sinh heading giả |

NER, terminology nâng cao, encoder và rhetorical-role model là **thành phần chưa bật** trong lần offline rule đầu; ghi rõ missing feature, không giả vờ đã có semantic model. Không train mô hình.

### 2. Hàng đợi và thứ tự đọc

- Proposition pháp lý: rule, rights/duties, review, statutory interpretation.
- Application/phân biệt: tình huống dẫn đến hệ quả, exception và rationale.
- Reported authority: citation/quotation/reference có nội dung cần đọc.
- Context: qualification, speaker hoặc tham chiếu chưa rõ. Quan hệ do rule suy ra là hint, không phải dependency đã xác nhận.
- Khám phá: vùng chưa đọc, vị trí khác nhau, giữa block dài, ít tín hiệu hoặc tín hiệu bất đồng.

Các tổ hợp feature sắp thứ tự **trong từng hàng đợi**. Scheduler xen kẽ hàng đợi và có chống starvation; không lấy top-k duy nhất từ tổng trọng số chưa hiệu chuẩn. Một vùng xuất hiện nhiều hàng đợi chỉ dispatch một lần. KOS kind/Issue/Claim/Evidence không tham gia selector.

Cost dùng để đóng gói/trì hoãn có ghi nhận; không biến vùng dài thành negative. Diversity giãn thứ tự, không xóa đoạn tương tự có condition, negation hoặc exception khác nhau. Chỉ collapse source span thực sự trùng.

### 3. Region để mô phỏng đọc

Region giữ exact TARGET/CONTEXT refs, source hash và quote. Dùng toàn target block cùng atom lân cận có giới hạn; mở thêm theo quote/reporting/qualification hoặc reference hint. Ghi rõ phần dependency chưa mở được. Không ép ranh giới semantic hoặc tạo global LegalUnit partition.

Mỗi request giả lập độc lập phải có context cần thiết; không giả định model nhớ phần đã gửi. Gộp span chồng lấn **trong request**, nhưng context gửi lại ở request khác vẫn tính vào chi phí. `exposed/delivered` offline không phải `semantically_assessed`.

### 4. Đối chứng

- `source_order`: đọc toàn inventory theo nguồn; cùng region renderer và cost profile.
- `cue_control`: thứ tự theo rule keywords đơn giản trên toàn block, occurrence đã dedup; không đồng nhất với run H cũ vốn chỉ có 30 target/preview.
- `multi_queue`: bộ ưu tiên nhiều hàng đợi đề xuất.

Khóa policy/seed/feature version trước khi xem coverage KOS. Không thay weights để tăng điểm trên KOS-5 sau khi thấy kết quả. Cấu hình đầu chỉ là giả thuyết vận hành, chưa là bộ xếp hạng tốt nhất.

## Kiểm tra offline bắt buộc

1. **Evidence xuất hiện sớm:** align quote KOS với nguồn exact hoặc whitespace-only; ghi lần đầu/cumulative cost khi full evidence span được TARGET mở, và riêng khi nó chỉ là CONTEXT. Partial overlap không tính full coverage.
2. **Theo loại nội dung:** nhóm KOS kind để báo cáo; thêm nhóm no-marker từ source aligned, application/exception theo cue chẩn đoán. Các nhóm sau không phải nhãn semantic, có thể chồng nhau. Hai án query không có AU KOS thì denominator bằng 0/NA, không tự ghi 100%.
3. **Điều kiện/attribution:** xem exact context lân cận, condition/reporting/quote/reference hints và phần chưa mở. Lập packet nguồn để review. Không gọi việc có từ `unless` hoặc một atom trước/sau là đã bảo toàn mọi dependency xa.
4. **Preview overlap:** thêm preview chồng lấn không làm đổi feature/priority/schedule vì scorer dùng source. Có regression tái hiện scorer cũ đếm một occurrence `court` thành ba.
5. **Tên riêng:** trên bản sao fixture và nguồn thật, thay PERSON/ORG surface forms được chọn trước bằng placeholder; giữ rolewords/thuật ngữ pháp lý. Dùng ordinal hoặc mapped offsets để so thứ hạng vì độ dài thay đổi. Báo số đảo/độ lệch thứ hạng; không tuyên bố đây là NER corpus-wide hoặc tên riêng luôn vô nghĩa.
6. **Negation/exception:** hai vùng lexical-similar nhưng khác qualification vẫn tồn tại; không semantic-dedup. Kiểm tra cả đoạn rule lẫn qualifier có mặt trong lịch.
7. **Coverage theo ngân sách:** tại 10/25/50/75/100% cost exhaustive, báo full evidence TARGET coverage, CONTEXT exposure, covered source characters, phần chưa mở, theo án và nhóm. Báo đường cong, không chỉ Recall@k theo số vùng.

## Hạch toán token và giới hạn offline

Provider requests/token thực = **0**. Venv hiện chưa có tokenizer Qwen/Transformers/tokenizers/tiktoken; không tải phụ thuộc hoặc model trong đợt này. Cost mặc định là **ước lượng** UTF-8 bytes/4, có kiểm tra độ nhạy bytes/3 và bytes/5; cùng renderer/scaffold cho mọi arm. Báo exact bytes và source characters bên cạnh estimated tokens.

Scaffold/IDs/TARGET/CONTEXT đều tính vào rendered cost; ghi rõ đây là renderer thử offline, chưa phải token thực hoặc chi phí inference của contract production. Không lấy union source chars làm token bill vì context/prompt có thể lặp. Không kết luận giảm GPU giờ/latency LLM/USD từ phép thử này.

## Bàn giao và cổng quyết định

- MD kế hoạch này, policy/fingerprints, full-source inventory và feature anchors.
- JSON lịch đọc các arm; per-AU alignment/first-open/coverage/cost; source review packet và đường cong theo budget.
- Báo kiểm thử độc lập, lệnh tái hiện, kết quả formal riêng với kết quả coverage tham khảo.
- Nguồn/hash/offset/coverage inventory phải đúng; KOS không được ảnh hưởng lịch; metamorphic tests phải báo kết quả thật; incomplete/ambiguous/no-match/dependency unknown không bị che.
- Multi-queue chỉ được xem là có tín hiệu tốt nếu giữ evidence tham khảo sớm hơn tại cùng cost mà không mất qualification trong packet kiểm tra. Không được chứng nhận AU recall/gold/semantic completeness, không mở remote run chỉ vì formal PASS.
- Nếu không tốt hơn đối chứng, giữ kết quả FAIL/không cải thiện và phân tích, không tuning trực tiếp theo KOS để báo thắng.

## Trạng thái

Đã chạy prototype offline toàn KOS-5; kiểm thử độc lập được ghi trong báo cáo riêng. [Kết quả và quyết định](../../pipeline_v1/outputs/region_priority_offline_20261013/RESULT.md): multi-queue chưa thắng các đối chứng ở budget thấp, chưa thay default hoặc mở toàn corpus. Kết quả formal không phải qualified-evidence/semantic PASS.

Kiểm tra đầu vào độc lập: 61 file KOS đúng manifest, 18 AU, không có lỗi parse; 9 evidence exact và 9 whitespace-normalized, tất cả ánh xạ duy nhất. Nguồn gồm 431 SourceBlock, 1.240 SentenceAtom, 206.853 ký tự. Hai án query không có AU KOS; vẫn chạy inventory/scheduler trên cả năm án.

Các ca context cần kiểm tra riêng: excerpt `045155-classification-reasons-s27` bị cắt trước phần subsection 27(3); `045155-policy-reasons-exhaust` bị cắt trước đoạn nêu ngoại lệ và áp dụng; `045155-exhaust-grievance-general` cần xét exception ở paragraph tiếp theo; `099980-right-to-make-submissions` bị cắt giữa từ và cần phần kết điều kiện cùng section 72. Coverage excerpt không đồng nghĩa đã mở đủ các phần này.
