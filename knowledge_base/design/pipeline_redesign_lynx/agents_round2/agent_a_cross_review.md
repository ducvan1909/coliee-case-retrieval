# Agent A — phản biện chéo chính thức vòng 2

## 1. Steelman thiết kế của Agent B

Phiên bản mạnh nhất của B là một hợp đồng thực nghiệm có thể bác bỏ, không phải lời hứa rằng pipeline đã rẻ. B buộc các arm dùng cùng workload, route manifest và các tập LLM lồng nhau; tính cả retry, cache provenance, local compute và rebuild; đồng thời yêu cầu dependency closure được kiểm tra bằng incremental-versus-full rebuild. Cách này sửa đúng một nhược điểm lớn của V13–V15: một run có thể trông tiết kiệm chỉ vì đọc ít hơn, lỗi sớm hoặc hưởng cache đã trả tiền ở run khác.

Tôi chấp nhận bốn nguyên tắc của B: cap LLM phải gồm case, source chars, provider token và request; model local phải có gate định lượng trước khi chạy toàn corpus; cold, warm, failed và resumed run phải báo riêng; update cost phải đo theo mutation type thay vì chỉ theo tỷ lệ file đổi. Đây là phần cần đưa vào `04` và `05`.

Ký hiệu: **[F]** fact đo/đọc trực tiếp; **[I]** suy luận; **[H]** giả thuyết cần thử.

## 2. Năm phản biện quan trọng

### 1. Route manifest bất biến có thể làm phép đo công bằng nhưng khóa luôn omission

**Claim →** B đề nghị tạo manifest từ R3-0 rồi dùng các tập lồng nhau `1% ⊂ 5% ⊂ 10%`.

**Evidence →** **[F]** `04` cho candidate đến từ raw retrieval, rule/local annotation và disagreement; `05` chỉ đánh giá omission bằng lấy mẫu span không được builder chọn. **[I]** Nếu R3-0 không tạo candidate cho đoạn no-citation hoặc court response xa, mọi cap LLM đều không thể sửa omission đó.

**Consequence →** Đường 0/1/5/10% chỉ đo lợi ích trên candidate đã thấy, rồi có thể kết luận LLM bão hòa trong khi lỗi nằm ở discovery.

**Fix →** Khóa hai artifact: manifest chính để so paired routing và một sentinel manifest lấy mẫu phân tầng từ vùng không được chọn. Báo riêng `conditional quality | candidate` và end-to-end omission; LLM không được dùng sentinel để thay đổi holdout manifest.

**Test →** Human review mù trên selected và sentinel spans. Nếu omission ở sentinel vượt ceiling đăng ký trước, không được kết luận routing đã đủ dù paired quality tăng.

### 2. Budget tương đương chưa đủ nếu baseline retrieval chỉ là lexical BM25

**Claim →** B yêu cầu so arm tại cùng case-K, hit-K, source chars, calls và wall-clock.

**Evidence →** **[F]** R0 hiện là paragraph/window BM25; citation trong query bị che và `08` đã ghi lexical miss là failure mode. **[H]** Raw semantic retrieval có thể tìm paraphrase mà BM25 bỏ sót mà không cần AU hay annotation.

**Consequence →** Enrichment có thể được đánh giá trên một baseline raw yếu; hoặc bị xem là cần thiết chỉ vì thiếu một raw semantic lane rẻ hơn và ít rủi ro ngữ nghĩa hơn.

**Fix →** Trước R1–R3, đo ba baseline source-only: BM25, semantic-raw và hybrid, cùng exact-span provenance. Chọn baseline raw tốt nhất dưới budget đã khóa; không gọi BM25 đơn lẻ là coverage baseline.

**Test →** So Recall@50/100/200, unique relevant cases và compute trên masked-citation, paraphrase và no-citation slices. Nếu semantic-raw không tạo gain, giữ BM25 để đơn giản hóa.

### 3. Hard cap cần thứ tự ưu tiên rõ để không biến hết ngân sách thành `unresolved` có vẻ an toàn

**Claim →** B yêu cầu dừng khi cap đầu tiên chạm.

**Evidence →** **[F]** EvidenceBundle có nghĩa vụ speaker, qualifier và authority response; `04` cho phép dừng unresolved khi hết budget. **[I]** Hai arm cùng token cap vẫn có thể phân bổ rất khác: một arm mở rộng nhiều candidate nông, arm khác hoàn tất ít candidate với đủ witness.

**Consequence →** Chi phí so được nhưng chất lượng không cùng nghĩa; tỷ lệ `unknown/unresolved` cao có thể che omission hoặc làm structured view vô dụng.

**Fix →** Khóa scheduler: ưu tiên hoàn tất obligation đang mở trước khi nhận candidate mới, trừ source-floor retrieval; log `budget_exhausted` tách khỏi `frontier_exhausted`. Báo coverage theo candidate và từng obligation, không chỉ accuracy trên record đã hoàn tất.

**Test →** Replay cùng manifest với breadth-first và obligation-completion scheduler. So severe error, unresolved rate, candidate coverage và token; chọn scheduler trên đường Pareto đã đăng ký.

### 4. Dependency closure phải bao gồm phụ thuộc ngữ nghĩa cấp field

**Claim →** B đề nghị mutation matrix và dirty closure theo artifact.

**Evidence →** **[F]** `Annotation` có `dependencies[]`, nhưng `DerivedRecord` chỉ có evidence chung và fingerprints. **[I]** Đổi authority linker có thể làm stale riêng treatment/court-response của một AU mà source span và proposition vẫn đúng.

**Consequence →** Invalidation toàn record gây rebuild thừa; invalidation quá hẹp giữ field sai nhưng checksum artifact vẫn hợp lệ.

**Fix →** Mỗi field được suy ra phải lưu producer, dependency refs và witness refs riêng. Dirty closure truyền theo field rồi mới materialize lại record/index; accepted status bị hạ nếu một chiều bắt buộc trở thành stale.

**Test →** Mutation lần lượt source, segmentation, citation rule, authority model, prompt và fusion. Incremental output sạch phải giữ checksum; field bẩn và accepted/index state phải khớp full rebuild.

### 5. Gate vận hành không được chốt trước gate an toàn ngữ nghĩa

**Claim →** B yêu cầu khóa ngưỡng GPU/CPU giờ, RAM/VRAM, OOM, latency và rebuild trước run.

**Evidence →** **[F]** Máy có GTX 1650 4 GB nhưng RAM chưa đo được; 40 holdout không bảo đảm đủ speaker conflict, distant response hoặc qualifier positives. **[I]** Một model rất nhanh vẫn không phù hợp nếu false acceptance tập trung ở slice hiếm.

**Consequence →** Pipeline có thể vượt compute gate rồi được mở rộng dù chưa đủ bằng chứng an toàn; hoặc bị loại bởi một budget tùy ý trước khi biết đường đánh đổi.

**Fix →** Gate hai tầng: semantic safety trước (`severe-error ceiling`, worst-slice non-inferiority, minimum positives), sau đó feasibility envelope. Khi chưa có ngân sách vận hành thật, báo Pareto frontier và `insufficient evidence`, không tự đặt một pass/fail duy nhất.

**Test →** Double-annotate toàn bộ critical slices, tính CI theo case/authority cluster; chỉ dự toán 9.556 án cho model đã qua gate semantic tối thiểu.

## 3. Điều A thay đổi sau khi đọc B

Tôi bổ sung route manifest lồng nhau, scheduler/cap có checksum, ledger actual-versus-amortized cost và mutation matrix như yêu cầu bắt buộc. Tôi cũng đồng ý rằng throughput gate phải được đăng ký trước holdout, nhưng đổi nó thành feasibility envelope nếu chưa có ngân sách vận hành thực. Tôi không còn xem “cùng candidate count” là so sánh đủ; phải ghi unique chars, calls, latency và completion của evidence obligations.

## 4. Phân xử

**Must-fix trước khi chốt spec:** route manifest chính + sentinel; baseline raw semantic/hybrid hoặc hạ lời hứa coverage; scheduler và stop reasons; provenance/dependency cấp field; định nghĩa actual/amortized cache cost; mutation matrix; semantic safety gate trước scale gate.

**Experiment-only:** chọn mức cap 1/5/10%; ngưỡng throughput cụ thể; BM25 so với semantic-raw; breadth-first so với obligation-completion; mức source floor/fusion; worker local nào thắng transfer test. Các mục này không được ghi thành hiệu quả đã xác nhận trước khi đo.
