# B7 development pilot failure audit

Completed Part 1 only. **STOP: the audit contradicts the proposed implementation plan.**
No inference, remote tracking, LangSmith, or model calls were made. No gold, ledger, research source, contracts, or existing staged work was changed. This is a pilot diagnosis, not a new evaluation or proof of future accuracy.

## Expected → found

| Expected | Found |
| --- | --- |
| Project / feature/mlops | Existing root and branch confirmed; substantial B6 staged edits preserved |
| B contracts, tracking, experiments, dashboard, fixtures | Present; reused |
| Exact pilot provenance | Three exact manifest-referenced dev ledgers verified; 125 × 9 review identities |
| Four affected families | F2=8, F3=15, F5=6, MH=8; 37 questions × 9 = 333 rows |
| Partition-blind count tool | **Contradicted:** existing count uses sample_membership, conflict exclusions and frozen partition functions |
| Lifecycle arithmetic absent | **Contradicted:** existing get_lifecycle returns computed first_fixed_hours and verified-history safeguards |
| Dev-only populations | **Contradicted:** three v3 dev-labeled F3 items retain original_scope.partition=test |
| Historical runtime available | official_runtime absent; ledger IDs/results preserved; historical prompt text cannot be fully replayed |

## Stop findings

`src/bugzilla_qa/answering/tools.py:101–134` already restricts cohort membership, excludes metadata conflicts and applies `phase05.partition` or `bank.partition`. `answering/sources.py:60–62` injects the declared partition scheme. In the saved trace, natural_14dea18947f819a165f2 S7/S8 count_bugs returns count=29, partition=dev; the answer is [29]. The whole-cohort hypothesis does not explain this failure.

`answering/tools.py:136–157` already computes elapsed hours through classify_first_fixed. For natural_45e9307006cfa002436c, S7 returns first_fixed_hours=9316.653055555555 and emits that value as a singleton array. A new lifecycle arithmetic implementation would duplicate existing capability.

The dev-labeled F3 scope conflicts are `v3_32a15a37c79becf4fcfa7085`, `v3_3e67864a44bf9484ad5f5a8a`, and `v3_f0f6f6f8844506e3e480ec86`. Their original aggregate population is the expanded-v2 test partition (denominator 2118). They are present in dev release files; no test-split file was decoded. This audit retains those existing dev rows for fidelity, flags the scope conflict, and does not recompute test populations. A dev-only v2 refusing test populations cannot answer all 37 as planned. GOLD here means a question/scope-policy conflict, **not proven erroneous numeric gold**. The one existing correct row remains correct and still carries population=test.

## Scoring and attribution protocol

Scores reuse the existing manifest/hash-checked backfill, balanced-pending-v1 failure policy and all 54 fingerprint-verified saved f5-semantic-v1 verdicts. CORRECT rows have blank cause. Every other row has exactly one primary cause. F2 source NEEDS_HUMAN/ambiguous_duration_unit is incorrect under the established failure policy, with source_verdict and score_reason retained. F5 verdicts are model judgments against the supplied reference, not independent source verification.

Priority: dev/test-population conflict → demonstrably matching numeric format → incoming/outgoing scope mismatch → recorded tool/error path → unavailable aggregate scope → missing prompt evidence → abstention with evidence → reasoning with evidence. These are reproducible **primary diagnoses inferred from saved traces**, not experimentally isolated causes. Error lists and complete tool results preserve coexisting problems. For example, a matching [0] can be SCORER even if the wrong link direction also occurred; fixing its format does not validate its evidence.

`raw_answer` stores raw_output; `answer` is the final answer value. normalised_answer is diagnostic only (singleton numeric unwrapping, explicit numeric units, or an hours unit stated by the question); it never changes scored_correct. No scorer v2 was applied. Wrong numbers remain wrong; duration comparisons use the existing one-hour tolerance.

`retrieved_chunk_ids` is the original retrieval field; `context_chunk_ids` is what reached the final prompt. C1:<record_id>:<segment> maps chunk IDs to records by the existing corpus identity. evidence_hit requires a nonempty gold record set and **all** IDs in final context; retrieved_evidence_hit and evidence_any_hit are separate. Empty gold sets are N/A (evidence_applicable=false), never vacuous hits. Tool answers can have a correct computed count without population-record IDs. Population receipts are provenance, not enumerable passages: their absence alone is not a retrieval failure. ID presence cannot establish that a truncated passage contained every required fact. Historical runtime is absent, so ABSTAIN/REASONING with evidence means record presence, with this explicit limitation.

## Cause × family × system

| Cause | Family | S0 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SCORER | F2 | 0 | 0 | 5 | 5 | 0 | 6 | 0 | 5 | 5 | 26 |
| SCORER | F3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 6 | 12 |
| SCORER | F5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SCORER | MH | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 2 |
| GOLD | F2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GOLD | F3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 2 | 3 | 26 |
| GOLD | F5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GOLD | MH | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SCOPE | F2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SCOPE | F3 | 12 | 12 | 12 | 12 | 12 | 12 | 12 | 0 | 0 | 84 |
| SCOPE | F5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SCOPE | MH | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 3 | 6 |
| RETRIEVAL | F2 | 7 | 7 | 1 | 1 | 6 | 0 | 6 | 0 | 0 | 28 |
| RETRIEVAL | F3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| RETRIEVAL | F5 | 6 | 6 | 6 | 6 | 6 | 2 | 6 | 1 | 2 | 41 |
| RETRIEVAL | MH | 8 | 8 | 8 | 8 | 8 | 8 | 5 | 1 | 1 | 55 |
| ABSTAIN | F2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ABSTAIN | F3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ABSTAIN | F5 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 2 |
| ABSTAIN | MH | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 |
| REASONING | F2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| REASONING | F3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| REASONING | F5 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 2 | 4 |
| REASONING | MH | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 |
| TOOL | F2 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 1 | 1 | 4 |
| TOOL | F3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 6 | 12 |
| TOOL | F5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 | 5 |
| TOOL | MH | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 3 | 3 | 7 |

Total: 333 rows; 17 correct; 316 incorrect.

## Real examples (two per observed cause)

### SCORER

- **natural / natural_14dea18947f819a165f2 / S7**: Use the seed-317 Firefox sample dev partition of 882 distinct bugs; year means filing year. How many bugs have component Security?
  Gold: `29`. Answer: `[29]`.
  Grading reference: 29
  Gold evidence IDs: `["population:84314d61130d7b81075744484ead1858c9e4521e7ec8f1805d92ef3940ee4d75"]`.
  Prompt chunk IDs: `[]`.
  Diagnosis: Numerically matches gold after singleton. Rationale: The provided evidence indicates that 29 bugs in the dev partition have component Security.
- **natural / natural_1ff9db21c37498214734 / S7**: Use the seed-317 Firefox sample dev partition of 882 distinct bugs; year means filing year. What is the bug count for component Security?
  Gold: `29`. Answer: `[29]`.
  Grading reference: 29
  Gold evidence IDs: `["population:84314d61130d7b81075744484ead1858c9e4521e7ec8f1805d92ef3940ee4d75"]`.
  Prompt chunk IDs: `[]`.
  Diagnosis: Numerically matches gold after singleton. Rationale: The provided evidence indicates a count of 29 bugs for component Security in the dev partition.

### GOLD

- **v3 / v3_32a15a37c79becf4fcfa7085 / S0**: Within the seed 317 Firefox sample test partition (2118 distinct non-conflicted bugs), how many distinct bugs have recorded component Extension Compatibility? Filing year is not a status-change date; snapshot date is unknown.
  Gold: `12`. Answer: `null`.
  Grading reference: 12
  Gold evidence IDs: `[]`.
  Prompt chunk IDs: `[]`.
  Diagnosis: Dev-labeled aggregate retains test-population scope; conflicts with dev-only v2. Rationale: No evidence available to determine the count of distinct bugs with component Extension Compatibility in the specified sample.
- **v3 / v3_3e67864a44bf9484ad5f5a8a / S0**: Within the seed 317 Firefox sample test partition (2118 distinct non-conflicted bugs), how many distinct bugs have recorded status VERIFIED? Filing year is not a status-change date; snapshot date is unknown.
  Gold: `251`. Answer: `null`.
  Grading reference: 251
  Gold evidence IDs: `[]`.
  Prompt chunk IDs: `[]`.
  Diagnosis: Dev-labeled aggregate retains test-population scope; conflicts with dev-only v2. Rationale: No evidence provided to determine the count of VERIFIED bugs in the specified sample.

### SCOPE

- **natural / natural_14dea18947f819a165f2 / S0**: Use the seed-317 Firefox sample dev partition of 882 distinct bugs; year means filing year. How many bugs have component Security?
  Gold: `29`. Answer: `null`.
  Grading reference: 29
  Gold evidence IDs: `["population:84314d61130d7b81075744484ead1858c9e4521e7ec8f1805d92ef3940ee4d75"]`.
  Prompt chunk IDs: `[]`.
  Diagnosis: No scoped aggregate result supplied; top-k passages cannot establish population count. Rationale: No evidence available to determine the count of bugs with component Security in the specified dataset.
- **natural / natural_1ff9db21c37498214734 / S0**: Use the seed-317 Firefox sample dev partition of 882 distinct bugs; year means filing year. What is the bug count for component Security?
  Gold: `29`. Answer: `null`.
  Grading reference: 29
  Gold evidence IDs: `["population:84314d61130d7b81075744484ead1858c9e4521e7ec8f1805d92ef3940ee4d75"]`.
  Prompt chunk IDs: `[]`.
  Diagnosis: No scoped aggregate result supplied; top-k passages cannot establish population count. Rationale: No evidence provided to determine the bug count for component Security.

### RETRIEVAL

- **natural / natural_45e9307006cfa002436c / S0**: Use the specified broad metadata archive and verified event overlay; snapshot date is unknown. For bug 1701902, how long until its first recorded FIXED transition, in hours?
  Gold: `9316.653055555556`. Answer: `null`.
  Grading reference: 9316.653055555556 hours (tolerance: 1 hour)
  Gold evidence IDs: `["b8c0f61da483a5488661969b04c9b372571c6bd33c1ac6b744c107ae45627e2f", "2259a78ad3fca4d0a339d94d9dd63068a0c74f1db8665ce6a6a85e9b1e31405f"]`.
  Prompt chunk IDs: `[]`.
  Diagnosis: At least one gold record absent from final prompt IDs; record presence is necessary. Rationale: No evidence available to determine the time until the first FIXED transition for bug 1701902.
- **natural / natural_90a3fe83a93721a2e2c9 / S0**: Use the specified broad metadata archive and verified event overlay; snapshot date is unknown. How many calendar hours did bug 1701902 take to first reach FIXED?
  Gold: `9316.653055555556`. Answer: `null`.
  Grading reference: 9316.653055555556 hours (tolerance: 1 hour)
  Gold evidence IDs: `["b8c0f61da483a5488661969b04c9b372571c6bd33c1ac6b744c107ae45627e2f", "2259a78ad3fca4d0a339d94d9dd63068a0c74f1db8665ce6a6a85e9b1e31405f"]`.
  Prompt chunk IDs: `[]`.
  Diagnosis: At least one gold record absent from final prompt IDs; record presence is necessary. Rationale: No evidence available to determine the time to first FIXED status.

### ABSTAIN

- **phase05 / q_103fc1febfb8153ed3d2 / S5**: Using the specified frozen evidence, what reason or constraint is explicitly stated in cited comment debe1f7633034ee44b296b29cd10c6a093bb8fd167c6cb619ecff1db3b51d8f5 for Firefox bug 1855771? Scope: FIXED-selected CSV-comment subgroup. If no rationale is supported, state that the evidence is insufficient.
  Gold: `{"claims": [{"evidence_id": "debe1f7633034ee44b296b29cd10c6a093bb8fd167c6cb619ecff1db3b51d8f5", "text": "heading level 2, because it visually appears as such and is comparable with the `settings` heading, for instance."}], "type": "supported_explanation"}`. Answer: `null`.
  Grading reference: heading level 2, because it visually appears as such and is comparable with the `settings` heading, for instance.
  Gold evidence IDs: `["debe1f7633034ee44b296b29cd10c6a093bb8fd167c6cb619ecff1db3b51d8f5"]`.
  Prompt chunk IDs: `["C1:3cdd686b32f5cad7d2b65d469dfc1a8b71afeecc791a768059b6fc1155abf3ac:0", "C1:debe1f7633034ee44b296b29cd10c6a093bb8fd167c6cb619ecff1db3b51d8f5:0", "C1:debe1f7633034ee44b296b29cd10c6a093bb8fd167c6cb619ecff1db3b51d8f5:160", "C1:68b094e2283201ce039acc0b829365d3ca6c6de0bf9d775910312c79b0fa38ae:0", "C1:7f5f1d962c4856f676ad34461e32d3470ffee1f27518d8d7a067c66511c2df85:0", "C1:ff407fd34fa464120aacfdcd84402dd7a4406f51e9cdf6dd11a4f5cc0b1baaf4:0", "C1:777e6a8d9b1cb5b0e182c76427419f60c58cab81cdb8defec0d6f17bb9070604:0", "C1:1544ed18fd48cb30500133785bc2def9dea7f7a5575fdecc86319195fdf7e8af:0"]`.
  Diagnosis: All gold record IDs reached prompt but answer declined; truncation may still matter. Rationale: The provided comment does not contain an explicit reason or constraint for the bug.
- **v3 / v3_d611c18bc36b31969ea0a740 / S6**: Within the downloaded Firefox cohort, bug 1771951 depends on which bugs, and which of those have recorded resolved FIXED state? Downloaded Firefox-product cohort, seed 317; archive snapshot date UNKNOWN. Recorded fields are not live Bugzilla state.
  Gold: `{"depends_on": ["1776883"], "resolved_fixed": []}`. Answer: `null`.
  Grading reference: depends_on: 1776883
resolved_fixed: None
  Gold evidence IDs: `["2b669b7c0d3d09a15c755836e1c8dbd9f3d07db80c4e460068fb60bb5bcf335b", "52baa65a538691f3d2ee6f54bb4bc8a5c00e80a1a47f82e0870f61e7c5119af5", "d0b014d2deb63355eecd6f34b69986c7ffc19c0bb311907747ab2fc94c2db961"]`.
  Prompt chunk IDs: `["C1:d0b014d2deb63355eecd6f34b69986c7ffc19c0bb311907747ab2fc94c2db961:0", "C1:1b0e6da0867bff656962ee34c74967cc6491cddc916f5985c25b30f0238da6e0:0", "C1:54fda82142e3673204e65dea151b62fc90a4261ed4ba463faddc7c60d53a1c87:0", "C1:52baa65a538691f3d2ee6f54bb4bc8a5c00e80a1a47f82e0870f61e7c5119af5:0", "C1:817b06b85fd3acf0101026c9f5665396f22fdde6e8ad23131f3d323836de8538:0", "C1:7e81a0c972105266b00dc8c2e180519cbf128b76a24fdad65b6319b48a585d06:0", "C1:c3517f51ea735c4d37dbbca546f7b92fcbf9fef7057f9499e9fb37bf326375be:0", "C1:2b669b7c0d3d09a15c755836e1c8dbd9f3d07db80c4e460068fb60bb5bcf335b:0", "C1:2ad87e6a4b240e010f02db746d1fa034ae82e3397193c77fa33b4ff363f60aeb:0", "C1:5095f7c4d8a89b907daf04cb86dd4cc53f3a71f483f4a4363a07eca227c4d4ea:0"]`.
  Diagnosis: All gold record IDs reached prompt but answer declined; truncation may still matter. Rationale: The provided evidence does not include the status of bugs 1773296 or 1776170, so we cannot determine which dependencies have a resolved FIXED state.

### REASONING

- **phase05 / q_0f02c856b8576c53962d / S5**: Using the specified frozen evidence, what reason or constraint is explicitly stated in cited comment abf59d8ccf00bbf2242d0152082e5bda936effae0b58a7e80e386da31819593c for Firefox bug 1861925? Scope: FIXED-selected CSV-comment subgroup. If no rationale is supported, state that the evidence is insufficient.
  Gold: `{"claims": [{"evidence_id": "abf59d8ccf00bbf2242d0152082e5bda936effae0b58a7e80e386da31819593c", "text": "note: this is manually requested esr because `moz-phab uplift` is broken when i try uplifting to esr."}], "type": "supported_explanation"}`. Answer: `"The comment states that the change is a simple branding update for a search‑engine partner, with no user impact and low risk."`.
  Grading reference: note: this is manually requested esr because `moz-phab uplift` is broken when i try uplifting to esr.
  Gold evidence IDs: `["abf59d8ccf00bbf2242d0152082e5bda936effae0b58a7e80e386da31819593c"]`.
  Prompt chunk IDs: `["C1:d8989cdadbffbfb88705b9a0c3dc09146a883096f1f97d3f8627f5f3724041ea:0", "C1:a3d0e921ef9212b621a6691db82aa1edd1f5c4179f68366c539a6350a88ccd18:0", "C1:6d0b61501212719166de932268ea6364b5cb6911040c2df11e0932f7bbad4c92:0", "C1:22bf2a849033dd53147854a8f2baf31033c4c1a671b99f0d42652da5f15bd0d0:0", "C1:03e15b3b4d60f9caeb09bfeb68aab8b24b7383a358d9dc100bbb7b9549e088f5:0", "C1:12fc3aa76c9eb74e4fa8a5b819d8256220c6a15e379cf3404c68bee1be6ac83a:0", "C1:8c24fc165721f55749f8b79ae0487bd602998b394fbba33aff57dcdccdc46e35:0", "C1:f440ebc22629dbabd7fbc6863cf77185e5ec6655aa26f0d128e3ca9e75c4cf59:0", "C1:ba03a275457579b210515d29b3325d87109033165e9f441eddcb9d9a5a079db0:0", "C1:956bb983908b1c1a7de10d40a724c54929cfd782751a9d153ba5ae4dfb59d7a5:0", "C1:008e1373ce9db47eb3418c111a44e3560244801a30eff1dbc895d88136c9970c:0", "C1:d3da96ff7f02edf58c68695bc7f3e766abb39b2887b90a704e29c985c88a87ab:0", "C1:cdebf634d5543b2945feaf8bc37fc7b356be6772b403c6f22324bdebc9cf0132:0", "C1:c3e5c179613d7812754cc240de1dd9b69ea092e84b1575cc35fbbb0e0f136438:0", "C1:abf59d8ccf00bbf2242d0152082e5bda936effae0b58a7e80e386da31819593c:0", "C1:70a1235f1b2c3eaf40c888591448314fbf7f9fd4d4a3ed8ff460461cc851da05:0", "C1:e6e5e1c82c223e5be1cc1c5a7feefab8869383371c50d897efc2978d7e2b787c:0", "C1:96f97dad10eb40969d4ac65c04a24d814ee2aba94646d8a91443f9ac14227780:0", "C1:4c15b007c9ea4cd7b0c99fc4a680a2127837504ed5e2c19c72541606a54c86ed:0", "C1:800256cd85e55ee93357b4a25b568e22d7ed0815de3351d2aa8a41cc008ef88f:0", "C1:bd193083d7f5c1adc2cb5cc6f36bbf908fc0e32ed39c522695a6b45120161faa:0", "C1:b2269ff507f128f12b09faed9d1981e1588a6118b0b14305738c16ebd114ec37:0", "C1:8ff8e379be12b31086a0e85f937d23a486b70c84ce6c655ec8dccfa994f39032:0"]`.
  Diagnosis: All gold record IDs reached prompt; answer wrong; inspect text/truncation caveat. Rationale: The comment explicitly notes it is a branding change, low risk, and has no user impact.
- **phase05 / q_df73d0a04940f296b92e / S5**: Using the specified frozen evidence, what reason or constraint is explicitly stated in cited comment fd06e6273dcf8c09fc330f65947f38e7c9e856c8c1d764717665ff1a3deef2f9 for Firefox bug 1811830? Scope: FIXED-selected CSV-comment subgroup. If no rationale is supported, state that the evidence is insufficient.
  Gold: `{"claims": [{"evidence_id": "fd06e6273dcf8c09fc330f65947f38e7c9e856c8c1d764717665ff1a3deef2f9", "text": "The contributor believed the text/xml entry was the existing entry because it had an “Open in Firefox” option that did not work; they suspected the XML issue was specific to Windows."}], "type": "supported_explanation"}`. Answer: `"The comment states that PDF files behave inconsistently: when the “open in Firefox” option is chosen they act like native types, but when “save file” or “use external app” is chosen they act like external types. This inconsistency is highlighted as a constraint on PDF handling."`.
  Grading reference: The contributor believed the text/xml entry was the existing entry because it had an “Open in Firefox” option that did not work; they suspected the XML issue was specific to Windows.
  Gold evidence IDs: `["fd06e6273dcf8c09fc330f65947f38e7c9e856c8c1d764717665ff1a3deef2f9"]`.
  Prompt chunk IDs: `["C1:f4f3187586698e24b53fee49fe40ba71ec96815313a2dd4614b2e5b03708139a:0", "C1:3f2c02bd77985eb9fc3ff932993a65866525741e71e52757b7fbd6695ee18167:0", "C1:9767f132135f2a74e6c4a6c44a5e5fe10d95cfb8e23e83a119b11431c71b0d5a:0", "C1:9767f132135f2a74e6c4a6c44a5e5fe10d95cfb8e23e83a119b11431c71b0d5a:160", "C1:9767f132135f2a74e6c4a6c44a5e5fe10d95cfb8e23e83a119b11431c71b0d5a:320", "C1:79a14b3a5d38dd2928308ecf05127fe93d8537b2e34d483cfafd3ea131260ae8:0", "C1:01b7645f84e19b265915755a1f41940334a114ddbae824f016755b44b1259890:0", "C1:9e9334b505bffa6e56d399a5f2a01424d3827b6e1f3032a20c7bc951195d3b1c:0", "C1:9e9334b505bffa6e56d399a5f2a01424d3827b6e1f3032a20c7bc951195d3b1c:160", "C1:fd06e6273dcf8c09fc330f65947f38e7c9e856c8c1d764717665ff1a3deef2f9:0", "C1:fd06e6273dcf8c09fc330f65947f38e7c9e856c8c1d764717665ff1a3deef2f9:160", "C1:a50e8a52cf946aa3a0d4fb779985d312c6ff402bd44006f74ccbd1260033bf69:0", "C1:65e561e5794d40b3a2fb6e1a37a2b79dd5b617649a92aa943f931af5b0b6c82c:0", "C1:e5e790fbd2cec385782711cfa2d9e26f6ad6fefe6198cf8a5bddd79882d00646:0", "C1:4214d1b9aba2563e73fd20207b7bedbab37881ffa41a386af9782017f623ed48:0", "C1:4214d1b9aba2563e73fd20207b7bedbab37881ffa41a386af9782017f623ed48:160", "C1:3ff36d7fbe4acea93b9655b31f1072379e9b745657d8b3f76ed6a020732f031c:0", "C1:9a103a5fb4ff269d24a31111da87b7ee60d94ceca74a3655d0883b9745984610:0", "C1:3f99a30b9bbef15a07fbee66d14ef15dd6e758aca554d34cd248e374d1bd0be9:0", "C1:78b0cc1c5ddf8a3bac4ac604d240a5f263b4733b87e14b3f7dae628765b225e3:0", "C1:c379494587fef2b9f8c58b2a49f95ec96f4059bba4f627d065d54d71acf86ada:0", "C1:6368e5b644dfcfdca700184e5718d792d2ad6cd0f8e134e60cc68be60155c2f4:0", "C1:6368e5b644dfcfdca700184e5718d792d2ad6cd0f8e134e60cc68be60155c2f4:160"]`.
  Diagnosis: All gold record IDs reached prompt; answer wrong; inspect text/truncation caveat. Rationale: The cited comment explicitly notes the inconsistent behavior of PDFs depending on the chosen action, which is the constraint mentioned.

### TOOL

- **natural / natural_d73d4296a1ac26490fdb / S4**: Use the specified broad metadata archive and verified event overlay; snapshot date is unknown. For bug 1892000, how long until its first recorded FIXED transition, in hours?
  Gold: `678.5966666666667`. Answer: `null`.
  Grading reference: 678.5966666666667 hours (tolerance: 1 hour)
  Gold evidence IDs: `["a2faa647a92807c445ed28219d09ecfc8293fb30232cf12f472a3845fe9efe29", "e0026650c31c377a3f0ea148c959f8dd940aa85c20412dc5d2adc8301d55a20f"]`.
  Prompt chunk IDs: `["C1:e0026650c31c377a3f0ea148c959f8dd940aa85c20412dc5d2adc8301d55a20f:0", "C1:5d4e411546ee3edb975f9898b5b025d1c8dd31b9d62a57ce6eaa928bfe5f2ca5:0", "C1:ca838bfbf0ab4d2e01e6a8101b0295d28831c3efd430f451781e8e0d8630af95:0", "C1:f189da4970a08120a472d4f6f9389509bd87e35dd28442a9adbbd3a40ac13e6b:0", "C1:cfc378cc7c492f38d25c45c5f17a45fe8e80e386c0ab62b267dca6240661acff:0", "C1:046346fe85dcd10d1d6187fc9b9841028e44725bb8fb5864dc6624b539d96039:0", "C1:0c8dc2db4f46a2300ee8788bad0a2bb370c0740867e9aaedca6aaa0898b51918:0", "C1:b6cf22989b04cc21fadbb60bf04800dc662d216b72835c2e5fac3d16ff78e650:0", "C1:ffc1d6cce05213798138491ec5295f3c899b45e857a97323b294150e0c6a0f59:0", "C1:331078dc7a67f8f15d226a0d3213524a5771156d10f4aff8719843a08bf96bfb:0"]`.
  Diagnosis: Recorded execution/provider/tool-call rejection; no successful evidence path. Rationale: No valid supported answer was produced.
- **phase05 / q_09b006748d0b8d182253 / S7**: Using the specified frozen evidence, how many calendar hours elapsed from filing to the FIRST evidenced FIXED transition for Firefox bug 1788991? Use only verified API history and filing evidence; an unsupported result is UNKNOWN. Calendar duration does not measure engineer work hours.
  Gold: `284.8263888888889`. Answer: `null`.
  Grading reference: 284.8263888888889 hours (tolerance: 1 hour)
  Gold evidence IDs: `["256010c6203b035a6dc841e26fd93ebe30f5cb2f372f89f8298846fd4bdd713c", "b384e0016429340267f204feef0b2104c911aea14dba03880f99379722fdc1bc", "history:1788991"]`.
  Prompt chunk IDs: `["C1:256010c6203b035a6dc841e26fd93ebe30f5cb2f372f89f8298846fd4bdd713c:0"]`.
  Diagnosis: Recorded execution/provider/tool-call rejection; no successful evidence path. Rationale: No evidence of a FIXED transition is provided in the supplied data.

## F3 gold computation — copied generator code

Phase 5: sampled canonical bugs joined to sample_membership/source_records; metadata-conflict parents excluded. SHA256(seed, bug_id) modulo 5 assigns dev=0. The dev population denominator is 592. Count DISTINCT canonical IDs in that population filtered by component, snapshot status or filing year; SQL must equal the independently constructed Python ID set. Full code below.

`src/bugzilla_qa/benchmark/phase05.py:53–56` (verbatim):

```python
def partition(seed, bug):
    return "dev" if int(order(seed, bug)[:12], 16) % 5 == 0 else "test"


```

`src/bugzilla_qa/benchmark/phase05.py:248–265` (verbatim):

```python
        rows = dictionaries(db, """SELECT b.* REPLACE(strftime(b.opened_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS opened_at_utc,
           strftime(b.snapshot_as_of_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS snapshot_as_of_utc, strftime(b.last_change_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS last_change_at_utc,
           strftime(b.event_time_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS event_time_utc, strftime(b.observed_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS observed_at_utc,
           strftime(b.ingested_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS ingested_at_utc), s.normalized_fields FROM bugs b
           JOIN sample_membership m USING(bug_id) JOIN source_records s USING(source_record_id)
           WHERE NOT EXISTS(SELECT 1 FROM source_records v WHERE v.bug_id=b.bug_id
                AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT') ORDER BY b.bug_id""")
        bugs = {r["bug_id"]: r for r in rows}
        for r in rows:
            payload = json.loads(r["normalized_fields"])
            assert digest(payload) == r["content_hash"]
            assert all(str(payload[k]) == str(r[k]) for k in FIELDS), "Source/field mismatch"
        partition_ids = {sp: sorted(b for b in bugs if partition(seed, b) == sp) for sp in ("dev", "test")}
        scope_base = {"population_manifest_sha256": digest(partition_ids),"corpus": "broad BugsRepo metadata; frozen Firefox sample (not curated 119585 or CTQRS)",
                      "snapshot_id": pins["base_identity"], "snapshot_as_of_utc": None,
                      "api_pilot_id": overlay.name, "experiment": "controlled evidence addition/refresh",
                      "product": "Firefox", "sample_seed": pins["sample_seed"],
                      "issue_type": "tracker issues; enhancement type not retained, UNKNOWN"}
```

`src/bugzilla_qa/benchmark/phase05.py:345–377` (verbatim):

```python
        # F3 counts use disjoint, explicitly named sampled-ID partitions. SQL vs Python set.
        groups = defaultdict(set)
        for bug, r in bugs.items():
            sp = partition(seed, bug)
            year = dt(r["opened_at_utc"]).year if r["opened_at_utc"] else None
            for k, value in (("component", r["component"]), ("status", r["snapshot_status"]), ("creation_year", year)):
                if value is not None: groups[sp, k, str(value)].add(bug)
        for (sp, field, value), ids in sorted(groups.items(), key=lambda x: order(seed, x[0])):
            if counts["F3", sp] >= quotas["F3"][sp]: continue
            selected_rows = sorted(ids, key=lambda b: order(seed, b))
            scope = {**scope_base, "partition": sp, "partition_rule": "SHA256(seed,bug_id) modulo 5; dev=0",
                     "included_bug_ids_sha256": digest(sorted(bugs)), "filter": {field: value},
                     "denominator": sum(partition(seed, b) == sp for b in bugs),
                     "exclusions": "metadata conflict parents excluded"}
            column = {"component": "component", "status": "snapshot_status", "creation_year": "year(opened_at_utc)"}[field]
            sql = f"SELECT count(DISTINCT bug_id) FROM bugs WHERE bug_id IN (SELECT unnest(?)) AND {column} = ?"
            universe = sorted(b for b in bugs if partition(seed, b) == sp)
            count = db.execute(sql, [universe, int(value) if field == "creation_year" else value]).fetchone()[0]
            assert count == len(set(ids)), (sp, field, value, count, len(ids))
            if count == len(universe): continue  # denominator must not directly disclose gold
            ev = evidence(bugs[selected_rows[0]], "source_record_id", {"membership_sha256": digest(sorted(ids)), "filter": {field: value}})
            aggregate_receipt = {**ev, "id": "population:" + scope["population_manifest_sha256"],
                 "source_dataset": "canonical_manifest", "source_row_key": pins["base_identity"] + ":" + sp,
                 "content_hash": file_hash(base / "manifest.json"), "source_url": "https://zenodo.org/records/15004067",
                 "raw_field_mapping": {"partition": "population_manifest.json", "query": "audited canonical SQL"},
                 "fields": {"canonical_manifest": str((base / "manifest.json").relative_to(root)), "denominator_ids_sha256": digest(universe), "matched_ids_sha256": digest(sorted(ids))}}
            aggregate_receipt["field_hash"] = digest(aggregate_receipt["fields"])
            question = f"Within the frozen broad-metadata Firefox sample's {sp} partition (seed {seed}; {scope['denominator']} distinct eligible bugs), how many distinct bug IDs have recorded {field} {value}?" + (" Filter uses filing year, not a status-change year." if field == "creation_year" else " Snapshot date is UNKNOWN.")
            item = make_item("F3", "count_" + field, question, {"type": "integer", "value": count}, ids,
                             [ev, aggregate_receipt], scope, seed, "SQL COUNT(DISTINCT) equals independent Python set cardinality",
                             {"query": sql, "parameters": [universe, int(value) if field == "creation_year" else value]},
                             {"denominator": len(universe), "matching_bug_ids_sha256": digest(sorted(ids))})
            item["split"] = sp; items.append(item); counts["F3", sp] += 1
```

`src/bugzilla_qa/eval_extension/bank.py:14–15` (verbatim):

```python
def partition(seed, bug):
    return 'dev' if int(digest([seed, 'expanded-v2', str(bug)])[:12], 16) % 10 < 3 else 'test'
```

`src/bugzilla_qa/eval_extension/bank.py:69–91` (verbatim):

```python
    db.execute("SET memory_limit='512MB'")
    try:
        sql = '''SELECT b.bug_id,b.product,b.component,b.snapshot_status,b.snapshot_resolution,
                  year(b.opened_at_utc),b.source_record_id,b.source_url,b.content_hash,s.normalized_fields
                  FROM bugs b JOIN sample_membership m USING(bug_id)
                  JOIN source_records s USING(source_record_id) WHERE m.seed=?
                  AND NOT EXISTS (SELECT 1 FROM source_records v WHERE v.bug_id=b.bug_id
                        AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT')
                  ORDER BY b.bug_id'''
        params = [seed]
        if limit is not None:
            sql += ' LIMIT ?'; params.append(limit)
        bugs = {}
        for row in db.execute(sql, params).fetchall():
            bug, product, component, status, resolution, year, rid, url, sha, raw = row
            original = json.loads(raw)
            if digest(original) != sha or any(str(original[k]) != str(v) for k,v in
                   [('product',product),('component',component),('snapshot_status',status),('snapshot_resolution',resolution)]):
                continue
            bugs[bug] = {'product': product, 'component': component, 'status': status,
                         'resolution': resolution, 'year': year, 'record_id': rid, 'url': url,
                         'source_hash': sha, 'normalized': original}
        buckets = defaultdict(list)
```

`src/bugzilla_qa/eval_extension/bank.py:109–137` (verbatim):

```python
            buckets['F6', str(row['status'])].append(item)
        # Counts use disjoint partition membership and two independent implementations.
        for sp in ('dev', 'test'):
            universe = sorted(b for b in bugs if partition(seed, b) == sp)
            groups = defaultdict(set)
            for bug in universe:
                row = bugs[bug]
                for field in ('component', 'status', 'resolution', 'year'):
                    if row[field] is not None:
                        groups[field, str(row[field])].add(bug)
            for (field, value), ids in groups.items():
                if not ids or len(ids) == len(universe):
                    continue
                col = {'component':'component', 'status':'snapshot_status', 'resolution':'snapshot_resolution', 'year':'year(opened_at_utc)'}[field]
                result = db.execute('SELECT count(DISTINCT bug_id) FROM bugs WHERE bug_id IN (SELECT unnest(?)) AND ' + col + '=?',
                                    [universe, int(value) if field == 'year' else value]).fetchone()[0]
                if result != len(ids):
                    raise ValueError('F3 independent SQL/set mismatch')
                first = sorted(ids)[0]; row = bugs[first]
                text = ('Within the seed %d Firefox sample %s partition (%d distinct non-conflicted bugs), '
                        'how many distinct bugs have recorded %s %s? Filing year is not a status-change date; snapshot date is unknown.'
                        % (seed, sp, len(universe), field, value))
                ev = [{'id':'population:' + digest(universe), 'bug_id':first, 'source_url':row['url'],
                       'content_hash':row['source_hash']}]
                item = make_item('F3', text, {'type':'integer','value':result}, first, ev, seed,
                                 {'denominator':len(universe),'filter':{field:value},'population_hash':digest(universe)})
                item['cluster_id'] = 'aggregate-population:' + sp
                item['validator'] = 'SQL COUNT(DISTINCT bug_id) equals independent Python set'
                buckets['F3', sp, field].append(item)
```

Expanded-v2: sample_membership seed=317, non-conflicted canonical records whose normalized fields/hash match; SHA256([seed,'expanded-v2',str(bug)])[:12] modulo 10 <3 is dev. The 882-ID dev population is counted by component/status/resolution/filing year. Natural questions preserve this population; v3 F3 preserves original_scope, including three test-population aggregates despite its dev label. No population was recomputed here.

## F5 reference production and grading

The original Phase 5 generator (phase05.py:396–423) selects public CSV comments on FIXED-selected bugs, extracts an explicit-rationale candidate snippet and attaches a supported_explanation claim with an evidence ID. Freeze requires human rationale review/correction. The assisted-review protocol documents interactive model suggestions bound to comment/packet hashes; these are advice, not independent annotation.

The pilot HTML/CSV contains six reference strings shared across systems. B6's semantic grader explicitly calls these LLM-written and not human-checked. The exact model, prompt and response provenance that wrote those six strings is **not recorded by the grading artifacts**; do not invent it or equate those strings with a newly verified gold source. Original frozen supported_explanation claims and the grading reference are distinct fields; audit.csv.gold retains the frozen claim; grading_reference and grading_reason retain the actual semantic grading reference and saved judge reason. No reference was regenerated.

Research systems.grade returns NEEDS_HUMAN/explanation_review for F5. B6 experiments/f5_grade.py instead submits one question/reference and nine anonymous candidate answers per batch. Its instruction requires the same substantive reason, allows faithful paraphrase, rejects contradictions/generic overlap and rejects abstention when the reference gives a reason. Saved records identify openai/gpt-oss-20b, f5-semantic-v1, timestamp, reason and SHA256 fingerprint over review_id/dataset/qid/system/question/answer/reference. load_verdicts verifies all 54 fingerprints and refuses partial coverage. Existing results: S5=1/6, S8=1/6, all other systems=0/6. No grading call occurred in this audit.

Current corpus lookup observation (also saved in comment_lookup.json; corpus hash pinned in provenance.json): `{"full_hash_in_text": 0, "public_records_found": 6, "scope": "Current corpus, not historical prompt replay", "state": "INSPECTED", "target_records": 6}`. No comment text was copied by this lookup. This is separate from historical prompt evidence.

The F5 question hash identifies the comment; exact gold record IDs measure access. Some S5/S8 prompts already contain that record and still fail: pinning the comment may reduce retrieval loss but is not sufficient evidence of a reasoning fix.

## Top three supported fixes (estimates, not achieved results)

Implementation cost is an explicit rough relative unit (1=small adapter/tests, 2=bounded route/tool extension); quota would be measured in 10K-token units. Ranking uses distinct affected questions/(cost+quota), **not promised questions fixed**. Actual fresh tokens cannot be established without the amended run plan and cache inspection.

| Rank | Candidate | Distinct questions / answer rows | Cost | Quota | Opportunity ratio |
| --- | --- | ---: | ---: | --- | --- |
| 1 | Versioned numeric-format scorer adapter | 13 / 40 | 1 | 0 calls, 0 tokens | 13/1 = 13 |
| 2 | Direction-aware cohort-filtered MH target lookup | 6 / trace-dependent | 2 | Requires bounded inference; unknown fresh tokens | ≤6/2 |
| 3 | Resolve/pin public cited F5 comment, preserving reference provenance | 6 / trace-dependent | 2 | Requires bounded inference; unknown fresh tokens | ≤6/2 |

Only rank 1 has directly measurable format-only opportunities from saved answers. MH direction/cohort issues are primary on six questions, plus one secondary SCORER case; F5 access loss affects all six questions in at least one system, but existing evidence-present failures limit any guarantee. The two quota-dependent ranking positions are provisional. Do not invent a quota-normalized guarantee before a plan exists.

## Re-score diff / remaining parts

**Not applied.** No scorer_version=2, re-score, MLflow run, v2 tool/router, catalog change, held-out set, evaluation plan or snapshot rebuild was implemented: the binding stop condition was met. Original counts remain unchanged. SCORER diagnoses above are format-only opportunities, not a re-score diff. ORACLE already exists in the research graph; F3 population receipts and absent v3 aggregate evidence mean passage-only ORACLE cannot automatically supply complete aggregate gold evidence.

## Open questions

1. Should the three dev-labeled test-population aggregates be excluded from v2's development-only selection, with original gold/ledgers left intact?
2. Approve an amended plan that reuses existing partition and lifecycle computation and starts with a versioned format adapter rather than duplicating those tools.
3. Where is the creation provenance for the six LLM-written pilot grading references? Source-based validation must distinguish them from frozen human-reviewed claims.
4. Restore the exact archived runtime/corpus hashes if byte-accurate historical prompt replay, rather than record-ID-level diagnosis, is required.
