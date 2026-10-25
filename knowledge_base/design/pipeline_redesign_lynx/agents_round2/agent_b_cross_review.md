# Agent B — phản biện chéo chính thức vòng 2

## 1. Steelman phương án Agent A

Phiên bản mạnh nhất của A không phủ nhận source-first pipeline. A bổ sung điều kiện để lời hứa “source không mất” trở thành coverage có thể kiểm tra: raw retrieval phải đủ mạnh và phải ghi rõ case nào bị fusion làm rơi; evidence resolver phải chứng minh đã tìm ở đâu; mỗi field suy ra phải gắn đúng witness; lỗi hiếm nhưng nghiêm trọng phải có gate riêng. Cách nhìn này phù hợp với ưu tiên correctness trước cost và sửa một khoảng trống thật của bản 03–08: structural validity hiện mạnh hơn retrieval và semantic validity.

Tôi đồng ý với lõi đó. Các số **đã đo** là corpus có 9.556 án, 279.096.251 ký tự, 1.721 án không có standalone marker và máy quan sát được chỉ có GTX 1650 4 GB. Việc BM25 bỏ sót paraphrase, source floor làm rơi raw hit, hoặc resolver dừng trước response xa hiện là **suy luận có cơ sở**, chưa phải lỗi đã đo trên holdout mới. Lợi ích của dense retrieval, field-level witness và whole-case fallback vẫn là **giả thuyết cần thí nghiệm**.

## 2. Năm phản biện quan trọng

### 1. Semantic-raw nên là arm song song, chưa nên thay R0

**Claim →** A đề nghị thêm dense/semantic raw lane vào baseline và chỉ gọi R0 là coverage baseline nếu hybrid không tạo gain. **Evidence/phản ví dụ →** Chưa có encoder, chunking, index config hay throughput được khóa; dense lane thay cả retrieval function lẫn compute. GTX 1650 4 GB và 279M ký tự làm build/index cost đáng kể nhưng chưa đo. **Consequence →** Nếu gộp dense vào R0, lợi ích của sidecar và chi phí corpus-time không còn quy được; baseline tối thiểu mất ý nghĩa. **Fix →** Giữ `R0-L = BM25 raw`; thêm `R0-S = semantic raw` và `R0-H = hybrid raw`, dùng cùng source spans, case budget và snapshot. Chỉ productionize R0-H nếu thắng quality–cost gate. **Test →** So paired Recall@50/100/200, unique relevant cases, build/query compute và latency trên masked-citation/paraphrase/no-citation slices.

### 2. Union mở rộng chỉ là phép đo ceiling, không phải so sánh vận hành

**Claim →** A đề nghị union budget mở rộng để đo coverage tiềm năng và fixed budget để đo trade-off. **Evidence/phản ví dụ →** Union tăng số case được đọc, context và downstream calls; recall cao hơn có thể chỉ do ngân sách lớn hơn. **Consequence →** Nếu báo chung, annotation lane có vẻ cải thiện coverage nhưng không chứng minh hiệu quả. **Fix →** Gắn nhãn rõ `coverage ceiling` cho union; quyết định production chỉ dựa trên fixed frontier đã khóa đồng thời case-K, hit-K, unique chars, calls và latency. Source floor phải là quota số nguyên với tie-break/dedup cố định và log gained/lost. **Test →** Property test containment và paired Pareto frontier; báo riêng `lost_relevant_raw_cases`.

### 3. Searched frontier cần có trần chi phí và thứ tự cố định

**Claim →** A yêu cầu local → section → related mentions → bounded scan → whole-case control cho từng obligation. **Evidence/phản ví dụ →** Đây là cách tăng correctness hợp lý, nhưng case P99 dài 146.898 ký tự; nhiều candidate cùng case có thể lặp whole-case scan. **Consequence →** Resolver có thể tái tạo lỗi đọc lặp V13–V15 và phá cap LLM dù mỗi bước riêng lẻ hợp lệ. **Fix →** Lưu frontier dùng chung theo `(case, source_hash, obligation type)`, trừ trùng span trước dispatch, và khóa cap unique chars/case/query, calls và wall-clock. `whole_case` chỉ là control offline hoặc fallback local không dùng provider token. **Test →** Distance-stratified slice; so obligation recall với unique/repeated chars, calls và p95 latency. Bác route nếu gain chỉ xuất hiện khi vượt cap.

### 4. Field-level provenance đúng, nhưng acceptance phải theo profile record

**Claim →** A yêu cầu mọi proposition, attribution, qualifier và treatment đều có witness riêng trước khi record được `accepted`. **Evidence/phản ví dụ →** Treatment cần two-witness, nhưng một citation mention hoặc authority link không nhất thiết có qualifier/treatment áp dụng. Bắt mọi chiều cho mọi record sẽ tăng annotation, verification và unresolved giả. **Consequence →** Schema và cost phình; record đơn giản bị chặn bởi field không áp dụng. **Fix →** Thêm acceptance profile theo `record_type`; mỗi field có `applicability = required | optional | not_applicable`, rồi `{status, evidence_refs, verifier, reason}`. Chỉ field `required` cần witness. **Test →** Mutation test tráo/bỏ witness và test record không có field áp dụng; validator phải từ chối mutation nhưng không ép verification thừa.

### 5. Safety slice cần power gate đăng ký trước, nhưng không được dùng để ngoại suy prevalence

**Claim →** A yêu cầu oversample lỗi nghiêm trọng và double-annotate toàn bộ critical slice. **Evidence/phản ví dụ →** Mẫu 40 holdout theo split × length không đủ positive là đúng; nhưng oversampling theo rule làm phân bố khác corpus và các slice có thể chồng nhau. **Consequence →** Có thể đánh giá safety tốt nhưng ngoại suy sai số lỗi và chi phí cho 9.556 án, hoặc đếm chồng stratum. **Fix →** Tách representative sample để ước lượng prevalence/cost khỏi enriched safety sample để đặt severe-error ceiling; khóa cluster, inclusion probability và trọng số trước annotation. Không cộng các structural slice chồng nhau trong `corpus_cost`. **Test →** Báo weighted corpus estimate và unweighted worst-slice CI riêng; thiếu positive hoặc CI quá rộng phải kết luận `insufficient evidence`.

## 3. Điều B thay đổi sau khi đọc A

Tôi bổ sung ba yêu cầu vào lập luận ban đầu của B. Thứ nhất, `source floor` phải là invariant tập hợp có gained/lost log, không chỉ là mô tả kiến trúc. Thứ hai, evidence resolver phải ghi `searched_ranges`, `search_modes` và phân biệt `frontier_exhausted` với `budget_exhausted`. Thứ ba, provenance phải gắn witness theo field và acceptance profile, thay vì một `evidence_refs[]` chung. Tôi vẫn giữ quan điểm rằng dense retrieval, whole-case scan và tăng mẫu chỉ được nhận sau phép đo chi phí tương ứng.

## 4. Phân xử

### Must-fix trước khi chốt spec

- Khóa route manifest lồng nhau cho R3 và bốn hard cap, tính cả retry/context expansion.
- Định nghĩa source-floor quota, tie-break, dedup và gained/lost trace.
- Bổ sung searched-frontier ledger có cap unique chars/calls/time và cache dùng chung trong case.
- Đổi provenance sang field-witness với acceptance profile theo record type.
- Khóa gate định lượng cho local compute; mutation matrix và dependency closure cho update/cache.
- Tách mẫu đại diện khỏi safety oversample; quy định weighting, overlap và `insufficient evidence`.

### Chỉ quyết định bằng thực nghiệm

- BM25 so với semantic-raw và hybrid raw.
- Union coverage ceiling so với fixed-budget production frontier.
- Whole-case local control và từng mức frontier expansion.
- Từng model local/sidecar, AU/derived lane và LLM cap 0/1/5/10%.
- Ngưỡng mẫu cần mở rộng, dựa trên CI/power rule đã đăng ký trước.

