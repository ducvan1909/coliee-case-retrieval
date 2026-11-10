# AG review thiết kế M3 full search — chưa triển khai

Repo `E:/Git/coliee-case-retrieval`; đọc AGENTS.md. User chốt E: vànamespacepipeline_v2. Nhiệm vụchỉreviewkếhoạch, khôngcodeproduction/chạyinference/verifyDBdài/deploy/rebuild/index/đổicấu hình. Khôngmởgold/labels/evaluator hoặc nghiêncứuđãmởnhãn đểtuning kếhoạch.

Đọc đầyđủ `pipeline_v2/docs/plan/M3_FULL_SEARCH.md`. Đối chiếu:

- `docs/plan/SOURCE_CHUNK_INDEX.md` Sections3.4–3.5, `docs/plan/AGENT_AND_EVALUATION.md` vàM3 trong `docs/plan/README.md`.
- `docs/M3_FULL.md`, `reviews/m3_full_validation_v1/AG_REVIEW_ACCEPTANCE.md` và `reviews/m3_full_ag_review_v1/{REPORT.md,findings.json,recomputed_metrics.json}`. Chỉđọcartifactcầnthiết, khônglặpfull audits.
- Codehiệncó `full_corpus/`, `optimization_v2/{index,runtime}.py`, `retrieval/{bm25,qdrant}.py`, readersM2đểkiểm implementationassumptions; đâykhôngphảireviewđãcófull searchcode.

Các đườngdẫntrên tươngđốivớipipeline_v2. Giữnguồn/code/config/artifactslịch sửread-only. Chỉghi báo cáo/scriptsreviewmới ở `pipeline_v2/reviews/m3_full_search_plan_ag_review_v1/`; nếuđãcóthìsuffixmới. Cóthểdùngmocks/tinycounterexampleslocal; khônggọiModal, khôngđọc.env, khôngghiQdrant, khôngnạptoànbộvectorsRAM hoặc hash lạiartifactlớnkhikhôngcần.

Reviewđộđúng/đủvàkhảthi trướcimplementation; khôngchỉđồngývăn bản. Ưutiên6câuhỏiSection11. Tìmcounterexamples: samecasefloodraw hits,query caseexclusiontrướccap,denseties/shortfall,cachedquery vectorreuse,partialchannelRRF,sourceDBdrift,simulatedtoreal,phrasecrosschunk/casefoldoffset,caseBM25khôngpinpoint,contextpaginationparentunknown+quoted,token budgetM4chưachốt. Đánhgiáexactdensefull vàbenchmarkmethods cóthểđosốthậtđược không; đừng suyF1/chấtlượngnoticedtừkếhoạchkỹthuật.

Tách quyếtđịnh đãkhóa(model/M2/fullscope/provenance/no-reembedding) với giátrịđangđềxuất100/4096/20/k60/64KiB và6queries. Đềxuấtthayđổicầnlýdo/test, khôngtuningbằnggold hoặc mởscopeM4. Nêucácphầnkhôngcầnsửa/chưacầnlàm nếuđangoverengineer. KhôngmặcđịnhmọigợiýcủaMain/userđúng.

Đầu ra:

1.REPORT.md: verdictapprove/approve_with_changes/needs_revision,blockers,scope,quyếtđịnhcầnMainchốt,phầnđãđủbằngchứng/phầnchưa.
2.findings.json: id,severity,plansection,evidence/counterexample,impact,recommendedchange,acceptancetest; khônggánproductionbugchochỉmộtđềxuấtthiếuchi tiết.
3.decision_matrix.md: từng6câuhỏiSection11→giữnguyên/sửa/defer,lýdo vàtradeoff.

Khôngsửakếhoạchgốc. BáocáolạiđểCodexMainphânxửvàcậpnhậtrevision; **khôngbắtđầutriểnkhaihoặcchạyremote** saukhireview.
