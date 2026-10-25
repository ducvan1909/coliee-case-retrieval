# Nghiên cứu bổ sung cho pipeline toàn corpus

## 1. Khoảng trống của nghiên cứu vòng đầu

Vòng đầu xác lập đúng mô hình source/part/annotation/provenance của Lynx nhưng chưa giải quyết đủ ba vấn đề: cấu trúc bề mặt thiếu hoặc sai; phân đoạn ngữ nghĩa không trùng paragraph/heading; và chi phí khi chạy trên 9.556 án. Vì vậy vòng bổ sung xem structure, citation, entity, rhetorical role, AU và relation là các lớp dự đoán khác nhau.

## 2. Lynx: phần có thể chuyển sang pipeline

### Portfolio of legal NLP and document curation services (2019)

Nguồn: https://aclanthology.org/W19-2207.pdf, Section 3, PDF pp.2–8; Section 4, pp.8–9.

- Structure recognition dùng pattern nhưng bài tự ghi đây vẫn là open problem; không hỗ trợ dùng marker/heading làm ground truth.
- NER, terminology, reference resolution, summarisation và similarity là các service tách rời. Điều này hỗ trợ sidecar có producer/version riêng, không hỗ trợ hợp nhất mọi output thành kết luận pháp lý.
- Term extraction giữ context và source reference, phù hợp với yêu cầu mọi annotation truy về exact span.
- Không có benchmark COLIEE, token, throughput hoặc semantic omission end-to-end.

### Orchestrating NLP Services for the Legal Domain (2020)

Nguồn: https://aclanthology.org/2020.lrec-1.284.pdf, Sections 4.1–4.3, pp.2333–2337; Section 6, pp.2338–2339.

- Document store, workflow state và worker thay thế được hỗ trợ cho contract/cache/resume.
- Deployment và evaluation còn là future work; không dùng bài này để biện minh chuỗi service dài hoặc chi phí thấp.

### Fine-Grained NER (2019)

Nguồn: https://www.dfki.de/fileadmin/user_upload/import/10980_Leitner2019_Chapter_Fine-GrainedNamedEntityRecogni.pdf, Section 3.2 và Table 1, pp.6–7; Tables 2–5, pp.9–11.

- 750 án liên bang Đức, khoảng 66.723 câu, 2,16 triệu token, 53.632 entity và 19 lớp; CRF/BiLSTM đạt F1 cao trong corpus đó.
- Đây là bằng chứng rằng citation/court/decision candidate không bắt buộc phải dựa hoàn toàn vào regex hoặc LLM sinh văn bản.
- Một annotator chính, IAA để future work, split theo sentence và citation Đức có tính công thức. Không chuyển F1 sang án Canada; NER không xác nhận speaker, treatment, AU hoặc relevance.

### Deliverables và evaluation

Danh mục chính thức: https://cordis.europa.eu/project/id/780602/results. Các deliverable D3.6 extraction/linking, D3.8 annotation, D3.9 IR và D5.8 evaluation xác nhận phạm vi service và pilot, không cung cấp benchmark đáp ứng bài toán hiện tại. Sự tồn tại của API/container không chứng minh endpoint còn hoạt động hoặc component đáng chạy trên toàn corpus.

## 3. Nghiên cứu ngoài Lynx về cấu trúc ngữ nghĩa

### Semantic Segmentation via Rhetorical Roles (2022)

Nguồn: https://aclanthology.org/2022.nllp-1.13.pdf, pp.153–171; code/data: https://github.com/Exploration-Lab/Rhetorical-Roles.

- Gán vai trò cho từng câu theo chuỗi để tạo các đoạn ngữ nghĩa; 13 lớp gồm facts, arguments, issue, precedent, ratio và ruling.
- Mô hình đa nhiệm dùng chuyển đổi nhãn theo tài liệu; bài kiểm tra domain transfer và distillation. Điều này hỗ trợ giả thuyết rằng context/thứ tự tốt hơn phân loại từng câu độc lập.
- Corpus chỉ 100 tài liệu thuộc competition law và income tax của Ấn Độ; license repository GPL-3.0, corpus được mô tả CC-BY-NC. Phải kiểm tra license cụ thể trước khi tái sử dụng.
- Vai trò rhetorical chỉ là annotation candidate; không đồng nhất với AU hoặc noticed case.

### LegalEval 2023

Nguồn task: https://aclanthology.org/2023.semeval-1.318.pdf, Section 3; baseline/code: https://github.com/Legal-NLP-EkStep/rhetorical-role-baseline.

- Task A phân loại từng câu trong chuỗi thành 13 vai trò. Các hệ thống dùng hierarchical BiLSTM-CRF, RoBERTa và đặc trưng thủ công.
- Kết quả công bố của các team khác nhau cho thấy task khả thi nhưng không giải quyết triệt để class imbalance, domain shift hoặc speaker/treatment.
- Đây là nguồn taxonomy và baseline local-model; không phải checkpoint được chấp nhận mặc định cho COLIEE.

### LegalSeg (2025)

Nguồn: https://aclanthology.org/2025.findings-naacl.63.pdf, pp.1129–1144; code: https://github.com/ShubhamKumarNigam/LegalSeg.

- 7.120 án và khoảng 1,487 triệu câu, bảy vai trò; so Hierarchical BiLSTM-CRF, transformer, GNN, role-aware transformer và một LLM instruction-tuned.
- Kết quả chính: broader context, quan hệ cấu trúc và thông tin tuần tự tốt hơn chỉ dùng đặc trưng từng câu; các vai trò gần nhau và class imbalance vẫn khó.
- Quy mô gần corpus hiện tại làm đây là bằng chứng tốt để thử throughput của sequence tagger local. Khác jurisdiction và label ontology vẫn buộc phải đánh giá transfer trên holdout Canada.

### SeqTNS (2025)

Nguồn: https://aclanthology.org/2025.findings-ijcnlp.50.pdf.

- Kết hợp embedding InLegalBERT, phụ thuộc chuỗi và tolerance classes; báo weighted F1 0,78 trên bộ 13 lớp, macro F1 0,83 trên bộ bảy lớp và giảm thời gian train 39–40% so với BiLSTM-CRF trong thí nghiệm của bài.
- Con số giảm train time không phải inference throughput trên GTX 1650, không phải total lifecycle cost và không chứng minh transfer.

## 4. Kết luận kiến trúc được bằng chứng hỗ trợ

| Kết luận | Mức hỗ trợ |
|---|---|
| Raw source, exact offsets và provenance phải là nền | Mạnh |
| Marker/heading chỉ là candidate signal | Mạnh từ audit và giới hạn structure extraction |
| Citation có thể kết hợp rule và local sequence/entity model | Có cơ sở; cần transfer test |
| Rhetorical-role sequence model có thể bổ sung document map | Có cơ sở; cần transfer và throughput test |
| Rhetorical role tạo AU chính xác | Không có bằng chứng |
| Sidecar giúp giảm token/retrieval cost | Chưa có; phải đo end-to-end |
| LLM cần chạy trên mọi bản án | Không có bằng chứng |
| Full KG hoặc chuỗi Lynx service cải thiện COLIEE | Không có bằng chứng |

Các bằng chứng này hỗ trợ source spine, document map, worker thay thế được và LLM chuyển tuyến có ngân sách. Quyết định hiện hành trong `04_pipeline_spec.md` dùng các thành phần đó để xây LegalUnit, AU và Issue metadata có provenance. Lynx không chứng minh boundary/AU/Issue extraction đạt chất lượng trên COLIEE và không quyết định cách nối NN–AU; các phần preprocessing phải được kiểm tra theo `05_experiment_plan.md`.
