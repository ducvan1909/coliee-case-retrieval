# Kiểm thử độc lập runner M3 full corpus

Ngày 08/11/2026. Code fingerprint trong lượt kiểm này: `e4b8b358697c67073134fe5c5929e770d5c9c1e0b30f2cd98fc686b1227e3503`.

**30/30 tests PASS** trong 0,585 giây: 12 test runner/storage mới và 18 regression tests optimization V2. Lệnh tái hiện từ repo root:

```powershell
& .venv/Scripts/python.exe -m unittest `
  pipeline_v2.tests.test_m3_full_storage `
  pipeline_v2.tests.test_m3_full_runner `
  pipeline_v2.tests.test_m3_opt_v2_index `
  pipeline_v2.tests.test_m3_opt_v2_session `
  pipeline_v2.tests.test_m3_opt_v2_runtime `
  pipeline_v2.tests.test_m3_opt_v2_benchmark `
  pipeline_v2.tests.test_m3_opt_v2_cli -v
```

Full runner tests cover 64-sized deterministic batch iteration including final remainder, isolation between simulated and real execution identity, rejecting mixed fake/real dependencies before loading a plan, CLI `plan` without parsing `.env`, fail-closed paginated DB reads, cache verification without repairs, and usage accounting that keeps an unfinished request's tokens unknown.

Failure-path test interrupts immediately after writing a complete cache shard but before DB upsert. Resume uploads that cached vector without another embedding request. A batch journal that says committed while its vector shard is missing fails before inference. These use temporary files, a fake Qdrant store and mocked encoder. Existing Qdrant artifacts, Docker, Modal, credentials, labels and gold were not touched.

The prior review defects in partial DB response validation and A→B→A page-offset cycles now have regression tests and pass on this fingerprint. The tests do not build all 415,693 passages, validate the actual full schedule against the M2 source bundle, create a real Qdrant collection, call the model, measure full-run throughput, or establish COLIEE retrieval quality. Main's separate actual-source plan audit and local CLI smoke must complete before AG runs any Modal workload.

Main update sau test: full plan thật và audit riêng đã PASS, fingerprint production không đổi. Audit đủ7.708rawcases/415.693passages, hash/offset/metadata và6.496batches (batchcuối13); status thật chạy với.env không tồn tại PASS. Evidence: [real_full_plan_audit.json](../reviews/m3_full_validation_v1/real_full_plan_audit.json), [local_acceptance.json](../reviews/m3_full_validation_v1/local_acceptance.json). Đây là kết quả Main trên dữ liệu thật, tách khỏi30tests fixtures/mocks. Chưa chạy Modal, tạo vectors hoặc verify DBfull thật.
