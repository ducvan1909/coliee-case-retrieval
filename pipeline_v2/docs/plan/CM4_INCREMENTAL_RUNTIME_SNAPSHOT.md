# CM4 — snapshot tăng dần, dựng payload và giảm input không mất căn cứ suy luận

Ngày thiết kế: 23/11/2026. Cập nhật 24/11/2026: **stage A–D đã triển khai code và kiểm local; profile prompt/navigation mới opt-in, chưa xác minh chất lượng live**. Các mục thiết kế bên dưới giữ như bản đề xuất; trạng thái thực hiện và giới hạn ở mục 19.

Phạm vi khảo sát thiết kế: checkout `G:/Git/coliee-case-retrieval`, HEAD `0c2da9f50321935dc989992ea736da6b8e98da2e`. Đợt viết thiết kế ngày 23/11 chỉ sửa tài liệu. Ngày 24/11 người dùng đã yêu cầu “thực hiện kế hoạch đi”: authorization mới cho triển khai/kiểm local, vẫn không gọi inference/deploy hoặc sửa ledger/snapshot lịch sử.

## 1. Quyết định đề xuất

Ưu tiên tối ưu này trước các thay đổi chính sách model: mỗi Engine giữ một projection của ledger trong RAM; startup/resume đọc và replay một lần; khi chạy tiếp chỉ áp dụng event vừa commit. Các khâu đọc trong cùng một phase dùng chung state/context và các chỉ mục đã dựng, thay vì tự đọc SQLite, giải mã JSON và replay riêng.

Một lượt controller có nhiều phase: trước admission, sau admission, sau receipt, sau action. **Dùng chung theo cùng mốc `seq`, không giữ nguyên một snapshot xuyên các lần ghi của cả lượt.** Sau mỗi commit phải cập nhật projection trước khi khâu tiếp theo đọc. Context đang chỉnh sửa phải tách khỏi context đã commit.

Mục tiêu của **ưu tiên 1–2, mục 1–13** là giữ nguyên payload, schema, thứ tự ref/ứng viên, cách tính coverage, quyết định và usage với cùng chuỗi event/action, trong cùng prompt/navigation policy. Model vẫn quyết định như hiện tại. Tối ưu host không chứng minh tăng chất lượng COLIEE, và không bảo đảm một lần gọi model mới sẽ tái tạo y hệt quyết định cũ.

Không cần framework/checkpointer mới. Ledger tiếp tục là nguồn sự thật bền vững; RAM là dữ liệu suy ra có thể bỏ và dựng lại. Chưa thêm snapshot ghi ra đĩa hoặc đổi định dạng event trong đợt đầu.

**Ưu tiên 2, bổ sung theo yêu cầu:** dựng phần payload dùng chung một lần, cache projection theo đầy đủ dependency của state/context/span, giảm dựng thử vùng đọc và kiểm token chính xác trước admission. Thiết kế chi tiết ở [mục 13](#13-ưu-tiên-2--giảm-dựng-thử-payload-khi-chọn-span-vừa-context). Mục 1–12 tập trung vào runtime/ledger; mục 13 xử lý riêng phần dựng payload còn lặp sau khi đã có runtime.

**Ưu tiên 3, bổ sung sau audit catalog trên HEAD hiện tại:** giảm mô tả lặp trong catalog khảo sát A, dùng instructions theo pha và chỉ tự chuyển trang khi không còn lựa chọn cần model. Thiết kế ở mục 14–18. Những thay đổi này chủ động đổi prompt hoặc navigation policy, nên có gate riêng; không được dùng PASS byte-parity của snapshot để tuyên bố model suy luận không kém đi. Đợt đầu giữ nguyên packet bằng chứng và decoder, giữ cả API đánh giá đơn; chưa tăng lượng raw để dùng hết phần context vừa tiết kiệm.

Yêu cầu “không giảm hiệu suất suy luận” được hiểu là giữ quyền truy cập bằng chứng, điều kiện phân biệt nguồn và các quyết định cần model, đồng thời không làm giảm chất lượng quyết định. Phần đầu kiểm được offline; phần chất lượng của prompt mới cần model/pilot do người dùng hoặc AG chạy sau này. Hiện chỉ đề xuất tài liệu, không cấp thêm authorization triển khai hoặc gọi provider.

## 2. Bằng chứng và giới hạn của nhận định

### 2.1. Đối chiếu số đo thật

Đã đọc trực tiếp các artifact sau bằng Python local, không gọi provider:

- [result.json của pilot](../../../cache/cm4-survey-first-ag-20261123-120716794/result.json): `timing_profile`.
- [trace.jsonl](../../../cache/cm4-survey-first-ag-20261123-120716794/trace.jsonl): các dòng `event=timing_breakdown`, `scope=compile_context`.
- [ledger SQLite](../../../cache/cm4-survey-first-ag-20261123-120716794/session/events.sqlite3): mở `mode=ro` để đếm event và kích thước record.

Các đường dẫn cache là artifact local, có thể không có trên máy khác.

| Số đo | Kết quả đã đối chiếu | Cách hiểu |
| --- | ---: | --- |
| Tổng `ledger_read.calls` trên các scope đã profile | 14.012 | Gồm compile, action, guard, reply, inspect và restore guard. Không bao gồm mọi lần đọc ngoài scope đã bật profile. |
| Tổng `ledger_read.total_ms` | 2.980.071,939 ms = 49,668 phút | Tổng thời gian exclusive của phần đọc; không cộng lại với thời gian scope cha. |
| Compile | 179 mẫu, tổng 3.168,906 giây | Có cả lượt cuối chưa có action tiếp theo. |
| `ledger_read` bên trong compile | 10.481 lần, 2.341,369 giây | Khoảng 73,89% tổng thời gian compile của run này. |
| Trung vị compile 20 lượt đầu | 0,70632 giây | Chỉ so hai cửa sổ 20 lượt, không phải mọi mode có tải tương đương. |
| Trung vị compile 20 lượt cuối | 33,31580 giây | Khoảng 47,17 lần cửa sổ đầu; có thể bị ảnh hưởng bởi mode và số lần thử fit. |
| `ledger_state_replay` trong compile | 1.577 lần, tổng 2,069 giây | CPU của reducer nhỏ hơn rất nhiều so với đọc/giải mã ledger trong phép đo này. |
| Ledger cuối run | 716 event; `seq=1..716`; tổng `length(record)=30.919.728` byte | Dung lượng record lưu trữ, không phải RAM của object Python sau giải mã. |

Phân bố số lần đọc: compile 10.481; progress guard 2.492; execute action 605; reply/receipt 427; final inspect 6; restore guard 1. Riêng progress guard mất 458,241 giây trong `ledger_read`, nên chỉ sửa `prepare()` sẽ bỏ sót chi phí đáng kể.

Run có 179 request, 178 action; `prediction=null`, `selection_status=pending_selection`. Usage còn một request chưa biết input/output/provider latency. Đây là số đo overhead host của pilot dang dở, không phải kết quả F1 hoặc bằng chứng tiết kiệm token.

### 2.2. Đánh giá độc lập giả định ban đầu

Đồng ý rằng đây là ưu tiên có bằng chứng mạnh: code hiện vẫn đọc toàn bộ record và giải mã lại; dữ liệu lịch sử tăng sẽ làm mỗi lần đọc tốn hơn. Tuy nhiên cần chỉnh hai điểm trong cách quy nguyên nhân:

1. **Đọc/giải mã lại là phần lớn nhất đo được**, không phải riêng vòng `RunState.apply()`. Chỉ cache RunState nhưng giữ nguyên các lần `events()` sẽ không giải quyết phần lớn chi phí.
2. Không thể lấy 49,668 phút làm lời hứa tiết kiệm nguyên vẹn. Vẫn còn startup, đọc delta, serialization event mới, copy context làm việc, dựng catalog, nguyên văn, tokenizer và fit payload. Cần replay trước/sau trên cùng đầu vào mới biết mức giảm thực tế.

Nhãn `ledger_read` hiện gộp mở kết nối, SQL, đọc record và `json.loads`; chưa đủ dữ liệu để phân rã chính xác từng phần. Mức tăng compile cũng chưa chứng minh chỉ có một nguyên nhân. Mục tiêu đợt này là loại cơ chế lặp đã xác nhận, rồi đo phần còn lại.

## 3. Code hiện hành và những chỗ phải đi qua

Các line bên dưới thuộc HEAD khảo sát; có thể dịch chuyển khi triển khai.

| Điểm | Hành vi hiện tại | Hướng thay |
| --- | --- | --- |
| [Ledger._read](../../agent_harness/ledger.py#L68) | `SELECT seq, record FROM events ORDER BY seq`, `json.loads` từng record, tạo list mới. | Giữ API full read phục vụ audit; thêm API đọc suffix theo `seq`. |
| [AgentHarness.events / _write](../../agent_harness/harness.py#L95) | `events()` luôn đọc DB; `_write()` append rồi `state.apply(event)`. | CM4 dùng runtime chung; hook sau commit cập nhật context/index/hash, không apply state lần hai. |
| [Engine.state/context](../../experiments/context_manager_v2/engine.py#L501) | State replay toàn bộ; context duyệt mọi event, deep-copy mỗi `cm_context` rồi overlay `cm_auto_query_view`. | Giữ state hiện tại và context đã commit; apply đúng một event mới. |
| [prepare](../../experiments/context_manager_v2/engine.py#L2432) | Đọc/replay đầu hàm, sau đó helper đọc lại; vòng fit gọi registry/catalog/feedback nhiều lần. | Một phase chung; reuse các projection không phụ thuộc kích thước payload. |
| [reply / execute_pending](../../experiments/context_manager_v2/engine.py#L2592) | Mỗi operation lại full replay; nhiều bước kiểm gọi history riêng. | Sync suffix khi lấy writer lock, rồi dùng state mới nhất; đổi phase sau từng event. |
| [live.run_loop](../../experiments/context_manager_v2/live.py#L288) | Điều kiện vòng lặp, guard, trace và inspect gọi state/context nhiều lần; comprehension lấy 5 field context gọi context 5 lần. | Lấy một read view sau mỗi boundary, truyền chung vào guard/trace/inspect. |
| [Snapshot.from_events](../../experiments/context_manager_v1/core.py#L97) | Tự tạo RunState, quét lịch sử nhiều vòng, copy cấu trúc và hash cả prefix. | Dùng chỉ mục runtime tương đương trong CM4; giữ hàm cũ làm oracle kiểm hồi quy. |
| [query_review.queries](../../experiments/context_manager_v2/query_review.py#L9) | Dựng action/request/query rồi tính exposure từ toàn lịch sử ở mỗi lần gọi. | Index query/exposure theo event; overlay priorities/conclusions theo context đang dùng. |
| [passage_review.delivered](../../experiments/context_manager_v2/passage_review.py#L123) | Nối admission/receipt bằng cách quét history cho mỗi case. | Index span đã giao theo `(case_id, source_hash)`, giữ nguyên thứ tự và duplicates nếu API cũ cần. |
| [M6 registry](../../m6.py#L214) | Quét observation/action/outcome để tính used, exhausted read, leads và target. | Tách dữ liệu suy ra theo event khỏi phần render theo payload; CM4 dùng index qua hook có mặc định tương thích. |

Các điểm liên quan khác phải kiểm: `IntegratedHarness._registry`, `_feedback`, `_rows`, `_catalog`, `_canonical_hybrid_need`, `_transition_result`, `opened_lead_keys`, `bind_repair`, `visible_repair`, lịch sử tái dùng hybrid và đoạn tìm need trong `execute_pending`. Giữ các kiểm journal/provenance của paid search reuse, không thay bằng một cờ cache.

## 4. Kiến trúc và quyền sở hữu dữ liệu

### 4.1. Một runtime cho một Engine/run

Thêm module dự kiến `context_manager_v2/runtime_snapshot.py` với `RuntimeSnapshot` và read view. Đây là tên thiết kế, chưa phải API có sẵn.

Runtime giữ:

- Identity của run/directory đã resolve và binding đã kiểm bởi `_start()`; không dùng cache toàn cục theo mỗi đường dẫn hoặc `max(seq)`.
- `last_seq`, `generation` trong bộ nhớ và cờ `valid`. `seq` là cursor dữ liệu; `generation` phát hiện view cũ đang bị dùng qua commit.
- Một RunState nội bộ, context đã commit, các index cần thiết, hasher prefix và dữ liệu event còn thực sự cần cho compatibility.
- Read view theo phase và memo cho dữ liệu suy ra theo revision; memo của phase cũ hết hiệu lực sau commit.

Ledger không trở thành state manager. Thêm khả năng đọc delta và hook tối thiểu vào harness, nhưng chỉ Engine CM4 bật runtime này trước. M4/M5/M6 khác vẫn có default cũ cho đến khi có nghiệm thu riêng.

### 4.2. Ba loại dữ liệu phải tách

| Loại | Được sửa bởi ai | Vòng đời |
| --- | --- | --- |
| Event đã commit | Không consumer nào được sửa | Ledger là bản gốc; bản RAM phải được bảo vệ khỏi alias mutable. |
| State/context/index đã commit | Chỉ reducer/runtime tại boundary event | Dùng chung để đọc; không truyền object mutable cho bên ngoài. |
| Context/payload đang chuẩn bị | Operation đang compile/execute | Clone một lần từ context đã commit cho operation; clone thêm chỉ khi logic thử fit hiện hành yêu cầu cách ly. Chỉ publish phần được ghi trong event. |

Không dùng `deepcopy(events)` hoặc `deepcopy(RunState)` làm snapshot cho mỗi helper/lượt. Chỉ copy object nhỏ hoặc nhánh cần chỉnh sửa. Khi context hiện tại đã lớn, giai đoạn đầu có thể clone **một context hiện tại** để giữ semantics; đo riêng chi phí này trước khi tính copy-on-write theo nhánh.

Không trả trực tiếp cached RunState từ API công khai rồi để caller sửa. `RunState.apply()` hiện giữ tham chiếu đến nhiều field event; `RunState.snapshot()` cũng trả alias cho catalog/needs/pending. Chỉ bọc object ngoài bằng frozen dataclass không bảo vệ được dict/list bên trong. Cần read facade nội bộ hoặc ownership rõ cùng kiểm mutation; `inspect()` và API compatibility trả dữ liệu tách rời ở biên xuất kết quả.

## 5. Đọc ledger và cập nhật sau commit

### 5.1. API delta đề xuất

Giữ `Ledger.read()`/`_read()` nguyên ý nghĩa full replay. Bổ sung:

```python
read_after(seq, db=None, through_seq=None)
# SELECT seq, record FROM events
# WHERE seq > ? [AND seq <= ?] ORDER BY seq

latest_seq(db)
# SELECT COALESCE(MAX(seq), 0) FROM events
```

`seq` là primary key nên suffix query dùng index có sẵn; xác nhận bằng `EXPLAIN QUERY PLAN` trên fixture. Không thêm index, sửa trigger hoặc giảm `synchronous=FULL` chỉ để tăng tốc.

Startup/resume: dưới writer lock, full read đúng một lần, dựng RunState, context, index và hasher qua cùng chuỗi event. `_start()` vẫn kiểm frozen config, initial observation và whole query. Nếu run mới, khởi tạo runtime rỗng trước khi `_start()` ghi `run_created`; tránh gọi hook khi runtime chưa tồn tại.

Lưu ý `_start()` hiện gán `state.source_hashes[query_id]` trước khi normalize initial result (`harness.py:132`). Với runtime mới, phần chuẩn bị này phải dùng state bootstrap chưa publish hoặc scratch state riêng; chỉ event `run_created` đã commit mới tạo committed projection. Không coi mọi phép sửa state ngoài `apply()` là tự động an toàn chỉ vì trước đây state đó là object tạm.

LoopGuard có lịch sử riêng: `_prime_guard()` (`live.py:250–260`) gọi `observe()` theo các boundary action-result và repair receipt, không thể dựng counters/cycles/seen chỉ từ state cuối. Cho nó consume lại **prefix đã đọc sẵn trong RAM** ở startup, hoặc prime trong pass bootstrap với accumulator riêng tương đương. Không mở ledger full read lần hai và không giữ prefix chỉ vì guard sau khi prime xong. Giữ nguyên semantics guard cũ: hiện nó cập nhật từ `cm_context`, chưa overlay `cm_auto_query_view`; sửa sự khác biệt này phải là thay đổi riêng, không lẫn vào tối ưu.

Mỗi operation ghi (`prepare/reply/execute_pending/stop`): lấy writer lock, đọc head nhỏ, sync suffix nếu một Engine khác đã append khi Engine này nhả lock. Sau đó dùng runtime hiện tại. Không full read cho operation kế tiếp cùng process chỉ vì đã nhả writer lock.

Các lần đọc phục vụ guard/trace trong cùng phase dùng view đã có; đọc độc lập từ public API có boundary sync riêng để giữ khả năng quan sát event writer khác. Chụp `head_seq` và đọc suffix đến đúng head đó trong một read transaction khi không giữ writer lock; tránh trộn state/context từ hai prefix.

### 5.2. Một nơi apply, đúng một lần

Luồng mong muốn:

```text
fields hoàn chỉnh, gồm metadata/cm_context
    -> Ledger.append: encode + SQLite INSERT + COMMIT
    -> apply event vào state đúng một lần
    -> cập nhật committed context, index, prefix hash
    -> publish last_seq/generation mới
    -> emit trace / trả kết quả
```

Đề xuất thêm hook sau commit/apply trong `AgentHarness._write`, mặc định không làm gì; CM4 gắn runtime vào hook này. Vì `_write` hiện là staticmethod, cần rà compatibility khi chuyển thành instance method hoặc chọn callback tương đương. Không tạo thêm một đường `state.apply()` ở Engine trong khi base đã apply.

Chuỗi kế thừa hiện có `IntegratedHarness -> uncapped policy/runner -> M6 -> AgentHarness`. `runner._write()` emit trace **sau** base write, còn `execute_pending()` có wrapper bổ sung context. Hook phải chạy với event **đã serialize và commit**, sau khi fields cuối cùng được dựng, và trước trace của runner. Không đặt hook chỉ sau `super()._write()` ở lớp ngoài cùng: nếu trace ném lỗi thì DB đã ghi nhưng RAM có thể chưa cập nhật.

Nếu commit thất bại: không advance cursor/hash, không publish working context. Nếu commit xong nhưng reducer/index hoặc trace lỗi: đánh dấu runtime invalid; dừng operation, rebuild từ DB tại boundary an toàn trước mọi quyết định tiếp theo. Không tự append lại event hoặc gửi lại provider/tool chỉ vì RAM chưa cập nhật. DB commit có kết quả không rõ cũng phải reconcile trước khi tiếp tục.

Khi sync event từ writer khác, runtime tự apply toàn bộ projection đúng một lần. Khi event do base write đã apply vào chính state nội bộ, hook chỉ cập nhật các projection còn lại. API phải phân biệt hai đường này rõ ràng và assert state/cursor, tránh ngầm dựa vào caller nhớ bỏ một lần apply.

`Ledger.append` trực tiếp trong fixture/replay không đi qua hook; boundary sync suffix phải nhận được những event đó. Không yêu cầu sửa snapshot lịch sử để dùng cache.

### 5.3. Invalidation và process khác

- Chấp nhận run append-only và writer lock hiện có; không giữ lock suốt lúc chờ model remote.
- Head tiến lên: đọc suffix. Head giảm, file/directory bị thay, identity/binding khác, event sai thứ tự hoặc reducer lỗi: invalid runtime và rebuild/kiểm binding; nếu khác frozen run thì fail closed.
- `seq` chỉ cần tăng nghiêm ngặt; không giả định phải liên tục trừ khi validator hiện hành có yêu cầu đó.
- DB bị thay bằng file khác có cùng head không phát hiện được chỉ bằng `MAX(seq)`. Ghi rõ thay DB tại chỗ khi Engine đang sống không phải operation được hỗ trợ; theo dõi file identity khi có thể, và yêu cầu runtime mới sau restore/replace. Không hash lại toàn DB mỗi lần đọc để xử lý trường hợp này.
- Cache không phải bằng chứng nguồn còn nguyên vẹn. Giữ nguyên `_verify`, `SourceDrift`, manifest binding và kiểm raw hash/offset ở các boundary hiện hành.

## 6. Context reducer và các chỉ mục tăng dần

### 6.1. Context phải khớp replay hiện tại

Reducer event giữ đúng thứ tự:

1. Bắt đầu từ default context hiện tại.
2. Nếu event có `cm_context` truthy: thay context bằng bản tách rời của field đó, không merge với context cũ.
3. Nếu cùng event có `cm_auto_query_view` truthy: overlay sau bước 2.
4. Áp dụng chuẩn hóa `_sync_missing()` tại điểm tương đương `context()` hiện tại. Hàm này cũng có `setdefault`, nên không để một getter đọc làm biến đổi committed context ngoài kiểm soát.

Full `cm_context` vẫn lưu như cũ trong event. Runtime chỉ copy context mới nhất khi có event thay đổi nó; không deep-copy tất cả context cũ. Chuyển sang lưu context delta trên đĩa là một thay đổi schema khác, chưa cần làm.

`prepare(admit=False)` và các lần thử payload không được publish view tự chọn, coverage, stage, pair progress hoặc source gate. Khi admit thật, `cm_auto_query_view` chỉ thành committed state sau event admission. Working context trong manifest và context phục vụ helper phải giữ đúng hành vi hiện tại; helper nào đang cố ý đọc committed context không tự đổi sang working context chỉ để tiện truyền tham số.

Trong `execute_pending`, đường passage lỗi đang dùng `self.context()` để phục hồi context đã commit (`engine.py:2987`). Phải giữ đường rollback này; không trả lại object đã bị `passage_review.execute()` sửa dở. Chỉ feedback lỗi được ghi qua event mới.

### 6.2. Index cần có để không quét/copy lịch sử lặp

| Projection/index | Cập nhật khi nào | Bất biến cần giữ |
| --- | --- | --- |
| Action start/result theo ID, latest outcome/search, successful search theo need | `action_started`, `action_result` | Thứ tự cũ, phân biệt success/duplicate/reuse/error; dùng được cho feedback và tìm need. |
| Request admission/receipt theo ID | `request_admitted`, `request_result` | Không coi admission là evidence đã giao. Giữ unknown/null và attempt thực tế. |
| Query base, candidate order, survey/raw exposure | Search result và receipt `received_response=True` | Dùng admission tương ứng; giữ dedup theo thứ tự, điều kiện ref/text/candidate như hàm cũ. |
| Query priorities/conclusions/completed candidates | Context mới hoặc working context cụ thể | Tách base index theo event khỏi overlay theo context; không cache theo `seq` rồi bỏ qua working context đang sửa. |
| Delivered span theo `(case_id, source_hash)` | Receipt đã nhận | Giữ phạm vi theo ref trong admission; không hợp nhất/xóa duplicates nếu thay kết quả `delivered()` cũ. |
| Need/operation/candidate/lead phục vụ Snapshot | Action và result có need/hits | Giữ conflict check exact need ID, candidate order, latest open_ref, active/invalidation và pending semantics. |
| Used action/exhausted reads/observations phục vụ M6 registry | Action/result liên quan | Chuyển qua hook nhận index cho CM4; không chỉ cache registry cuối theo seq vì nó còn phụ thuộc payload. |
| Opened lead, repair scope đã dùng, latest repair boundary | Event tương ứng | Giữ retry limit qua resume; latest boundary không có retry phải che repair cũ. |
| Usage/summary xuất trace | State hiện tại; có thể memo theo generation | Giữ nguyên unknown/charged/observed; không tính unknown bằng 0. Không nhất thiết viết lại usage reducer trong đợt đầu. |

Ưu tiên chuyển helper nóng sang index trong CM4. Không sửa thẳng toàn bộ `Snapshot.from_events()` của context_manager_v1 chỉ để phục vụ CM4; giữ oracle cũ, tạo adapter tương đương từ runtime cho caller CM4. Nếu vẫn cần materialize một Snapshot lớn, memo theo revision và ghi rõ phần copy còn lại.

Có thể giữ một buffer decoded event dùng chung trong bước chuyển tiếp để giảm I/O ngay, nhưng buffer đó không được deep-copy mỗi lần hoặc tạo list mới cho mỗi helper. Đây chỉ là bước trung gian: các helper quét buffer vẫn O(lịch sử) và giữ nhiều payload/context cũ trong RAM. Chưa chốt tối ưu hoàn chỉnh nếu đường nóng vẫn phụ thuộc full buffer.

RunState hiện vốn giữ requests/receipts/catalog; index có thể tăng theo run. Không hứa RAM O(1). Tránh giữ thêm một bản decoded log đầy đủ cùng nhiều bản deep-copy, theo dõi peak RSS/heap và chỉ giữ field lịch sử cần thiết. Giảm retention của RunState là việc sau nếu cần, không gộp vào thay đổi này khi chưa chứng minh tương đương.

## 7. Giữ nguyên source_revision và prefix hash

`prepare()` hiện dùng `fingerprint(self.events())`; `Snapshot.from_events()` cũng có `bindings.prefix_sha256`. Cache list mà vẫn serialize toàn list mỗi lần hash sẽ giữ một chi phí tăng theo lịch sử. Đổi sang `last_seq` hoặc hash-chain khác sẽ thay contract/provenance.

Có thể giữ **đúng hash hiện tại** mà cập nhật tăng dần, vì `fingerprint(events) = SHA256(encode(events))` và `encode` là JSON canonical compact:

```python
# Minh họa thuật toán; chưa phải implementation.
h = sha256(b"[")
count = 0
for event in newly_committed_events:
    if count:
        h.update(b",")
    h.update(encode(event))
    count += 1

closed = h.copy()
closed.update(b"]")
prefix_sha256 = closed.hexdigest()
```

Hash event có cả `seq`, `kind`, `at_utc` và mọi field đúng như full read, theo thứ tự seq; dùng event round-trip do `Ledger.append` trả về, không hash object trước serialize. Chỉ append byte event mới một lần; hasher chính không nhận dấu `]`. Startup dựng lại hasher từ ledger. Cache invalid thì bỏ hasher cùng projection.

Tại mọi prefix, kể cả rỗng, digest phải bằng `fingerprint(full_events)`. Không thay `source_revision` ở manifest lịch sử, không tự chuyển sang chain hash mới. Hash bằng nhau cũng yêu cầu event RAM không bị consumer sửa qua alias.

## 8. Chia sẻ theo phase trong một lượt

Luồng dự kiến:

```text
startup/resume: full read -> runtime(seq=N)
prepare: sync tail -> read view N + working context
    rows / feedback / registry / catalog / fit dùng chung projection N
    -> manifest -> admission commit -> runtime N+1
controller remote: dùng payload/schema đã admit, giữ nguyên transport
reply: lock + sync tail -> validate đúng manifest -> receipt commit -> runtime mới
execute: lock + sync tail -> working context -> action_started commit
    -> tool/context action -> action_result commit -> runtime mới
guard / trace / inspect: một view mới nhất sau action
```

Một operation có thể commit nhiều event; không hard-code `seq+1` hoặc đúng bốn event mỗi lượt. Sau `action_started`, mọi truy vấn committed history phải nhìn thấy start đó. Read view cũ không được lặng lẽ trỏ vào state đã đổi mà vẫn mang seq cũ: invalidate/assert generation; chỉ giữ bản detached nhỏ cần so sánh sau commit.

`live.run_loop` lấy context một lần cho trace, usage một lần theo boundary, và truyền query summary đã có thay vì gọi `inspect()` để lấy đúng một field. `inspect()` vẫn đầy đủ khi người dùng yêu cầu hoặc kết thúc run, nhưng không đọc lại ledger và không dựng cùng query summary hai lần.

Trong vòng fit, reuse history-derived index; **không reuse schema/catalog hoàn chỉnh khi rows/coverage/byte_limit/page_size/context khác nhau**. Không đổi thứ tự thử fit, soft/hard cap, offered refs hay token counter. Những thứ đó quyết định model nhìn thấy gì.

## 9. Kế hoạch triển khai và nghiệm thu từng bước

### Bước A — chốt oracle và phép đo

Main freeze revision, chọn fixture đủ query/results/passage/identity/error và các prefix thật; ghi baseline theo cùng code hiện hành. Đo số full read, rows/bytes decoded, replay, context copy và hash. Oracle cũ chỉ chạy ở nhánh kiểm; không chạy song song full replay trong mỗi lượt production.

### Bước B — ledger delta và runtime core

Implementer sở hữu `agent_harness/ledger.py`, hook tối thiểu tại `agent_harness/harness.py`, module mới `context_manager_v2/runtime_snapshot.py` và tests core do Main giao. Tái dùng `RunState.apply`; bảo vệ alias; sync tail và hash đúng; kiểm exception trước/sau commit. Default harness ngoài CM4 giữ hành vi hiện tại.

Gate B: mọi prefix có state/context/hash bằng oracle; writer lock, append và unknown recovery không đổi; event apply đúng một lần. Không đi tiếp nếu RAM có thể đi trước DB hoặc cursor qua event chưa apply.

### Bước C — tích hợp Engine và index nóng

Cùng implementer sở hữu `engine.py`, `query_review.py`, `passage_review.py`, adapter Snapshot và hook M6 tối thiểu nếu cần. Thay full replay tại `prepare/reply/execute_pending/stop`; chuyển feedback, review/exposure, lead/need lookup và registry sang projection chung. Không đổi module context_manager_v1 nếu adapter CM4 đủ dùng.

Gate C: payload/schema/handles/aliases/coverage và kết quả action bằng baseline trên fixture có lỗi, duplicate, reuse và fit nhiều vòng. Không còn full read/replay trong đường nóng sau startup; helper còn scan lịch sử phải được liệt kê và xử lý hoặc báo rõ chưa đạt.

### Bước D — live loop, đo lại và bàn giao

Implementer sửa `live.py` để dùng read view theo phase. Tester độc lập sở hữu file test riêng; phải chạy bản cuối sau integration. Với review commit/cache/resume và hash, dùng `tester_advanced` thay tester khi phù hợp, tối đa hai subagent cùng Main theo AGENTS.md.

Bổ sung file mới vào `engine.code_binding()` và chuỗi binding cần thiết. Code thay đổi làm binding khác: dùng namespace mới khi preflight/pilot. Không sửa frozen config trong ledger cũ để ép resume; cùng bản code mới phải tự resume đúng run mới của nó. Prefix lịch sử chỉ dùng read-only/offline oracle hoặc scratch replay có nguồn gốc ghi rõ.

Gate D: qua ma trận ở mục 10, báo before/after và RAM; Main nghiệm thu. Codex chỉ chuẩn bị code/lệnh Modal nếu cần pilot, người dùng/AG thực hiện inference/deploy theo phân công hiện tại.

Không giao hai agent sửa cùng file. Tester viết ca độc lập trước được, nhưng kết luận chỉ sau khi chạy trên implementation cuối. Bàn giao phải ghi file thay đổi, lệnh thực chạy, lỗi/retry và giới hạn bằng chứng.

## 10. Ma trận kiểm thử và tiêu chí đạt

### 10.1. Đúng trạng thái và không đổi dữ liệu model nhận

| Nhóm | Tình huống bắt buộc | Tiêu chí |
| --- | --- | --- |
| Prefix parity | Mọi prefix fixture; prefix thật đầu/giữa/cuối; mọi loại event trong ledger | State field quan trọng, usage, context, query view, index và exact prefix hash bằng full replay. Không chỉ so `state.snapshot()` vì thiếu state nội bộ. |
| Context overlay | `cm_context`, `cm_auto_query_view`, cùng event có cả hai, missing reason, pair switch | Replacement/overlay/defaults đúng thứ tự, không rò progress của pair khác. |
| Preview và fit | Gọi `prepare(admit=False)` nhiều lần; unfit; auto survey; fit giảm bytes/page size | Ledger và committed state/context/hash không đổi; payload lặp cùng đầu vào giống nhau; coverage không tăng. |
| Commit boundary | Fault trước INSERT, rollback; sau commit trước apply/index; sau update trước trace; trace lỗi | RAM không đi trước DB; rebuild đúng từ durable events; không double apply/append. |
| Mutable alias | Sửa sâu kết quả `context/inspect/events`, sửa working context rồi ném lỗi, sửa row xuất ngoài | Committed state/event không đổi; passage error phục hồi đúng context đã commit. |
| Exposure | Admission chưa receipt; received=False; received=True; malformed nhận được; STOP trước gửi | Theo đúng điều kiện `received_response` và source refs hiện hành; không tự đồng nhất success với đã giao, hoặc admission với đã đọc/xét. |
| Resume | Dừng sau admission, receipt, action_started, action_result, terminal | Giữ in-flight unknown, pending action, recovery/repair allowance và retry count; không gửi lại request/tool không rõ kết quả. |
| LoopGuard resume | Cùng chuỗi event ở hai chế độ chạy liên tục và restart, gồm repair boundary và auto-query admission | So bản mới với baseline trong từng chế độ: `no_progress`, cycles, seen, warning/stop/reason phải bằng. Không ép liên tục và resume bằng nhau nếu baseline vốn khác; không thay semantics quan sát context. |
| Hai Engine | Engine A nhả lock, B append, A lấy lock lại; direct append ở scratch fixture | A thấy suffix trước quyết định tiếp theo; không replay từ đầu; cùng event apply đúng một lần. |
| Invalidation | Head lùi, binding drift, DB thay, event không hợp lệ, cache hỏng | Bỏ cache và kiểm lại; mismatch frozen identity phải chặn, không tự tiếp tục bằng state cũ. |
| Query và B | Survey, reused/duplicate/no-hit, passage đọc nhóm, identity pending/final, partial/complete | Candidate order, phase, refs, conclusion, selection và unresolved giữ nguyên. |
| Source drift | Cache đã ấm rồi raw nguồn đổi | Validator vẫn phát hiện; cache không bỏ kiểm hash/offset. |
| Hash | Empty list, nhiều prefix, Unicode, escaped text, null, nested context, event có seq | Exact digest bằng `fingerprint(full_events)`; không dùng chain hash thay thế. |

Payload differential phải so canonical wire bytes, input token count, schema, dispatch handles, aliases, offered spans, feedback và action validation với cùng event/action. Manifest được phép khác các **binding code mới được khai báo**; mọi field khác, đặc biệt source revision/hash/offset, phải giống hoặc được giải thích và không tự bỏ qua. Fixture side-by-side cần cố định clock/identity nếu tự sinh event mới, tránh coi timestamp khác là lỗi cache hoặc bỏ qua toàn bộ hash.

### 10.2. Hiệu năng

Đo hai lớp riêng:

1. Replay reducer/index trên chính 716 event đã lưu, so kết quả tại prefix; đây là kiểm state và chi phí cập nhật, không phải benchmark compile đầy đủ.
2. Compile offline ở các prefix cùng mode/rows/context bằng baseline và bản mới, cùng tokenizer/source assets, cấm mọi controller/embedding/rerank network. Bao gồm query leaf, results, passage/identity và trường hợp fit nhiều vòng. Nếu binding hoặc assets không đủ để replay lịch sử, báo blocker của phép đo này, dùng fixture có cùng tải và không gọi đó là live validation.

Mỗi prefix chạy một lượt warm-up riêng và ít nhất 5 lượt đo, baseline/new chạy xen kẽ; báo p50, p95, min/max, số fit/tokenizer và peak RSS. Mở rộng lên 20+ lượt nếu muốn p95 có sức nặng; không coi p95 của 5 mẫu là thống kê ổn định. Đo startup/resume riêng để cache không che chi phí cold start.

Các gate đề xuất:

- **Bắt buộc:** steady state cùng process có 0 full read và 0 full replay sau bootstrap; không có decoded-history deep-copy cho mỗi helper/fit. API audit được phép full read, nhưng không được gọi từ đường nóng.
- **Bắt buộc:** mỗi event commit được decode/apply vào runtime tối đa một lần ở mỗi vòng đời runtime; sync tail chỉ lấy event chưa biết. Cold rebuild sau invalidation được tính và báo riêng.
- **Bắt buộc:** số hàng/byte được decode trong bootstrap + các tail bằng dữ liệu thực mới, không nhân với số lần getter. Không phải đạt số lượng SQL query bằng 0: head probe nhỏ vẫn được phép.
- **Mục tiêu cần đo:** giảm ít nhất 90% tổng thời gian đọc/giải mã lịch sử trong replay tương đương; giảm ít nhất 50% p50 compile ở nhóm prefix muộn có ledger là nút thắt. Đây là ngưỡng nghiệm thu đề xuất, chưa phải kết quả đã đạt.
- **Giới hạn:** không yêu cầu compile phẳng tuyệt đối theo độ dài run vì current context/catalog/candidate pool có thể lớn dần. So chi phí theo cùng workload; nếu còn slope từ quét lịch sử thì chưa đạt mục tiêu kiến trúc.
- **RAM:** báo base/peak RSS và kích thước các cấu trúc chính; không giữ hai bản full decoded history lâu dài. Nếu giảm I/O nhưng RAM/copy tăng mạnh, phải chỉnh thiết kế hoặc nêu phần chưa đạt trước pilot dài.

Tận dụng `runtime_timing.py` hiện có, thêm counter/part cho `ledger_full_read`, `ledger_tail_read`, `ledger_rows_decoded`, `runtime_apply`, `runtime_rebuild`, `context_working_copy`, `history_index_lookup`, `prefix_hash_update`. Cần counter xác định được ngoài wall time để bắt regression đọc lại lịch sử. Không cộng inclusive của catalog với ledger con; báo exclusive và tổng phase riêng.

Kết quả phải báo cả các lượt compile lỗi, thử fit thất bại, STOP/resume và cache rebuild. Request/token/latency provider giữ nguyên actual/unknown; offline báo 0 provider calls. Không suy ra token tiết kiệm từ số phút host giảm.

### 10.3. Kiểm local liên quan

Lệnh sau là bộ kiểm dự kiến khi có implementation, **chưa được chạy trong đợt viết đề xuất**:

```powershell
.venv/Scripts/python.exe -m unittest pipeline_v2.experiments.context_manager_v2.tests.test_runtime_snapshot
.venv/Scripts/python.exe -m unittest pipeline_v2.experiments.context_manager_v2.tests.test_engine pipeline_v2.experiments.context_manager_v2.tests.test_live pipeline_v2.experiments.context_manager_v2.tests.test_feedback pipeline_v2.experiments.context_manager_v2.tests.test_tool_repair
.venv/Scripts/python.exe -m unittest pipeline_v2.experiments.context_manager_v2.tests.test_survey_auto_navigation pipeline_v2.experiments.context_manager_v2.tests.test_query_review_acceptance pipeline_v2.experiments.context_manager_v2.tests.test_passage_review pipeline_v2.experiments.context_manager_v2.tests.test_search_reuse pipeline_v2.experiments.context_manager_v2.tests.test_offline_terminal
.venv/Scripts/python.exe -m unittest pipeline_v2.tests.test_runtime_timing
```

`test_runtime_snapshot` là module mới dự kiến. Bổ sung test ledger/harness/M6 trực tiếp bị ảnh hưởng khi sửa hook; chọn đúng module thật trong checkout lúc triển khai. Không dùng các test đơn lẻ trên một fixture để tuyên bố đã nghiệm thu toàn integration.

## 11. So sánh phương án và ranh giới hoàn thành

| Phương án | Lợi ích | Phần còn thiếu / quyết định |
| --- | --- | --- |
| Chỉ truyền một list events chung trong `prepare` | Dễ làm, giảm đọc trong compile | Guard/reply/action vẫn đọc; nhiều helper còn replay/copy. Chỉ là bước nhỏ tạm thời. |
| Cache full decoded events theo head | Cắt phần lớn I/O và JSON lặp | Scan, deep-copy, hash cả history và RAM vẫn tăng; cần tiếp tục projection/index. |
| Runtime state/context/index tăng dần + view theo phase | Loại đọc/giải mã/replay lặp, giữ durable contract và model view | Chọn phương án này; phải chứng minh commit/alias/parity. |
| Persist snapshot/checkpoint ra đĩa | Có thể giảm startup/resume dài | Thêm version, integrity, atomicity và reconcile; để sau nếu startup thực sự thành nút thắt. |
| Đổi event sang context delta hoặc chuyển framework | Có thể giảm lưu trữ hoặc thay orchestration | Scope rộng, đổi schema/ownership; không cần cho nút thắt hiện đã đo. |

Chốt implementation khi correctness/differential đạt, đường nóng không full replay, có before/after và RAM trên workload phù hợp. Nếu chỉ xong cache decoded log thì ghi nhận đúng mức đó; không gọi là hoàn tất incremental state/context. Nếu local đạt nhưng chưa pilot, báo **đã kiểm offline, chưa xác minh live**. Dùng cờ fallback chỉ ở code mới nếu cần so baseline, không sửa hay ghi đè run lịch sử.

## 12. Những gì đã kiểm trong đợt đề xuất này

- Kiểm repo root, HEAD và trạng thái Git; checkout có artifact untracked sẵn, không đưa chúng vào phạm vi thay đổi.
- Đọc handoff, progress, ledger/harness, Engine/live, query/passage review, Snapshot cũ và M6 registry; đối chiếu các đường ghi kế thừa và wrapper action.
- Đọc result/trace, tổng hợp lại timing và mở ledger pilot read-only: số liệu mục 2 khớp yêu cầu, xác định rõ cửa sổ 20 lượt.
- Có review độc lập read-only bằng `tester_advanced` về alias, rollback context, commit/hook, hash và resume. Probe local xác nhận alias trong `RunState.snapshot()` và hash JSON-list tăng dần trên dữ liệu nhỏ; chưa phải test một implementation cache.
- Chưa thay production code, chưa chạy suite triển khai, chưa đo speedup và chưa gọi inference/deploy.

## 13. Ưu tiên 2 — giảm dựng thử payload khi chọn span vừa context

Trạng thái: **đề xuất, chưa triển khai**, bổ sung ngày 23/11/2026. Phụ thuộc runtime/read view của ưu tiên 1 để lấy dữ liệu lịch sử mà không mở/replay ledger trong mỗi phương án thử.

### 13.1. Chi phí đã xác nhận và phần chưa đo

Đối chiếu lại cùng `result.json`/`trace.jsonl` ở mục 2:

| Số đo trong `compile_context` | Kết quả | Giới hạn diễn giải |
| --- | ---: | --- |
| Lần compile | 179 | Số mẫu profile. |
| `leaf_payload_projection.calls` | 1.250 | Trung bình 6,983 lần/compile; trung vị 4; tối đa 20. Đếm từ breakdown từng compile. |
| `catalog_and_schema.calls` | 1.324 | Gồm các nhánh dựng payload khác; không tự đồng nhất mỗi lần với một span khác nhau. |
| `tokenizer.calls` | 1.324 | Không suy ra mỗi leaf projection luôn có đúng một lần đếm; fallback có thể pack lại. |
| Catalog/schema exclusive | 362,095 giây | Đã loại các phép đo con như ledger; vẫn gồm công việc chưa instrument nhỏ hơn. |
| `open_query_leaf` exclusive | 165,223 giây | Có 1.250 lần; là chi phí mở/dựng record, không chỉ tokenize. |
| Tokenizer exclusive | 40,066 giây | Đây không phải phần lớn nhất trong số đo run này. |
| `project_wire_payload` exclusive | 5,429 giây | Chỉ khâu compact/alias; khác decorator leaf projection bao cả chuỗi dựng. |

Không cộng `leaf_payload_projection.elapsed_ms` inclusive vào tổng compile: phép đo này có thể lồng qua catalog → thử span → leaf projection và đã chứa ledger/tokenizer. Trace ghi tổng inclusive khoảng 3.800,445 giây, lớn hơn tổng compile 3.168,906 giây; cộng trực tiếp sẽ tính trùng. `TimingProfile.summary()` báo p50 của **tổng exclusive theo compile**, không phải p50 thời gian mỗi lần projection.

1.250 là số lần gọi, **chưa có số distinct span/cache key** để kết luận cả 1.071 lần vượt 179 đều dư thừa hoặc chắc chắn bỏ được. Trace cũ cũng chưa tách caller `catalog_span_probe`, `auto_navigation`, `actual_read` và `fallback`. Đây là baseline lịch sử, không phải phép đo mới chứng minh code auto-navigation hiện hành vẫn có đúng 1.250 lần.

Nhận định được code hiện tại hỗ trợ: auto-navigation bớt lượt model chọn vùng, nhưng vẫn có đường thử nhiều full projection. Cache ledger của ưu tiên 1 sẽ giảm thời gian mỗi projection; bản thân số lần dựng catalog/schema/raw/tokenizer cần xử lý ở ưu tiên 2. Đo riêng hai hiệu ứng để không báo tiết kiệm hai lần.

### 13.2. Khác gì với code hiện tại

| Khâu hiện tại | Việc đang làm | Thay đổi đề xuất |
| --- | --- | --- |
| `_gate_catalog`, khoảng `engine.py:1865–1874` | Mỗi `adjacent_spans` dựng `_combined_query_record`, tạo context `query_span` có `_checking_query_span=True`, gọi toàn bộ `_query_leaf_payload`, giữ các target vừa cap. | Enumerate target một lần theo input hiện tại; dedup đúng khóa; dùng common frame và cache probe; chỉ dựng phần span/schema động còn thiếu. |
| `_query_leaf_payload`, `engine.py:2304` | Mở/verify nguồn, feedback/history, visible paragraphs, dispatch, catalog/schema, compact/alias, serialize và tokenize cho từng phương án. | Tách source record, common facts, span overlay và pack/count; không gọi lại pipeline chung từ đầu cho mỗi span. |
| `_next_survey_read`, `engine.py:2378` | Tại `next_byte`, đi từ root xuống vùng con, thử full projection của từng vùng đủ điều kiện cho tới first fit; leaf quá lớn có thể split tiếp. | Chọn đúng nhánh nguồn trước, tái dùng record/fit result, chỉ render exact những phương án chưa biết; giữ thứ tự first-fitting hiện hành. |
| `prepare`, `engine.py:2449+` | Đã nhận tuple `best` trả về từ auto-navigation và tái dùng khi vừa. | Giữ lợi ích đã có này. Không mô tả sai rằng vùng được auto chọn luôn bị dựng lại lần cuối. Cache bổ sung nhắm vào các lần probe lặp và common work. |
| `_query_leaf_navigation_payload` và vòng fit khác | Dựng navigation fallback, hoặc thử page size/byte limit; catalog phụ thuộc rows đang thử. | Cùng dùng frame/index và cache có dependency đúng; không reuse catalog/schema cuối giữa các rows khác nhau. |

Hai ngữ cảnh thử cần phân biệt: `fit_probe` trong catalog có `_checking_query_span=True` để không đệ quy liệt kê span; `publish` khi vùng thực sự được cấp có thể có catalog khác. **Một probe fit không phải chứng nhận payload publish sẽ fit.** Luôn đếm exact final publish hoặc dùng exact result của chính publish key.

### 13.3. Dựng phần chung một lần, phần động theo span

Thêm `CompileFrame` và các helper thuần, dự kiến trong module mới `context_manager_v2/payload_planning.py`. Tên này là thiết kế; không thêm dependency hay framework mới.

Luồng dữ liệu:

```text
RuntimeSnapshot/read view tại seq N
    -> CompileFrame: binding, index, common facts, static templates
    -> SpanDescriptor: source identity + span + provenance + projected context
    -> RegionPlan: common facts + span-dependent rows/coverage/catalog delta
    -> project(payload, schema) chung một alias table
    -> encode(wire) -> exact token count -> FitResult
    -> admission dùng chính payload/schema/handles/aliases đã được kiểm
```

Phân chia cụ thể:

- **Chung theo runtime revision:** indexes action/request/query/need, search-completed, candidate/assessment counts và các observation đã xử lý. Lấy từ ưu tiên 1, không gọi `Snapshot.from_events()` ở mỗi phương án.
- **Chung theo compile/context variant:** facts để dựng feedback, status survey/permit/repair, profile/cap, trạng thái ngân sách backend đã chụp tại boundary, schema/tool definitions tĩnh. Context-dependent guidance vẫn tính đúng từng mode/variant, không reuse nguyên `_feedback(context)` chỉ vì cùng seq.
- **Chung theo nguồn/span:** record raw chuẩn hóa, source/text hash, components/provenance, paragraph intersections, structure projection có thể cache theo source binding và span. Record cache không được xóa bước phát hiện source drift.
- **Động theo vùng:** raw text, current refs, coverage, visible paragraphs, segment/proposition refs, pending/continuation refs, lựa chọn source need, handles và schema enum. Tính từ descriptor cùng frame, giữ thứ tự dữ liệu cũ.
- **Động theo trial policy:** `_checking_query_span`, mode/region, page size/byte limit, warning/repair, nhánh bỏ warning hoặc paragraph table. Dùng variant riêng; không để trial sửa frame hoặc cấu trúc của trial khác.

Schema skeleton chỉ gồm branch definitions bất biến. Các enum/ref, điều kiện có/không có tool, `maxItems` do batch recovery và description phụ thuộc state phải dựng trên bản riêng hoặc delta bất biến. Không cache nguyên catalog rồi sửa chung dict/list qua nhiều phương án.

`model_view.project()` hiện compact payload rồi tạo **một bảng alias dùng chung cho payload và schema** (`model_view.py:157–210`), có xử lý collision bằng kéo dài alias. Có thể cache structure/fragment canonical, nhưng chưa ghép các wire fragment có alias độc lập thành payload cuối. Muốn tối ưu sâu `project()` phải chứng minh tương đương riêng; đợt đầu vẫn project nhất quán trên payload/schema đã lắp hoàn chỉnh.

Việc dựng/copy lại dữ liệu phải tỷ lệ với **current frame/span**, không phải toàn bộ lịch sử. Chỉ thêm cache trước `_query_leaf_payload()` mà mỗi cache miss vẫn dựng lại toàn pipeline là bước trung gian, chưa hoàn tất tách common work.

### 13.4. Khóa cache, chứng nhận fit và invalidation

Chỉ `(state.revision, span)` **chưa đủ**. `context.revision` hiện không đại diện mọi input vào compile; cùng seq còn có working context và cờ probe khác nhau. Đề xuất hai tầng cache:

1. **Source artifact cache:** `(query_id, source_hash, span_bytes, provenance/components binding, source/navigation policy binding)` → normalized record/structure. Hai record cùng text/span nhưng provenance khác không tự gộp.
2. **Compile-session cache:** `(frame_id, context_variant_id, span_identity, purpose, fit_variant, render_options)` → plan/projection/FitResult. Frame ID gắn với generation, context input, profile và mọi external dependency đã chụp; variant ID gán cho descriptor bất biến được intern trong compile, không hash lại cả history cho mỗi lookup.

Dependency của frame/variant phải bao phủ:

- Run identity, runtime generation/head seq; working-context version hoặc fingerprint phần context đọc bởi compiler; need/candidate/stage/mode, source gate, priorities/conclusions, settled/unresolved spans, pair state và source-return focus.
- Region ref hoặc span, source/text hash, paragraph handle, provenance, offered rows/coverage/current refs; source tree/split/byte-cap binding.
- `gate_enabled`, `survey_first`, dual/source-bound mode, adaptive config, page size/byte limit, `_checking_query_span`, `batch_item_limit`, active repair, progress warning và fallback variant.
- Tokenizer/counter/instruction/chat-template/model-view/compiler binding; input cap, output cap và trạng thái ngân sách ảnh hưởng catalog. Ledger seq không theo dõi thay đổi ở embedding/rerank journal hoặc backend riêng.

Khóa nên được tạo tập trung từ input cấu trúc; không rải danh sách tuple thủ công qua nhiều helper. Bản đầu cache projection đầy đủ **trong một compile**, clear khi operation kết thúc hoặc generation/context dependency đổi. Như vậy giảm nguy cơ stale và giới hạn RAM. Reuse qua lượt chỉ cho source artifacts hoặc subprojection có dependency hẹp đã chứng minh; không hứa exact projection sẽ hit qua mọi admission/receipt.

`FitResult` giữ ít nhất: key đầy đủ; purpose/variant; status fit/unfit; exact input tokens; wire body/hash; wire schema; aliases; canonical dispatch/handles; rows/coverage; lý do fallback và source verification provenance. Có thể lưu plan thay full body cho negative result để giới hạn RAM, nhưng không mất token/variant evidence.

Cache cả fit và unfit **đúng key**. Không suy rộng một span unfit sang mọi subspan, một span fit sang vùng khác, hoặc từ cap cũ sang cap mới mà không kiểm dependency. Số token không phụ thuộc cap nếu body không đổi, nhưng cap có thể làm đổi nhánh pack/fallback; phân biệt token-count cache theo body với kết quả planner theo policy.

Cache count exact riêng có thể dùng `(counter_binding, canonical_wire_body_hash)`; chỉ hữu ích khi body đã có, không tự giảm chi phí dựng catalog. Cache response schema/aliases vẫn phải nối đúng với body. Không expose cached mutable dict/list cho caller chỉnh sửa; xuất working copy nhỏ khi cần và assert frame không bị mutate.

Đổi source/file/binding hoặc phát hiện `SourceDrift` thì bỏ source/projection liên quan và giữ hành vi fail closed. Không cho cache hit vượt qua `_verify(rows)` trước admission. Resume bỏ cache compile, dựng lại frame từ ledger; không persist fit certificates trong run cũ ở đợt này.

### 13.5. Chọn vùng trước, exact token sau: giới hạn để giữ hành vi

**Auto-navigation chọn một vùng.** Chọn `next_byte` và nhánh cây nguồn bằng remaining/unresolved spans trước khi dựng payload; không dựng các nhánh chắc chắn không được chọn theo quy tắc nguồn hiện tại. Duyệt các ancestor đủ điều kiện theo cùng thứ tự hiện hành; reuse fit certificate nếu đúng publish key. Đối với candidate chưa có kết quả, lắp phần động từ common frame rồi exact count, gặp first fit thì giữ luôn tuple đó cho admission. Các vùng đã biết kết quả trong cùng compile không dựng/đếm lại.

Có thể tính ước lượng rẻ bằng raw/structure size và static-overhead để phân bổ công việc hoặc gợi ý vùng có khả năng vừa. Nhưng ước lượng không phải exact fit: JSON escaping, boundary tokenizer, template và schema/tool thay đổi có thể làm lệch. Không lấy số byte hoặc tổng token của từng mảnh làm bằng chứng toàn payload vừa.

Nếu ước lượng chọn một descendant trước, muốn giữ **first-fitting ancestor** vẫn phải exact/cached-exact những ancestor đứng trước, hoặc có bound an toàn đã được chứng minh cho tokenizer/rendering cụ thể. Không có bound thì không bỏ candidate vì heuristic. Không dùng binary search với giả định token count đơn điệu theo độ dài span: catalog/enum/fallback có thể đổi khi ranh giới paragraph/segment đổi.

**Catalog cần nhiều lựa chọn.** `_gate_catalog` hiện đưa tất cả target fit từ tập đã enumerate vào `query_span_options`, handles và enum `read_query_span`. Nếu chỉ exact một target rồi bỏ các target khác, menu model nhận sẽ khác. Đợt giữ semantics phải tính exact/cached-exact cho mọi distinct probe key ảnh hưởng menu; giữ nguyên thứ tự, ref và những target bị loại. Mục tiêu là mỗi distinct key dựng phần động/pack/count tối đa một lần, không dựng lại phần chung cho từng target.

Chứng nhận probe chỉ giúp tạo menu như hiện tại; khi model chọn span để đọc, publish vẫn kiểm với context/feedback mới. Không biến fit-probe không warning thành exact publish có warning hoặc ngược lại.

**Final admission:** dùng đúng counter hiện tại: `ModalQwenTransport.count_tokens()` render instruction + payload header/body rồi chat template/special rendering (`modal_qwen.py:169–182`). Không thay bằng raw text tokenizer hay cộng token các fragment. Cả `available_tools` trong payload, schema/alias dispatch và output cap phải đồng bộ; không tự giả định provider response schema là phần được local counter đếm nếu transport contract hiện tại không làm vậy.

Nếu `best` đã là exact publish tuple đúng mọi dependency, dùng lại body/tokens đã kiểm, không pack/tokenize thêm chỉ để gọi đó là final check. Nếu warning, feedback, catalog, source verification hoặc working context đã đổi, certificate hết hiệu lực: dựng/đếm lại variant đúng trước admission. Khi cache hash dùng để tra body, không serialize lại toàn payload chỉ để xác nhận một cache hit đã có input bất biến.

Mục tiêu thực tế là **một exact publish cho vùng đã chọn ở đường bình thường**, cộng những distinct probe cần thiết để giữ menu/first-fit và fallback. Không đặt yêu cầu giả tạo “mỗi compile chỉ được tokenize đúng một lần”. Muốn chỉ offer một vùng, lazy-validate lúc execute, hoặc chọn descendant theo estimate mà bỏ ancestor là thay đổi policy riêng, cần người dùng chốt và đánh giá ảnh hưởng model view; chưa thuộc đề xuất tương đương này.

### 13.6. Pseudocode luồng đích

```python
frame = compile_frame(runtime.read_view(), working_context, profile, backend_snapshot)
memo = CompileMemo(frame.id)  # chỉ sống trong compile

def fit(target, *, purpose, variant):
    descriptor = describe_span(frame, target, purpose, variant)
    key = frame.key_for(descriptor)
    if key in memo:
        return memo[key]  # không mutate result
    plan = overlay_span(frame, source_artifacts(descriptor), descriptor)
    result = exact_pack_and_count(plan, frame.counter)
    memo[key] = result
    return result

# Catalog: tất cả lựa chọn vừa như baseline, không cắt thành một lựa chọn.
for target in ordered_span_targets(frame, current_rows):
    probe = fit(target, purpose="fit_probe", variant="checking_query_span")
    if probe.fits:
        add_original_span_option(target)

# Auto: cùng đường cây và first-fit, dừng ngay khi có exact publish fit.
for target in first_remaining_region_path(frame):
    final = fit(target, purpose="publish", variant=frame.publish_variant)
    if final.fits:
        return final  # chính body/schema/handles/aliases này được admit
```

Đây là hai consumer có thể xuất hiện trong các nhánh compile khác nhau, không buộc mỗi compile chạy cả hai vòng. `exact_pack_and_count` giữ thứ tự fallback hiện tại: full feedback → bỏ progress warning nếu vượt cap → compact paragraph table khi điều kiện hiện tại cho phép. Mỗi variant có key và kết quả riêng; không ghi đè result full bằng compact rồi reuse nhầm.

Trong fit-probe phải giữ `_checking_query_span=True` hoặc equivalent guard để không đệ quy enumerate chính menu đang kiểm. Nếu lookup cùng key đang tính dở, báo cycle/bug trong offline test; không dùng một kết quả “fit” mặc định để phá vòng lặp. Working cache không được biến preview thành event admission hoặc tăng exposure/coverage.

### 13.7. Kiểm thử và đo hiệu quả riêng

Các ca dưới đây bổ sung vào mục 10, chưa chạy trên implementation vì chưa có code mới:

| Ca kiểm | Điều phải chứng minh |
| --- | --- |
| Menu nhiều span | Cùng ordered `query_span_options`, handles, enum và alias như baseline khi 0/1/nhiều span fit; span quá lớn bị loại đúng. |
| First-fit theo cây | Parent fit, parent unfit/child fit, split leaf, unresolved chặn auto-next, vùng chồng previous; chọn đúng region/ref/span và giữ đủ raw bytes. |
| Cache hit/miss | Cùng exact key được hỏi nhiều lần chỉ dựng/pack/count một lần; negative cache cũng đúng; khác purpose hoặc context phải miss. |
| Dependency bị đổi ở cùng seq | Đổi working gate, warning/repair, page size, batch limit, backend remaining, profile/template/alias binding; không dùng kết quả stale. |
| Probe khác publish | Probe với `_checking_query_span` fit nhưng publish menu/feedback lớn hơn; final exact kiểm lại, không admit payload vượt cap. |
| Biên token | Body thực ở cap−1/cap/cap+1 với counter pin; Unicode, JSON escapes, span qua paragraph/quotation/heading. Không dùng fake word count để chứng minh production fit. |
| Fallback | Bỏ warning, bỏ paragraph table, navigation-only và truly-unfit; giữ feedback, dispatch table, offered refs và terminal behavior cũ. |
| Alias/schema | Nhiều refs và collision fixture; wire refs ↔ canonical refs ↔ schema enum ↔ handles khớp toàn payload, không ghép alias độc lập. |
| Mutation/source drift | Trial A không sửa frame/trial B; cache source ấm rồi raw đổi vẫn phát hiện trước admission; cache không giữ provenance của source khác. |
| Preview/resume | Repeated `admit=False` không đổi ledger/coverage; restart clear compile cache và dựng lại cùng model view từ state đúng. |

Dùng oracle cũ so **wire bytes, exact tokens, schema, handles, dispatch, aliases, rows, coverage và region/menu được chọn**, không chỉ so boolean fit. Các test hiện hành liên quan: `test_survey_auto_navigation`, `test_map_first`, `test_source_gate`, `test_source_grounding`, `test_model_view`, `test_tool_repair`, cùng fixture query-span và partial/unfit cần bổ sung. Đề xuất tester sở hữu `tests/test_payload_planning.py` riêng, chạy trên implementation cuối.

Instrument thêm `compile_frame_build`, `span_enumerate`, `span_plan`, `span_fit_probe`, `publish_projection`, `fit_fallback`, cache hit/miss/evict và số distinct key theo purpose. Mỗi compile báo source-open/verify, full catalog build, overlay, project/serialize/tokenizer calls, exact token count, trial context variant và peak memory. Không log full raw payload vào telemetry mới nếu ledger đã giữ nó.

Đo ba cấu hình trên **cùng fixture/prefix/workload và cùng policy**: baseline hiện tại; chỉ runtime ưu tiên 1; runtime + common frame/cache ưu tiên 2. Nếu auto-navigation profile khác baseline lịch sử, lập benchmark riêng cùng profile hiện tại. Không trừ trực tiếp hai run live có số vùng/mode/model action khác nhau rồi quy hết chênh lệch cho cache.

Gate correctness: parity ở bảng trên; không thay source boundaries/model menu hoặc dùng estimate để admit. Gate cấu trúc: một common frame mỗi compile; tối đa một build/count cho mỗi distinct exact key; không mở history trong trial; final publish reuse đúng tuple. Đếm riêng những fallback và target khác thật sự cần kiểm, không coi mọi projection vượt số compile là lỗi.

Mục tiêu hiệu năng đề xuất, chưa đo: trên fixture có cùng key lặp ít nhất 3 lần, giảm ít nhất 2/3 full projection/count cho key đó; trên workload nhiều distinct span, common frame build vẫn bằng 1 và chi phí catalog/history chung không tăng theo số trial. Báo thêm p50/p95 compile, projection calls và RSS trước/sau; chưa đặt một tỷ lệ giảm tổng 1.250→179 vì chưa biết distinct key và số menu probe bắt buộc.

### 13.8. Thứ tự triển khai bổ sung

1. Chốt oracle/counters theo caller và key trước; không suy đoán hit rate từ 1.250 lần gọi.
2. Sau runtime core, tách source record/common frame/span overlay, giữ compiler cũ làm oracle offline. Thêm exact memo theo compile và cache source có integrity guard.
3. Chuyển `_gate_catalog` sang probe có memo, `_next_survey_read` sang planner giữ first-fit; giữ reuse `best` đã có trong `prepare`. Chưa đổi menu hoặc thuật toán chọn vùng vì estimate.
4. Tester độc lập chạy parity, boundary và invalidation; review chuyên sâu nếu thay recursion/catalog/schema/alias. Sau đó đo ba cấu hình, sửa giới hạn RAM nếu cần.

Implementer sở hữu `engine.py` và module `payload_planning.py` mới; nếu cần sửa `model_view.py`, `query_options.py`, `source_gate.py` phải chốt scope cùng Main trước và cập nhật code binding. Các file này giao cùng implementer theo thứ tự, tránh hai agent sửa `engine.py` đồng thời với ưu tiên 1. Tester chỉ sửa test riêng; Main nghiệm thu cuối và cập nhật trạng thái khi đã có evidence mới.

Đợt bổ sung tài liệu này chỉ đọc code/artifact và review độc lập; đã xác nhận các counter lịch sử nêu trên. Chưa triển khai cache/frame/planner, chưa chạy suite mới, chưa có số đo speedup và không gọi provider.

## 14. Ưu tiên 3 — giảm catalog và instructions, giữ đủ hợp đồng suy luận

Trạng thái: **đề xuất chi tiết, chưa triển khai**. Bổ sung ngày 23/11/2026 trên HEAD `0c2da9f`. Khuyến nghị làm snapshot và common frame trước khi tích hợp vào runtime; emitter catalog và ma trận quy tắc có thể chuẩn bị độc lập. Không đổi controller, tokenizer, output cap 1.024, embedding model/cap, chunk, pool, reranker hay top-k.

### 14.1. Bằng chứng từ pipeline hiện tại

Audit local [summary.json](../../../cache/cm4-catalog-audit-0c2da9f-20261123/summary.json), [audit.py](../../../cache/cm4-catalog-audit-0c2da9f-20261123/audit.py) có 17 payload; 0 controller/embedding/reranker requests. Bốn payload A dùng `MapFirstQueryTools` và nguyên văn `021095.txt`. Các pha sau dùng pool hai hit được script, nhưng text/hash/absolute offsets lấy từ nguồn thật `021095.txt`, `070847.txt`, `011064.txt`. Quyết định và điểm xếp hạng đều được script, không phải suy luận pháp lý hoặc retrieval thật.

Đã đối chiếu binding code, prompt, tokenizer và nguồn của các mẫu A đã lưu; đếm lại input bằng counter pin. Đọc mẫu đã lưu để tiếp tục audit không phải chạy lại toàn pipeline. `elapsed_seconds` của invocation cuối có cache reuse, không dùng làm số đo latency pipeline.

| Payload hiện hành | Tổng input | Catalog: delta khi bỏ `available_tools` | Raw text trong `excerpts`, đếm riêng |
| --- | ---: | ---: | ---: |
| A đầu tiên, `[0,929)` | 6.546 | 3.901 | 231 |
| A tiếp theo, `[929,2551)` | 7.621 | 4.511 | 363 |
| Chọn permit | 2.525 | 307 | 181 |
| Danh sách hai B, page size mặc định 5 | 2.071 | 158 | 0; thẻ có preview ngoài `excerpts` |
| Đọc B | 3.969 | 706 | 1.117 |
| Chốt định danh B | 2.860 | 279 | 772 |

Catalog của survey A chiếm khoảng 59–60% input ở hai mẫu này. Riêng descriptor batch trong mẫu đầu có 3.188 token standalone, descriptor đơn có 574 token. `bound_assessment_variants()` sinh tối đa 7 nhánh decision/ref/quote; `_gate_catalog()` đã compact descriptor đơn nhưng còn nhúng các object gần giống nhau vào `assess_source_needs`. Batch đã nhận từ 1 đến 3 item. Không kết luận các pha B đều có catalog lớn hoặc mọi tool đều được gửi trong mọi lượt.

Thử trên **bản sao prompt**, giữ nguyên decoder schema:

| Thử nghiệm dung lượng | A đầu tiên | A tiếp theo |
| --- | ---: | ---: |
| Hiện tại | 6.546 | 7.621 |
| Thay mô tả item batch bằng bộ trường chung, vẫn giữ tool đơn | 3.938 | 4.639 |
| Đồng thời bỏ descriptor tool đơn | 3.364 | 3.992 |

Hai hàng thử chỉ là ablation đo kích thước. Bản merged descriptor trong audit chưa có đủ bảng điều kiện để trở thành implementation đạt yêu cầu. Giữ tool đơn ở bước đầu tương ứng khả năng giảm khoảng 39% trên hai mẫu, không phải mức 48% của phương án bỏ tool đơn. Descriptor hoàn chỉnh có thêm quy tắc nên phải đo lại; chưa suy ra mức giảm toàn run, thời gian inference hay chất lượng model.

Instructions cố định đóng góp delta khoảng 1.259 token/request trong các mẫu. Con số 1.288 của minimal payload còn gồm chat frame và payload tối thiểu, không phải toàn bộ instructions. Không coi 1.259 token là phần có thể xóa hết.

### 14.2. Các điều kiện phải bảo toàn

Ưu tiên bỏ cách diễn đạt lặp; giữ nội dung có thể làm đổi quyết định:

- Nguyên văn, source order, source hash, offsets, paragraph/quotation structure, attribution cues, citation/support roles và các ref đang được cấp. Không thay passage bằng tóm tắt hoặc chỉ giữ citation.
- Phân biệt lời đương sự, nguồn được trích, quyết định cấp dưới và lập luận của tòa đang xét. Giữ điều kiện/ngoại lệ trong proposition; một chủ đề pháp lý rộng chưa đủ là nhu cầu nguồn cụ thể.
- Có đường `need_more_context`, sửa span, quote recovery, defer và giữ pending. Không ép kết luận ngắn hoặc tăng số item mỗi lượt để đạt số request thấp hơn.
- `no_search_needed` chỉ xử lý các byte được chọn; typed supports không tự settle phần text của chúng. Đã cấp/đã nhận raw không đồng nghĩa đã screened, assessed hoặc chốt.
- A phải viện dẫn/dựa vào chính B; quan hệ ngược hoặc cùng trích án C không đủ. Ref tự định danh B khác ref quy tắc trong thân B. Các mâu thuẫn về quyết định thực phải còn đường model xem xét.
- Khóa conclude một lần theo query–B, identity-only trước select, và phân biệt pending/partial/complete. Không bỏ lượt định danh bằng cách nhét thêm cờ select vào action khác.
- Giữ nguyên trường output, enums, bounds, host semantic validation và source validation. Metadata host có thể compact như hiện có, nhưng không cắt căn cứ model cần chỉ vì host đã giữ một bản đầy đủ.

Không thể chứng minh chất lượng suy luận bằng việc output vẫn qua JSON schema. Model có thể chọn span sai hoặc bỏ sót nhu cầu dù schema/ref đều hợp lệ; gate mục 17 phải theo dõi riêng.

### 14.3. Descriptor batch dùng một bộ trường và bảng điều kiện

Tách ba thành phần nhưng sinh từ cùng contract hiện hành:

1. **Hợp đồng canonical tại host:** action, fields, điều kiện từng decision, source-choice sets và validation như hiện tại.
2. **Decoder schema:** giữ đủ các nhánh mutually exclusive, enums/ref và giới hạn chính xác. Bước đầu không đổi schema được truyền cho worker.
3. **Descriptor model đọc:** mô tả item một lần, kèm bảng ngắn các điều kiện thay vì lặp lại 7 object JSON. Đây là hướng dẫn về cùng API, không phải định nghĩa một loại output mới.

Đề xuất module `catalog_descriptor.py` làm emitter thuần từ contract và refs đã biết. Dùng tên argument hiện hành; không đổi sang ký hiệu khó nhớ, tuple vị trí hoặc mã enum một chữ. Không chỉ lấy union fields rồi bỏ điều kiện. Chỉ dedup các field/spec thực sự giống nhau; khác enum theo nhánh thì phải thể hiện scope tương ứng.

Descriptor của một item phải nói rõ ít nhất:

| Quyết định | Cách chọn nguồn | Quy tắc không được lược |
| --- | --- | --- |
| `search_needed` | Chính xác một `proposition_ref` hợp lệ hoặc `proposition_quote` literal | Không chọn cả hai; không dùng ref chỉ dành cho kết luận âm; proposition cần đủ ý. `sufficient_for_search` giữ ý nghĩa/fallback hiện hành. |
| `no_search_needed` | Chính xác một ref hoặc literal quote của vùng đã đánh giá | `remaining_visible`/negative-only chỉ áp các ranges được cấp; không bao phủ phần chưa đọc; `context_complete` phải thỏa validator hiện hành. |
| `need_more_context` | Ref, quote hoặc không selector theo các nhánh đang được offer | Không gửi cả ref và quote. Giữ `missing_context`, cách mở thêm và phần việc unresolved; không tự biến thành kết luận âm. |

Common fields vẫn mô tả đủ name/type, attribution/reason enums, `reason` và bounds, `context_complete`, optional `signal_ref`, `sufficient_for_search`, `missing_context`, `a_supports` có role và span ref. Enum có khác theo packet phải lấy từ packet đó. Ref selectable cho search và ref chỉ dành cho negative không được hợp nhất thành một tập “dùng tùy ý”.

Batch ghi rõ `args.items` là array từ 1 đến `batch_item_limit` item theo contract này, mỗi item độc lập, không tự lặp đánh giá cùng span hoặc tạo kết luận xung đột trên span chồng lấn. Giá trị max phải theo recovery hiện tại 3 → 2 → 1, không hardcode 3 trong descriptor khi schema đã hạ xuống 2/1. Tool đơn vẫn có tên và cách gọi hiện hành, tham chiếu cùng mô tả item bằng ngôn ngữ rõ ràng. Không lặp lại toàn bộ field table hai lần; nếu thêm shared item description trong payload, đó là metadata mô tả, không phải key được yêu cầu trong reply.

Ưu tiên cấu trúc dễ đọc: một field table cùng bảng decision/selector, batch nói rõ dùng lại item fields. Không cần phát minh DSL, dùng `$ref` chưa được giải thích hoặc đưa schema dạng nén vào prompt. Có thể giữ các enum ngắn inline; các ref list dài chỉ đổi sang `choices_from` khi đường dẫn **wire sau alias** rõ ràng và mọi ref cần thiết vẫn xuất hiện trong packet. Bước đầu chưa cần tối ưu ref list ngoài việc loại lặp trong 7 nhánh.

Đoạn ví dụ trong descriptor phải được sinh từ refs/schema thực của packet và qua validator. Chỉ thêm ví dụ cho ref/quote/need-more-context nếu bảng quy tắc chưa đủ; tính cả token ví dụ vào mục tiêu tiết kiệm. Không đưa một câu án tự viết vào làm minh họa pháp lý; ví dụ API chỉ được giải thích là mẫu hình thức.

Mọi thay đổi nằm ở descriptor phải dùng object tách rời. Không mutate decoder schema hoặc shared template khi compact. Các nhánh `quote_recovery` bị ẩn, tool eligibility, source choices và batch recovery phải đồng bộ với descriptor.

### 14.4. Giữ tool đơn trước, thử batch-only sau

Phương án khuyến nghị đầu tiên: descriptor batch gọn, vẫn offer `assess_source_need` và `assess_source_needs`. Model không phải học ngay rằng đánh giá một mục đã chuyển API. Chưa có bằng chứng bỏ tool đơn không ảnh hưởng tỷ lệ chọn đúng action, output length hoặc khả năng sửa lỗi.

Sau khi bản này được kiểm, có thể thí nghiệm batch-only vì array một item biểu đạt cùng quyết định. Đây là thay đổi action surface riêng: descriptor, decoder offered actions, repair messages và schema choices phải khớp; host có thể giữ parser legacy để đọc lịch sử, không âm thầm chấp nhận action không được offer ở request mới. Test recovery giới hạn 1 phải vẫn có một đường hợp lệ. Không gộp kết quả thí nghiệm batch-only với kết quả của compact descriptor.

### 14.5. So sánh các lựa chọn thu gọn

| Lựa chọn | Lợi ích | Rủi ro và quyết định đề xuất |
| --- | --- | --- |
| Chỉ cache catalog/schema tại host | Bớt dựng lặp, model thấy nguyên prompt | Thuộc mục 13; không giảm input thực gửi. Làm trước, không gọi đó là prompt compaction. |
| Gom field/conditional guidance, giữ decoder và cả hai API | Giảm phần lặp lớn nhất ở survey; giữ đường gọi đơn quen thuộc | Chọn B1. Cần kiểm descriptor diễn đạt đủ mọi branch và thử model sau local; dung lượng audit chỉ là bằng chứng tiềm năng. |
| Xóa tool đơn ngay | Giảm thêm vài trăm token ở các mẫu | Đổi action surface và repair behavior cùng lúc; để E riêng, chưa là mặc định. |
| Bỏ toàn bộ schema/mô tả, chỉ còn tên tool | Payload ngắn nhất | Model thiếu tên trường, scope refs và điều kiện quyết định; decoder PASS không khôi phục chất lượng suy luận. Không chọn. |
| Mã hóa field/enum thành ký hiệu ngắn hoặc yêu cầu giải nén | Có thể giảm token bề ngoài | Thêm gánh giải mã và nhầm mapping; refs đã có alias hiện hành. Không chọn ở đợt đầu. |
| Tóm tắt/cắt raw hoặc bỏ counterevidence | Giảm nhiều token nguồn | Thay căn cứ đánh giá, vi phạm mục tiêu giữ nghĩa; không dùng để đạt KPI input. |
| Tăng raw ngay khi prompt nhỏ hơn | Có thể giảm số lượt đọc | Đổi packet/độ khó trong cùng thí nghiệm; để policy E sau, đo omission và output cap riêng. |

## 15. Instructions theo pha và packet nguồn ổn định

### 15.1. Common core và hướng dẫn đúng việc đang làm

Hiện `live.runtime()` chọn một `SURVEY_FIRST_INSTRUCTIONS` cho cả session. Thay bằng bộ profile hữu hạn, được host chọn từ working context và canonical offered actions; model không tự chọn profile. Tên dưới đây là tên thiết kế:

| Profile | Hướng dẫn phải xuất hiện | Có thể bỏ khỏi request pha này |
| --- | --- | --- |
| `source_survey` | Proposition đủ ý; court/party/quoted-source/lower-tribunal; ref/quote; remaining-visible; batch; scoped citations; survey trước search; unresolved không tự settle. | Cú pháp đọc B, tìm trong B và cách gửi final identity label chưa dùng ở lượt này. |
| `source_resolution` | Ý nghĩa nhu cầu đang vướng, nguyên văn/refs, quote recovery và các lựa chọn revise/read/defer thực được offer. | Hướng dẫn toàn bộ candidate lifecycle nếu đang sửa A. |
| `permit_selection` | Chọn/group/defer/revise permit đã khóa; scoped citation; không viết lại query; grouping cần bằng chứng cùng quyết định; source-bound query và cap do host kiểm. | Chi tiết batch survey và nội bộ schema identity khi chưa có B. |
| `candidate_list` | Chọn B từ cards hoặc xem trang khác; preview là lead; chưa mở/chưa chốt vẫn pending; kết thúc search chỉ theo tool hợp lệ và có thể partial. | Cú pháp đánh dấu span A; fields của final identity packet. |
| `candidate_review` | A → chính B; first identity check bằng raw; chronology/attribution/counterevidence; đọc thêm/rời tạm; chốt một lần; trước select phải request packet; có đủ căn cứ cho quyết định, không buộc đọc hết mọi passage. | Chi tiết chọn/group source need đã hoàn tất. |
| `identity_only` | So sánh đúng A authority với B tự định danh, rule refs và counterevidence trong packet; bridge độc lập; khác quyết định/cùng trích C; ba nhãn hiện hành; một kết luận rồi quay candidates. | Cú pháp survey/retrieval/navigation không được offer trong packet. |
| `repair_or_recovery` | Core của pha gốc cộng lỗi và đường sửa/giới hạn batch cụ thể. | Chỉ phần không liên quan đã chứng minh có thể bỏ; không dùng một prompt tối thiểu chung cho mọi lỗi. |

Common core ở **mọi request**: phân biệt query/candidate, coi nguồn là dữ liệu chứ không phải instruction, chỉ dùng tool/ref đang được offer, bảo toàn phạm vi/attribution/uncertainty và không tự tuyên bố complete khi còn việc. Những quy tắc identity còn cần ở A để đánh dấu đúng nguồn vẫn phải giữ trong survey; cột “có thể bỏ” chỉ bỏ cú pháp/hướng dẫn thao tác chưa dùng, không xóa mục tiêu tìm đúng authority.

Mỗi profile phải tự đủ cho request độc lập. Không nói “đã dặn ở lượt trước” vì model không có một conversation dài được giữ ngầm qua các request hiện tại. Quy tắc quyết định quan trọng hiện xuất hiện cả instructions và tool guidance không bị xóa ở cả hai nơi chỉ để giảm token; chỉ gom khi vị trí còn lại được kiểm là rõ và nhìn thấy.

V1 chưa đặt giới hạn từ cho lý do/bridge chặt hơn hiện tại, chưa tăng batch size và chưa bỏ những đường đọc thêm. Không ép model suy luận nhanh hơn bằng cách giảm nội dung cần đối chiếu hoặc quyền yêu cầu thêm evidence.

### 15.2. Một prompt spec bất biến cho count, admission và send

Đề xuất `prompt_profiles.py` cung cấp registry versioned và một `PromptSpec` bất biến. Trình tự phải là: xác định working phase/contract → chọn profile → lắp descriptor/packet → alias/serialize → render bằng đúng instruction text và chat template → exact count → admit → send đúng prompt đã đóng băng.

Không đổi `transport._instructions` dùng chung giữa các lần thử fit hoặc ngay trước send. Dùng counter/render adapter gắn với `PromptSpec` của compile. Counter được truyền vào navigation/map và counter trước admission phải thuộc policy được khai báo; không có chỗ ngầm dùng full instructions trong khi chỗ khác dùng phase instructions. Nếu fallback làm thay đổi phase thực sự, tạo spec/frame mới rồi compile lại; không dùng fit certificate của profile cũ.

Run identity bind toàn registry/template versions, descriptor policy, evidence-planning policy, navigation policy, tokenizer/chat template và renderer. Không dùng global prompt fingerprint thay đổi theo pha để lách `_start()` frozen-config check. Mỗi admission/manifest lưu ít nhất:

- Profile ID, version và instruction hash; instruction literal phải khôi phục được từ registry đã freeze trong plan/run config, không chỉ có một hash trỏ vào code có thể đổi sau này.
- Canonical payload/body hash, rendered prompt hash, response schema/hash, aliases/dispatch binding và exact input count, output cap.
- Evidence-plan fingerprint, source refs/hashes/offsets và context revision dùng để compile.

Receipt nối cùng request/admission đó. Resume dùng spec của admission cũ để quan sát/reconcile request đang pending; không chọn lại phase theo state mới rồi gửi lại. STOP trước send, unknown admission, repair và length recovery giữ accounting hiện hành. Request mới sau recovery có spec/hash riêng và maxItems đã hạ. Không giả mạo receipt hoặc coi chưa gửi/unknown là đã tiết kiệm.

Đường worker hiện nhận `generate(prompt, schema, max_tokens)`; thay profile host không tự đòi đổi model hay deployment. Tuy nhiên mọi thay đổi binding vẫn dùng namespace mới, và kiểm deployment/API thực tế trước pilot theo phân công người dùng/AG. Không tự deploy hoặc inference từ kế hoạch này.

Cache ở mục 13 bổ sung `PromptSpec/registry/descriptor/evidence-policy fingerprint` vào key. Hai request cùng state seq nhưng khác profile không được reuse body/count. Exact count so với prompt thực gửi phải khớp; không thay bằng token count từng mảnh cộng lại. Schema truyền riêng cho decoder không được cộng như thể nó nằm trong prompt; phần schema viết lại trong `available_tools` thì có.

### 15.3. Không dùng token vừa tiết kiệm để tự thay evidence packet

Prompt nhỏ hơn có thể khiến một ancestor lớn hơn trở thành first fit, dù code chọn cây không đổi. Nó cũng có thể làm giữ được nhiều cards/đoạn B hơn trong một lần. Vì vậy chỉ “không sửa chunk/first-fit” chưa đủ để đảm bảo model nhận cùng căn cứ.

Đợt so sánh descriptor/instructions đầu phải khóa cùng `RegionPlan`: ordered rows, source spans/hash, quotation/attribution structure, supports, coverage, current refs, page/byte limit và ordered eligible actions như baseline. Phần tiết kiệm tạo headroom, chưa tự mở rộng raw hoặc thay menu. Giữ original offsets và source order; không bỏ phản chứng để packet nhỏ hơn.

Offline paired-packet audit có thể dùng ngay plan/manifest đã freeze. Với integrated pilot giữ evidence-planning policy baseline riêng khỏi admission-render policy: planner vẫn chọn packet theo counter/policy baseline đã bind; bản compact chỉ render/count/admit packet đó. Nếu cần tái render baseline để giữ lựa chọn thì đo cả overhead này; chưa được gọi đó là host optimization đã hoàn tất. Có thể dùng frame/cache mục 13 để tránh dựng lại phần chung, nhưng không dùng một ước lượng rẻ làm oracle lựa chọn.

Sau khi B/C có evidence chất lượng, việc dùng headroom để đọc vùng lớn hơn là một thí nghiệm riêng: giữ paragraph/citation/quotation boundaries phù hợp, giữ đường đọc thêm và đo omission, attribution, số quyết định mỗi lượt, output truncation và chất lượng toàn run. Không lẫn mức giảm token do descriptor với mức tăng raw do policy mới.

## 16. Tự chuyển trang chỉ khi không còn quyết định cần model

### 16.1. Cái đã có và phần đề xuất thêm

Current HEAD đã auto cấp vùng A đầu/tiếp theo khi đủ điều kiện; gom passage cùng B; auto quay về candidates sau conclude B trong survey-first. Probe A có chuỗi chỉ gồm các action đánh giá, không có open/page chen giữa hai vùng đã settled. Do đó 107/178 action điều hướng lịch sử không phải baseline tần suất hiện hành, cũng không phải số action có thể cắt hết.

Phần mới giới hạn ở bước phân trang B bắt buộc. Audit `page_size=1` tái hiện sau chốt B payload 1.822 token chỉ còn `show_context_page`; thêm một model call chỉ để chọn trang kế tiếp. Đây là edge case có chủ đích, không đại diện page size mặc định 5 hoặc phân bố top 10 thật. Cần fixture mặc định với đủ B/trang trước khi nghiệm thu integration.

### 16.2. Điều kiện auto và những việc vẫn để model

Chỉ auto khi đồng thời đúng:

1. Đang ở danh sách của cùng active search query, không có B đang đọc, identity packet chưa chốt, anchor draft, repair/recovery hoặc action/request chưa giải quyết.
2. Mọi B ở trang hiện tại đã có kết luận cuối hợp lệ. Không coi default not_select, đã xem card, rời tạm hoặc pending là đã xong.
3. Catalog/action-space sau khi áp điều kiện hiện hành không có lựa chọn khác cần phán đoán, và chỉ có **một page target hợp lệ**. `next_unseen_page` là hint không đủ để auto khi còn B cần mở hoặc còn nhiều page target khác nhau.
4. Target tiến tới cards chưa giao trong cùng query; source/pool/query/page bindings hợp lệ, không đổi order/rank policy và không vượt giới hạn context.
5. Không có STOP, terminal hoặc guard đang yêu cầu dừng; không tạo vòng chuyển trang vô hạn.

Nếu các điều kiện không đạt, giữ tool/model decision như hiện hành. Đặc biệt vẫn để model chọn B, lượng đọc, sửa nguồn, group needs, defer hoặc kết thúc search partial. Không tự drain toàn hàng chờ tìm kiếm, không auto-not-select B chưa mở, không tự complete sau khi hết trang. Giữ identity-only turn theo contract hiện hành.

V1 chỉ chuyển một bước trước một admission thực. Theo dõi visited bằng khóa ổn định `(query_id, immutable_pool_fingerprint, page_offset)`; revision trước/sau lưu riêng để audit, không đưa revision tăng dần vào khóa phát hiện vòng. Nếu trang đích lại không có việc hoặc quay lại target đã auto thăm, trả đường xử lý hiện hành hoặc blocker có lý do; không lặp host transition không giới hạn. Ca nhiều page target cần policy ưu tiên riêng và đánh giá sau, không âm thầm chọn theo một hint.

### 16.3. Commit, preview, exposure và resume

Làm tương tự auto-query admission: tính navigation proposal trong working context, compile trang đích, rồi chỉ commit overlay khi ghi admission của request thực tiếp theo. Tên metadata dự kiến `cm_auto_candidate_view`, giữ from/to, query ID, revision trước/sau, target/page binding và lý do chỉ còn một bước. Đây là host transition, không có model reply tương ứng.

`prepare(admit=False)` không ghi navigation, expose card hoặc thay query progress. Nếu trang đích không fit hay admission thất bại, không publish overlay. Runtime/context reducer, full replay oracle và guard phải xử lý overlay ở đúng thứ tự và đúng một lần sau commit; không chỉ sửa code đường chạy liên tục mà bỏ resume. Việc thêm metadata là thay đổi contract/navigation riêng, không gộp vào đợt snapshot giữ schema cũ.

Cards chỉ được tính đã giao theo điều kiện payload/receipt hiện hành; admission hoặc host chuyển trang chưa tự tăng `survey_exposed`. Không tạo `request_result` giả, token giả, action count/controller request giả hoặc dấu `review_complete` cho B. STOP sau admission trước send vẫn theo receipt known-zero hiện tại; unknown remote call vẫn theo dõi cùng call.

Trace ghi riêng số host auto transitions và controller navigation calls còn lại. So saved request trên cùng danh sách, cùng số B đã chốt và cùng pending/partial status. Không quy một action bị cắt thành mức tiết kiệm latency cố định khi chưa có run thật.

## 17. Nghiệm thu: nhanh và ít input hơn nhưng không đánh mất năng lực đánh giá

### 17.1. Ba loại parity, không áp một gate cho mọi thay đổi

| Stage | Được phép khác | Phải giữ |
| --- | --- | --- |
| A: runtime snapshot + common frame | Code binding khai báo; host counters/time | Wire bytes, schema, input count, refs/aliases/dispatch, source plan, state/usage/action results theo mục 10/13, trong cùng prompt/navigation policy. |
| B: compact descriptor, giữ tool đơn | Descriptor bytes, prompt/input count và binding | Canonical action space, decoder schema, field names/conditions/bounds, packet nguồn và role, validation, repair/recovery, selection rules. |
| C: phase instructions | Instruction text/profile/hash, prompt/input count | Cùng packet, offered actions, decoder, common/phase reasoning obligations và request render/count/resume invariants. |
| D: deterministic paging | Một model navigation admission/action được bỏ; thêm overlay host và counters | Các request thực nhận đúng cards/raw; source order, model decisions, conclusions, exposure, pending, usage actual/unknown và khả năng resume. |
| E: batch-only hoặc packet lớn hơn | Action surface hoặc evidence planning có version riêng | Các bất biến nguồn/định danh/coverage và chất lượng phải kiểm lại riêng. Chưa thuộc default đề xuất đầu. |

Không buộc input token parity ở B/C hoặc chuỗi action parity nguyên xi ở D; thay vào đó phải liệt kê exact intentional differences. A vẫn so byte parity với baseline tương ứng của **mỗi** policy. Không dùng profile mới làm cách né một sai khác ngoài dự kiến.

### 17.2. Gate local trước mọi thử nghiệm model

| Nhóm kiểm | Tiêu chí bắt buộc |
| --- | --- |
| Descriptor ↔ schema | Mọi family ref/quote/no-selector hiện được offer đều biểu đạt rõ; valid examples qua schema; cả-ref-và-quote, thiếu selector, negative-only sai decision vẫn bị chặn. Không chỉ so union field names. |
| Single/batch | Bước B vẫn nhận hai API; batch 1/2/3, max hạ 2/1, quote recovery và item lỗi có cùng semantics, không settle nhầm item/span khác. |
| Trường và nguồn | Same packet raw/hash/offset/order/structure, citation/attribution/support roles, phản chứng và đường đọc thêm; cùng canonical action cho cùng scripted reply ra cùng kết quả. |
| Phase rule coverage | Mỗi quy tắc ở mục 14.2/15.1 có nơi xuất hiện rõ trong từng pha cần nó. Test nối renderer/profile với phase thật, không chỉ snapshot một danh sách profile names. |
| Count/send | Prompt hash/count từ admission khớp bytes send; schema/aliases cùng packet; không thiếu instruction text, không dùng nhầm legacy counter hoặc cache profile cũ. |
| Preview/resume | Không thay committed state khi preview; admission/receipt/action boundaries, frozen profile registry, pending unknown, STOP, repair và length recovery đều khôi phục đúng. |
| Paging | Default page size 5 với nhiều trang; edge 1; trang còn pending; chỉ một tool nhưng nhiều page targets; next hint chưa đủ; wrong query/ref; restart và STOP quanh commit. |
| Host accounting | Auto navigation không tăng model usage/coverage/selection; pending card chưa giao vẫn pending. Cả failure/fallback/unknown được giữ, không báo saved call chưa biết. |
| Tương tác với runtime | Prefix hash, state/context overlay và các index có parity đúng policy; cache keyed theo descriptor/profile/evidence plan; không đọc full history trong emitter/probe. |

Dùng original passages với hashes/offsets cho các ca cần nguồn pháp lý; fixture được script chỉ chứng minh contract/navigation. Tối thiểu giữ các ca `[2](a)/(b)`, các khối trích riêng ở [18] của `021095.txt`, mở đầu Prothonotary của `070847.txt`, và body quote Aqua-Gem của `011064.txt` khác tự định danh B. Không biến kết luận model trong pilot cũ thành gold.

Mục tiêu engineering đề xuất cho B: trên hai packet A đã khóa ở audit, giảm ít nhất 25% total input sau khi descriptor có đủ điều kiện và vẫn giữ tool đơn; đo thêm packet ref/quote nhiều lựa chọn, unresolved/recovery và context dài. Đây là mục tiêu cần kiểm, không phải kết quả ablation đã đạt cho descriptor hoàn chỉnh. Nếu không đạt, báo chi phí thực và cân nhắc mức compact; không cắt raw/quy tắc để vượt ngưỡng. B/C không được tăng lỗi local hay làm mất action hợp lệ để đổi lấy token ít hơn.

### 17.3. Kiểm chất lượng suy luận khi có authorization/pilot sau này

Offline không chứng minh model không suy giảm khi thay prompt. Đề xuất trước khi đổi default: người dùng/AG chạy paired-packet comparison trên cùng nguyên văn/refs/context, rồi integrated pilot namespace mới cho từng stage đã qua local. Codex chỉ chuẩn bị code/lệnh và phân tích receipts theo phân công hiện hành.

Paired-packet so baseline với B, rồi B với C, không đổi cùng lúc batch API, raw packet và prompt. Đánh giá có evidence nguồn về: proposition có đủ điều kiện/ngoại lệ; attribution đúng; các ý độc lập vẫn được đánh dấu; ref/quote chọn đúng phạm vi; yêu cầu thêm context khi thiếu; identity bridge liên kết A tới chính B; không chọn chỉ vì cùng quy tắc hoặc cùng trích C; counterevidence không bị bỏ.

Không yêu cầu output JSON giống hệt baseline để coi đúng, và cũng không coi agreement với baseline là gold. Dùng người review/evaluator tách khỏi solver, giữ gold chỉ ở evaluator. Query/case set và tiêu chí quyết định phải freeze trước khi xem kết quả; không tune theo lỗi trên holdout. Khi chưa đủ mẫu/nguồn chuẩn để kết luận không kém hơn, ghi **chưa xác minh không suy giảm**, giữ full profile làm default. Fallback sang full chạy trong namespace mới, hoặc qua nhánh fallback đã được bind/version từ prepare; không thay prompt policy giữa run hoặc render lại instructions của admission cũ. Không tuyên bố đạt từ vài fixture.

Integrated pilot phải báo theo cùng lượng công việc đã hoàn tất: byte A được screened hợp lệ, source needs/grouping, query đã chạy, B pending/đã đọc/đã chốt và prediction availability. Báo schema/ref repairs, malformed/length, retry, lỗi source/identity, premature complete/partial, omissions, controller/embedding/reranker requests, actual/unknown tokens và latency cả run lỗi/STOP. Khi có gold, báo pool/shortlist retention và prediction precision/recall/F1 riêng; token/latency ít hơn nhưng thiếu evidence hoặc kết thúc sớm không đạt.

Không đặt kết luận thống kê từ một án hay một lần gọi. Số mẫu/lần lặp và ngưỡng không suy giảm phải được định trước theo evaluator và baseline noise có thật; nếu dữ liệu chỉ đủ engineering acceptance thì chốt đúng mức đó. Nếu xuất hiện lỗi mới làm mất nguồn/attribution hoặc sai identity do prompt, không mặc định đổ cho model: giữ receipts và exact prompt, rollback stage gây lỗi, kiểm lại obligation coverage trước khi thử tiếp.

### 17.4. Đo lợi ích riêng từng tầng

Đo cấu hình nối tiếp: legacy; A; A+B; A+B+C; A+B+C+D. E nếu có là thí nghiệm riêng. Các phép đo packet giữ cùng `RegionPlan`; phép đo end-to-end báo mọi thay đổi workload, không trừ thời gian hai run khác action rồi quy hết cho cache.

- Host: p50/p95 compile theo mode/prefix, full/tail reads, frame/probe/tokenizer counts, cache hit/miss, context copies, RSS; không suy ra từ thời gian model.
- Input: exact total mỗi request, delta catalog/instructions, raw và metadata, phân bố theo pha; cộng cả retry/repair và unknown riêng. Không cộng component standalone như thể bằng exact total.
- Calls: model navigation còn lại, host auto transitions, assessment/identity/search calls, cùng số byte/B được xử lý. Không dùng số 107/178 cũ làm kết quả tiết kiệm current HEAD.
- Remote: provider-reported generation và client transport wait tách riêng; phase prompts có thể đổi prefix-cache hit rate nên ít token chưa tự bảo đảm latency giảm tương ứng. Chỉ kết luận sau đo actual receipts; không tự đổi vLLM/GPU/scale-down trong đợt này.

## 18. Kế hoạch thực hiện và phạm vi bàn giao bổ sung

1. **Freeze baseline và obligations:** lưu binding, packet/source refs, descriptor/schema, instruction text và counter; dùng 17 mẫu audit làm điểm khởi đầu, bổ sung default shortlist nhiều B và history dài. Lập bảng obligation ↔ phase/descriptor trước khi rút text.
2. **Làm A theo mục 9/13:** runtime/read view và common frame/cache có parity trong full policy. Không dùng compact prompt để che một lỗi chọn vùng/cache.
3. **Làm B1 độc lập:** emitter descriptor mới, giữ tool đơn, packet/schema/validation nguyên contract. So exact token và các ca điều kiện; không đổi instructions ở commit này.
4. **So hành vi B1 khi có pilot:** trước mắt có thể hoàn tất local/preflight và chuẩn bị lệnh. Chưa có inference evidence thì profile mới là opt-in experimental, chưa thay default vì token size đẹp.
5. **Làm C:** immutable prompt registry/spec, per-request binding và renderer/counter thống nhất; packet planner baseline tách admission renderer. Qua replay/resume/repair rồi mới paired-packet/pilot C.
6. **Làm D riêng:** strict one-target auto paging, admission overlay, full/incremental reducers và exposure/accounting. Đo đúng bước controller đã bỏ trên fixture tương đương; pilot sau nếu được giao.
7. **Chỉ sau nghiệm thu từng stage mới xét E:** batch-only, larger source packets, nhiều cards hơn hoặc thay output cap. Mỗi phương án có policy/binding/evidence riêng, chưa là phần phải triển khai của đề xuất đầu.

Giao một `implementer` sở hữu lần lượt `engine.py`, `source_gate.py` (contract export tối thiểu), `model_view.py`, `live.py`, `agent_harness/modal_qwen.py` và module mới dự kiến `catalog_descriptor.py`, `prompt_profiles.py`; phần paging thuộc `passage_review.py` và reducer tương ứng. File nào đã thuộc snapshot/frame ở mục 9/13 phải hoàn tất/ghép tuần tự với cùng implementer, không cho hai agent sửa song song. Không sửa worker/model deployment nếu API hiện có đủ dùng.

`tester_advanced` review read-only invariants, prompt/packet boundaries, bindings, action-space và resume; tester sở hữu test riêng khi được giao, như `test_catalog_descriptor.py`, `test_prompt_profiles.py`, `test_auto_candidate_navigation.py` (tên dự kiến, chưa có). Main chốt nghiệm thu cuối; tối đa hai subagent, tester phải kiểm implementation cuối. Các phase có thể dùng lại tester_advanced thay tester theo AGENTS.md, không mở vượt giới hạn.

Các profile/cờ là đề xuất thiết kế, chưa phải CLI sẵn có: `full` làm baseline; `compact_catalog_v1`; `phase_instructions_v1`; `deterministic_candidate_paging_v1`; `legacy_evidence_plan_v1` giữ packet policy. Bind khi prepare vào namespace mới; không cho run/resume tự đổi giữa chừng. Profile không được tự bật vì thiếu context hoặc chạm cap; fallback trong cùng profile phải được version và ghi rõ.

Đợt cập nhật mục 14–18 **chỉ sửa file kế hoạch này**. Dữ liệu token đến từ audit local của lượt trước, đã đối chiếu lại summary và binding; 5 test điều hướng đã PASS trong lượt audit đó. Không chạy lại chúng chỉ vì sửa prose. Các module/cờ/test mới ở trên chưa được triển khai, chưa có model comparison hoặc live speedup/noninferiority mới. Các chi tiết snapshot/frame của mục 1–13 vẫn là đề xuất chưa triển khai.

## 19. Checkpoint triển khai local — 24/11/2026

Mục này cập nhật trạng thái sau yêu cầu triển khai; các câu “chưa triển khai” trong mục 1–18 mô tả thời điểm lập kế hoạch ngày 23/11, không thay cho checkpoint hiện hành. [Báo cáo và lệnh tái hiện](../../reviews/cm4_incremental_runtime_20261124/REPORT.md) ghi đầy đủ phạm vi và giới hạn.

- **A — runtime/common frame:** đã có suffix ledger, after-commit hook, exact prefix hash, state/context/query/exposure/navigation indexes, detached public views, invalidation/rebuild và operation-scoped frame/memo. Default CM4 dùng runtime mới; ngoài CM4 giữ compatibility path. Đã kiểm lỗi trước/sau commit, external append, alias/mutator, source drift, preview và resume. Distinct catalog/span/fit vẫn dựng theo dependency thực; không đổi first-fit hoặc cắt menu bằng estimate.
- **B1 — compact descriptor:** đã có `catalog_descriptor.py`; giữ tool đơn, batch 1–3/recovery và decoder nguyên contract. Cờ prepare `--catalog-profile compact_catalog_v1`; mặc định `full`.
- **C — instructions theo pha:** đã có `prompt_profiles.py`/InputPolicy, registry literal freeze trong plan, prompt spec trong manifest/admission và `send_frozen` tại transport. Cờ `--instruction-profile phase_instructions_v1`; mặc định `full`. Renderer mới chạy sau legacy evidence planner nên giữ nguyên packet.
- **D — paging xác định được:** đã có pure guard và admission context overlay, không giả model action/request/exposure; cờ `--candidate-navigation deterministic_candidate_paging_v1`; mặc định `manual`. Pending/repair/recovery/STOP/identity/multiple targets/visited chặn auto.
- **E — chưa làm theo chủ ý kế hoạch:** batch-only, packet lớn hơn, thay output cap/model/GPU hoặc policy rerank không thuộc mặc định đầu.

Nghiệm thu engineering cuối: **228/228 CM4 + 85/85 shared PASS**; script differential 10 stage so baseline `0c2da9f` giữ exact wire/schema/handles/dispatch/aliases/coverage/excerpts/context và state trừ code binding được khai báo. Preflight namespace `cache/cm4-incremental-compact-final-20261124` giữ span `[0,929)` của `021095.txt`, input **3.443 token**, spec/count và code binding khớp, **0 provider calls**. Lệnh run inference chỉ chuẩn bị trong báo cáo, chưa thực thi.

Trên hai packet A audit cố định: compact catalog 6.546 → 4.392 và 7.621 → 5.176 token; ghép phase instructions thành 3.437/4.221 token. Đây là size test cùng nguồn/schema, không là kết quả chất lượng model. Projection state/context/hash ledger 716 event p50 1.434,376 → 12,407 ms, bootstrap 3,081 s; working-set trước/sau bootstrap khoảng 68,0 → 176,3 MiB. Không lấy số này làm speedup toàn run hoặc hứa RAM hằng số.

**Chưa nghiệm thu:** noninferiority của prompt mới, speedup live, recall/F1, benchmark full compile nhiều prefix dài/RSS để chứng minh mọi mục tiêu hiệu năng của mục 10/13. Giữ các profile thay prompt opt-in và full baseline, không tự đổi default theo token savings. Dùng namespace mới khi đổi binding; không ép resume run lịch sử. Paid reuse còn duyệt cached search outcomes để kiểm journal/provenance; không loại kiểm nguồn/usage vì cache.
