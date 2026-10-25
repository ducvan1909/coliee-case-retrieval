# Ma trận nghiên cứu Lynx và khả năng áp dụng

## Cách dùng bằng chứng

Các bài được dùng để hỗ trợ một quyết định cụ thể, không dùng uy tín dự án Lynx để suy ra hiệu quả COLIEE. “Implemented”, “containerized” hoặc API xuất hiện trong catalog không chứng minh endpoint còn hoạt động, chất lượng transfer, token saving hay hiệu quả retrieval.

## Phân loại danh mục publications

Trang [Lynx publications](https://lynx-project.eu/publications/articles) liệt kê các bài và proceedings liên quan. Nhóm được đọc sâu gồm document/annotation model, orchestration, NER, terminology, TKG, link verification và các deliverable extraction/annotation/retrieval. Các bài translation, lexicography, democracy, governance và proceedings tổng hợp được loại khỏi quyết định kiến trúc chính vì không phân xử coverage, attribution, treatment hoặc lifecycle cost của COLIEE.

| Nhóm | Mức liên quan | Quyết định có thể hỗ trợ |
|---|---|---|
| Document curation, LKG, annotations | Cao | Immutable source, parts/spans, provenance, derived annotation |
| NLP orchestration/workflow | Cao | Stable contracts, replaceable workers, persisted state |
| Fine-grained legal NER/reference resolution | Trung bình | Candidate citation/court/statute extraction; cần transfer test |
| Terminology/TKG | Trung bình-thấp | Soft query expansion hoặc sidecar experiment |
| QA link prediction/verification | Thấp, preliminary | Predicted relation cần evidence verification |
| Summarization/similarity | Phụ | Candidate signal; không thay exact source |
| Translation/lexicography/proceedings/governance | Không dùng để chốt | Không giải quyết quyết định hiện tại |

## Phiếu đọc sâu

### Developing and Orchestrating a Portfolio of Natural Legal Language Processing and Document Curation Services, 2019

Nguồn: [ACL Anthology PDF](https://aclanthology.org/W19-2207.pdf).

- **Bài toán:** mô tả danh mục 13 legal NLP/document services và orchestration.
- **I/O:** document đi vào; annotations, terms, entities, references, structure, summary, similarity và QA output.
- **Bằng chứng:** Section 3 (PDF pp.2–8) mô tả services; term extraction giữ context/source reference; reference resolution là prototype bán tự động; structure dùng pattern và vẫn là open problem; Section 4 (pp.8–9) mô tả workflow qua Camunda/RabbitMQ.
- **Đánh giá/baseline:** không có end-to-end COLIEE, token-cost hoặc treatment benchmark.
- **Giới hạn:** nhiều component còn là prototype/ongoing work.
- **Transfer:** cao cho provenance và service boundaries; thấp cho full KG hoặc mặc định chạy nhiều service.
- **Quyết định hỗ trợ:** annotation phải truy về source; component có I/O/fingerprint riêng.

### Orchestrating NLP Services for the Legal Domain, 2020

Nguồn: [ACL Anthology PDF](https://aclanthology.org/2020.lrec-1.284.pdf).

- **Bài toán:** Document Manager + Workflow Manager cho legal NLP services.
- **Kiến trúc:** REST/OpenAPI, persisted workflow state, shared document storage, worker thay thế được; Sections 4.1–4.3, pp.2333–2337.
- **Giới hạn:** Section 6 để deployment/evaluation cho future work; không báo token, failure rate hoặc semantic quality end-to-end.
- **Transfer:** áp dụng stable contract, checkpoint và document/annotation separation.
- **Không áp dụng mặc định:** Camunda, MongoDB, PostgreSQL, Kubernetes hoặc RDF store cho pilot hiện tại.

### Fine-Grained Named Entity Recognition in Legal Documents, 2019

Nguồn: [DFKI PDF](https://www.dfki.de/fileadmin/user_upload/import/10980_Leitner2019_Chapter_Fine-GrainedNamedEntityRecogni.pdf).

- **Dữ liệu:** 750 German federal court decisions, 66.723 câu, 2.157.048 tokens, 53.632 entities, 19 fine-grained classes; Section 3.2/Table 1, pp.6–7.
- **Phương pháp:** CRF và BiLSTM; 10-fold sentence-wise cross-validation.
- **Kết quả:** CRF fine-grained F1 khoảng 93,23; BiLSTM fine-grained 95,46 và coarse 95,95; Tables 2–5, pp.9–11.
- **Giới hạn:** một annotator chính, IAA để future work; split theo sentence; citation Đức có tính công thức; class imbalance và non-standard forms gây lỗi.
- **Code:** [Legal-Entity-Recognition](https://github.com/elenanereiss/Legal-Entity-Recognition) dùng TensorFlow/Keras cũ; khả năng tái lập hiện đại phải kiểm tra riêng.
- **Transfer:** chỉ coi NER là candidate generator; không chuyển thẳng F1 sang English Canadian cases, không suy ra authority/treatment/noticed case.

### LKG specification v1.2

Nguồn: [LKG specification](https://lynx-project.eu/doc/lkg/).

- `LynxDocument` giữ text và metadata.
- Parts/annotations trỏ vào vùng text bằng offsets và có parent/provenance/confidence.
- Validation bảo đảm cardinality/offset/structure, không bảo đảm legal semantics.
- **Transfer:** dùng `source_hash + SpanRef + producer fingerprint + confidence/status`.
- **Không bắt buộc:** RDF/NIF/JSON-LD. JSON/SQLite phù hợp nếu giữ cùng invariants.

### Terminology extraction

Nguồn: [CEUR paper](https://ceur-ws.org/Vol-2309/07.pdf) và bài syntactic-pattern Spanish được dẫn trong danh mục Lynx.

- JATE experiment dùng 20 Spanish labour-law documents, 21.475 tokens; legal patterns thêm khoảng 6% terms với CValue và 3,5% với TF-IDF; Sections 4.4–5, pp.8–10.
- Các nghiên cứu pattern là preliminary; termhood, variant handling và expert validation còn hạn chế.
- Tool công khai phụ thuộc JATE beta/Solr 5.3.0: [terminology-extractor](https://github.com/oeg-upm/terminology-extractor).
- **Transfer:** terminology chỉ là soft signal/query expansion candidate; không hard filter và không được coi là concept correctness.

### Creation and Enrichment of a Terminological Knowledge Graph

Nguồn: [CEUR PDF](https://ceur-ws.org/Vol-2598/paper-07.pdf).

- **Phương pháp:** sáu task gồm refinement, disambiguation, enrichment, relation validation/extraction và RDF conversion.
- **Đánh giá:** Section 5 chủ yếu là evaluation plan; một số task ongoing/pending.
- **Transfer:** hữu ích để tách candidate, disambiguation, validation và publication thành các stage.
- **Không hỗ trợ:** full TKG cải thiện COLIEE recall hoặc lifecycle cost.

### Question Answering for Link Prediction and Verification

Nguồn: [DOI record](https://doi.org/10.1007/978-3-030-32327-1_23).

- Bài ngắn, abstract mô tả preliminary results dùng QA để tìm/kiểm tra KG links.
- Không lấy được toàn văn đủ để xác minh dataset, baseline, metric và bảng kết quả trong nghiên cứu này.
- Chỉ dùng như ý tưởng: predicted edge cần external evidence; không dùng làm bằng chứng hiệu quả.

### Deliverables và platform tổng kết

- [D3.8 annotation/summarisation](https://zenodo.org/records/3865668) mô tả services nhưng vẫn nói tiếp tục development/evaluation.
- [D3.9 IR/recommender](https://zenodo.org/records/3870457) mô tả Search, Terminology Query, QA và Semantic Similarity; containerized không đồng nghĩa đã chứng minh transfer.
- [CORDIS project results](https://cordis.europa.eu/project/id/780602/results) liệt kê deliverables extraction/linking, workflow, annotation, IR và evaluation.
- [Lynx platform 2022](https://www.sciencedirect.com/science/article/pii/S0306437921001563) xác nhận platform/use cases; không cung cấp benchmark COLIEE noticed-case retrieval.
- [API catalog](https://lynx-project.eu/doc/api/) cho biết các interface từng được mô tả. Nghiên cứu này không gọi live endpoints, nên không xác nhận availability/SLA/authentication hiện tại.

## Kết luận có thể và không thể rút ra

| Kết luận | Đánh giá |
|---|---|
| Source bất biến, parts/spans, provenance | Được hỗ trợ mạnh |
| Document và annotation lưu tách | Được hỗ trợ mạnh |
| Service có contract, state và worker thay thế | Được hỗ trợ mạnh |
| Citation/NER/term extraction có thể sinh annotation/span proposal | Được hỗ trợ có giới hạn; cần transfer test |
| Annotation giúp giảm token COLIEE | Chưa có bằng chứng; phải đo |
| Full KG tăng Recall/F1 | Không có bằng chứng trực tiếp |
| Multi-service workflow đáng tin/rẻ hơn | Không có bằng chứng trực tiếp |
| Summarization hoặc sidecar có thể thay raw source | Không được hỗ trợ |

Đóng góp hữu ích nhất của Lynx cho pipeline này là **document contract, span provenance và component isolation**, không phải việc sao chép toàn bộ ontology hoặc deployment stack.
