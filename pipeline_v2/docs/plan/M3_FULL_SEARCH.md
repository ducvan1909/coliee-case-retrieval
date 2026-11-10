# Kế hoạch chi tiết M3 full search

Ngày09/11/2026. Trạng thái: **draft để người dùng và AG review thiết kế; chưa cho phép triển khai theo tài liệu này**. Bản này cụ thể hóa M3 trong [kế hoạch tổng thể](README.md), [nguồn và context](SOURCE_CHUNK_INDEX.md), [agent và evaluation](AGENT_AND_EVALUATION.md). Sau review, Main phân xử và chốt revision trước khi code.

## 1. Mục tiêu và giới hạn

Agent gửi một câu tìm kiếm, nhận các unique candidate cases từ toàn corpus cùng các đầu mối có thể mở và kiểm chứng. Retrieval hỗ trợ truy tìm nguồn A sử dụng; similarity/rank không tự chứng minh noticed relation.

Đầu ra đợt này: full search session, ba kênh tìm kiếm, fusion theo case, literal/identity tools, evidence open và diagnostic CLI; tests và lệnh AG kiểm thực tế. Không triển khai controller M4, legal assessor, selector noticed, tuning gold/F1 hoặc snapshot/restore DB full. Không embed lại corpus.

Tài sản có sẵn và chỉ đọc:

| Tài sản | Bản sử dụng |
|---|---|
| Full run | `pipeline_v2/artifacts/m3_full_train_20261108_v1` |
| Scope |7.708 train cases,415.693 passages |
| BM25 | `lexical.sqlite3`,4.357.505.024bytes, case và passage postings |
| Dense collection | `coliee_m3_full_ef2f4d6950a5b9fd`,415.693points, Qdrant local |
| Vectors |6.496 committed shards,2560-dimFP32; không gom toàn matrixRAM |
| Model |Qwen3-Embedding-4B,revision5cf2132abc99cad020ac570b19d031efec650f2b,appV2L4 |
| M2 |accepted seal0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6 |

Full ingestion/DB integrity đã PASS theo [nghiệm thu](../../reviews/m3_full_validation_v1/AG_REVIEW_ACCEPTANCE.md); đó chưa phải search-level acceptance.

## 2. Namespace và phụ thuộc bất biến

Đề xuất code mới `pipeline_v2/full_search/`, CLI `m3_search.py`, profile `configs/m3_search.json`; không sửa code/config đã bind pilot/full run. Tests/reviews mới tách riêng. Đây là layout đề xuất, chưa tồn tại implementation.

Search manifest buộc full-plan hash/seal, embedding fingerprint, collection, compatibility receipt, reader/tokenizer/code dependencies, search policy version và universe. Không import labels/gold/citation-link studies/nguồn phục hồi web vào runtime. Search nhận query case chuẩn đã có trong train; query case ngoài corpus chỉ trong chế độ diagnostic được ghi rõ, không tự nới benchmark universe.

Mỗi tool request có request ID, phiên bản inputs/profile/index, thời gian, channel results và giới hạn. Log nằm ngoài source/index artifacts. Một query được thực thi lặp có thể có record riêng, không giả như chưa tốn request.

## 3. Session và kiểm tra toàn vẹn

Mở session: kiểm full plan seal/code/provenance và raw-source hashes theo immutable-snapshot contract; kiểm real compatibility và embedding fingerprint. SQLite read-only; lazy metadata theo hitIDs; vectors đọc từng shard cần dùng, cacheLRU có cap. Hash SQLite4,36GB một lần khi mở/revalidate vẫn có I/O; không quảng cáo startup tức thời.

Readiness cần receipt verifyfull do Codex/AG đã lưu: bind collection/fingerprint/plan/cache scope, kết quả PASS và evidence hash. Receipt lịch sử không chứng minh DB hiện tại bất biến. Mỗi request kiểm schema/exact count và payload/score của các returnedhits. Explicit `verify` là audit full riêng, không lặp25phút trước mỗi search. DB có thể bị sửa đồng thời ngoài tool: chặn nếu phát hiện, không hứa detect mọi mutation chưa trả về; benchmark nên dùng DB read-only từ phía workload, không chạy writer.

Session không hash toàn corpus mỗi search. Open source kiểm raw hash ngay lúc đọc; snapshot drift cần invalidate/reopen. Longlived session phải có explicit revalidate, không dựa vào mtime để chứng nhận hash. Guard code/profile rẻ trước request và sau response; không dùng receipt stale để tiếp tục query RPC.

Local tools/CLI help, lexical-only, phrase, identity và open không đọc.env hoặc gọiModal. Chỉ dense/hybrid cần query embedding và nạp authlocal. Khởi tạo queryencoder lazy sau validateinput/readiness. Không redeploy/preflight ngầm. Vectorcache search là tùy chọn version riêng; ban đầu không semanticcache và không tự reuse vector từ querykhác.

## 4. API dự kiến và lỗi

| API | Đầu vào và hành vi |
|---|---|
| `search_corpus` |query case ID,text,channels,limit,channel case budget,scan budget; trả rankedcases/hits/channel coverage |
| `search_case` |case ID,text,mode lexical/literal; tìm toàn case đã biết, gồm query case; không denseRPC mặc định |
| `search_phrase` |literaltext,scope corpus/case,matchingmode,limit,cursor; trả exactraw spans |
| `search_identity` |text,scope/limit; literal/lexical leads, không danh tính inferred |
| `open_source` |case ID+source hash+handles/hitIDs,byte budget,cursor; trả parent/context/raw/pending |
| `revalidate` |kiểm lại snapshot; lỗi invalidate session |

Tool names có thể điều chỉnh khi triển khai để khớp adapter M4 nhưng semantics phải giữ. `search_corpus` trong production luôn cóquery case để exclusion; `search_case(query case)` vàopenquery vẫn được phép đọc query.

Validate canonicalIDs, limit/budget/cursor bound trước RPC. Text query embedding dùng instructionV2/tokenizer đã khóa, cap448 fulltokens; quá dài trả lỗi có thể hành động để agent viết lại, không truncate/chunk query âm thầm. Không coi rawquery full text là mặc định embeddinginput.

Thất bại một channel: default hybrid fail rõ và lưu các kết quả/request đã có; không tự trả rank như đủ3kênh. Nếu caller chủ động chọn partialmode, response nêu channel thiếu và policy khác, không so như cùngbaseline. Timeout giữ usageunknown, không autoretry; retry cần explicit request và ledger riêng. Emptyhits hợp lệ khác unavailable/error.

## 5. Ba kênh và unique-case budget

Giữ BM25 analyzerUnicodeword/casefold/no-stopwords,k1=1,5,b=0,75 đã có. Casechannel dùng casefull-text posting; passagechannel dùng coreM2; dense dùng corevectors, exactcosine Qdrant làm baseline. Không đổi chunk/model, chưa dùngreranker/HNSWapprox cho baseline. HNSW đã có không đồng nghĩa dùng approximate khi request exact=true.

Exclusionquery case phải thực hiện ở DB/SQL trước rawhitlimit ở mọi kênh, không lọc hậu kỳ sautopK. Casechannel trả case trực tiếp; passagechannels dedup bằng besthit rank, unique-case rank mới là đầu vào fusion. Giữ nhiều passageleads cócap mỗi candidate nhưng không cộng phiếu sibling/overlap.

**Không bê scan_cap1024pilot sangfull mà gọi cùng unique-case budget.** Đề xuất initialreviewprofile: output20cases, mỗi channel hướng tới100uniqueeligiblecases, initialrawscan256, geometricexpand tới4096raw hits hoặc universeexhausted. Các con số là startingpolicy để review, chưa tối ưu bằnggold. Mỗi vòngquerydensetái dùng cùngquery vector, không gọi lạiembedding. SQLBM25 có thể iterate thứ tự ổn định; Qdrantexpand topK yêu cầu dedup/recompute không cộngdồn phiếu.

Mỗi channel báo requested/returnedunique/raw hits,scanlimit,exhausted/capped/complete_for_requested_budget. Nếu4096hits vẫn chưa đủ100cases thì giữbudget_shortfall, không tuyên bố exhaustive hoặc equalbudgetachieved. So sánh3kênh dùng cùnguniquecasebudget và báoshortfall, không nângk chỉ đểche. Chỉ chọn exact approach nếu latency thực tế chấp nhận; nếu không, đề xuất policyapprox riêng và đo recallvs exact trước đổi.

Tie-breaklexical scoredesc rồipassage ID/case ID. Dense topK ở biên cóties: kiểm tie-aware numeric tolerance; không hứa IDset ổn định tuyệt đối khi servercắt qua tie. Trảboundarytie/coverageuncertainty nếu không resolve được trong scan budget. Không đổi thànhsortlocal đểkhẳng định đã thấy mọi hit bằngđiểm ngoàitopK.

Fusionkhởi đầu equalweightRRFk60 trên rankunique-case của3kênh, mỗi case tối đa1contribution/channel. Không cộng rawscores khác scale. Tiecase dùngcase ID; missingchannel không tựnormalize đểgiả profile đủkênh. Outputcap chỉáp saufusion; preserve per channelcandidate/rank/score và matchedpassages. Phrase/identity không tự thêm thànhkênhRRF thứ4/5.

## 6. Phrase và identity: tìm dấu vết, không suy noticed

Exactphrasebaseline so raw Unicode, casesensitive/insensitive là mode rõ. Casefold/Unicode normalization nếu dùng phải có mapping ngược raw bytes; không dùng matchoffset từ normalizedstring trực tiếp lên raw. Mode chưa có mapping kiểm được thì từ chối, không fakeoffset.

Corpusphrase nên quét raw stream hoặc sideindex mới có provenance; **không chỉ tìm trong passages** vì quote có thể cắt qua ranh giới chunk. BM25termfilter chỉ được tối ưu nếu chứng minh recall-safe theo matchingmode, còn lại fullscan/casequery có pagination vàscanprogress. Các casezero/nopassage vẫn được search nếu có trongrawuniverse; mọi kết quảcócase hash/spanbytes/raw hash. Repeatedmatches và matchcrossnewline có policy rõ, không sửatext đểtăngmatch.

Identitybaseline tìm tên/citation quan sát được bằngphrase/lexical trongnguồnhiệncó. Nếu dựng alias/regexindex, lưu exactsourceevidence vàmethodversion; không gọialias làcaseidentityverified hoặc tạo citation links từgold. Placeholderchung không resolve thànhtênán. Frenchtext giữsearchable nhưnguồn, chưa tune riênglanguage/translation.

## 7. Response và evidence delivery

Searchresult gồmquery case/input hash,session/profile/indexfp,channel coverage,rankedunique cases,fusionscore,per channelranks/scores vàboundedpassagehits. Mỗi hit cópassage ID,parenthandle,raw span/source hash,previewrefs vàopenref. CaseBM25hit không có pinpoint thì trảcase lead, không bịa passage gán từcase score.

Preview nguyên văn theoM2, cóoffset/hash; phầnellipsis/format nằm ngoàiraw. Không đánh dấupreview đã giao đủparent/context; searchlead không phải evidenceđãđọc hoặc legalverified.

Open ápcontractM2: hit12b→fullparent12 +prev/nextparagraph theo source order, không marker±1. Multi-parent/quoted/unknown/un-numbered theo refs thật; không loạiroleunknown hoặc reset ở[1]. Heading/whitespace giữrefs; context không vượtfile và không âm thầm ghép qua vùngdịch/ngữcảnhbịcontractcấm. Nhiềuhit cùngparent/context gộp rawintervals, giữmapping từhit tới deliveredspans; score không tăng theoexpandedcontext.

Agenttokenizer/budgetM4 chưa chốt: backend trảraw spans qua byte budget/paginationtrungthực, **không gọi đó làtoken-safeagentpayload**. Initialproposedbytecap64KiB/response chỉ làhosttransportcapđểreview. Nếuparentvượtcap, trảphầnchứahittrước, continuationhoàntấtparentrồineighbors, kèmrequested/delivered/pendingrefs vàclippedspan. Cursorbindcase hash/profile/requestcontextset; driftinvalidate. M4 sau này ápagenttoken budget và chỉ ghi evidenceđãgiao thực vào payloadledger.

## 8. Telemetry và vận hành

Đo riêng sessionopen/fullhash,queryrender/tokenize,RPCclient,remoteGPU,SQLite/Qdrant,metadata fetch,preview/open,serialization vàwallCLI. Lưu failures/unknown/retry vàknownquerytokens. Một search có nhiều scanrounds là1embeddingrequest nếu vectorreuse, nhưng nhiềuDBrequests phảihạchtoán. Không dùng0,208slocalpilot đểhứa fullCLI hoặcfullquality.

Sửa vấn đề tiến độ đã gặp bằngcode mới: phase+completed/total+timestamp cho search verify/batchedaudits, cachedreads vàexplicitrevalidate; receipt không thay đổiartifactrun cũ. Search bìnhthường không giữwriterlock fullingestion; full audit/revalidate chỉ đọc, concurrencycontract giới hạn nhưSection3. Log không lưucredential/.env. Không sửa Windows sleep hoặc Dockerconfig ngầm; longjob bàn giao lệnh/process bền rõràng.

## 9. Các mốc triển khai sau review

| Mốc | Đầu ra | Điều kiện qua |
|---|---|---|
| S0 |Chốt schema/profile/decisions và dependencybindings |Main phân xử AGreview; khôngcònblockerdesign |
| S1 |Readonlyfullsession,lexicalchannels,unique-casefusion |OracleBM25/fusion/exclusion/drift PASS; mocks không dịch vụ |
| S2 |Denseadapter+adaptive scan+lazycachedvectorvalidation |Exact/tieawaretests,attestation/cap/erroraccounting PASS |
| S3 |Phrase/identity+openpagination/dedup |Rawspan/crosschunk/Unicode/contextpendingtests PASS |
| S4 |CLI/telemetry vàlocalfull corpuschecks |Oldfingerprints giữnguyên; resource/latencycomponentsthựctế |
| S5 |AGreviewrealquerysearch trênfull DB |Codexchuẩnbịlệnh;user/AGchạyModalqueriesboundedscope;Mainnghiệmthu |

Các mốcS làsubstepsM3, không thayM0–M7. Fullsearchgate: tìm toànuniverse được, query caseexclusion,trảunique candidates+openđúngnguồn, khôngleakgold, reportscoverage/partial/usageđúng. Chưa chấmF1 hoặcnoticedquality ở gateengineeringnày.

## 10. Kiểm thử và tiêu chí nghiệm thu

- BM25 independentoracle giữcôngthức/analyzer,Unicode/digits/negation,ties vàexclusiontrướccap; test cảcase/passage. Fusionoracle độc lập: lặphit/sibling khôngđổicaserankcontribution, nhiềuquerykhôngcộngphiếu,limitđúng.
- Budgetfixtures:1casechiếm>1024raw hits,adaptiveexpand mớiđủ100cases;capvẫnbudget shortfall phảibáo. Dense exactreference dùng cachematrix theo streamingdotproduct rồiheap topK, không concatenate4GB. Chọnqueries/case IDs seed trước, khôngdùnggold/hardness.
- DBerrors: missing/foreign/duplicatehit,wrongpayload/vector/cosinescore,count/schemafpdrift,sourcedrift,stalecompatibility; fail trướcpaidcallnếupháthiệnđược. Simulatedreceipt/vector khôngmởkhóareal.
- Phrase/open: crosschunk,crossline,lặpmarker,sốkhôngtheothứtự,quotations,unknown,Unicodecasefoldbiếnđộdài,CRLF/BOM,largeparent,đầu/cuốifile,overlapmultihit,cursordrift. Byteoffsetrawroundtrip vàpendingcoverage trungthực.
- Local lexical/phrase/open/help noenv/noModal. End-to-end realchecks sau localPASS: đề xuất6query strings/3standaloneCLI lần đo walltime,3query vectorssoexactreferencestreaming; sốrequestcụthểphảiđượcmanifest trướcchạy, khôngtựmởrộng/retry.
- BáopeakRAM/indexsize/querylatencycảcold/warm,failurevàunknownusage. Không đặtSLAtựbịa; thu sốđothậtvàphânxửbottleneck. Slow/full DBaudit khôngmặcnhiênlàblockerquality nhưngphảighi lại.

## 11. Quyết định cần AG phản biện

1.100unique/channel,rawcap4096,output20,k60 có đủ làm baselineengineering không? Có trường hợp denominator/coverage bị báo sai?
2.Snapshot/readiness vàreturnedhitchecks có giữ được provenance với RAM/latency hợp lý? Điều kiện DBmutation nào chưa detect?
3.Dùngexactdensefull làm baseline có chấp nhận được? Nếu chậm, đo/cắt scope thế nào trước khiđềxuấtapprox?
4.Phrasecrosschunk/normalizationmapping vàidentityleads đã đủ rõ, có vô tình biến retrieval thànhlegalverification?
5.Bytepagination64KiB vàM4 token budgetdeferred có giữđủcontractparent+neighbors/pending, cầnthayđổigì?
6.Scope/timeline/acceptance có thiếu search-case/query-reading tool, cache/compat/rankinginvariant hoặc guard tránhgold leak không?

AG trả findingscóseverity,section,evidence/logic,counterexample,đềxuấtsửa vàverdict `approve`/`approve_with_changes`/`needs_revision`. Mainreviewlạitrướckhicode; khôngtựthay cácgiátrịđềxuấtthànhprofileđãchốt.
