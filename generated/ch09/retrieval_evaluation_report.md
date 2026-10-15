# Chapter 9 Constructed Retrieval Evaluation

**Artifact class:** `illustrative_constructed`  
**Evaluation:** `ch09-constructed-ten-query-v1`  
**Input SHA-256:** `a025f0add42f2d3abb0d3796c9ab512b3ad2132a5448b49a5f2c455f26296c0f`  
**Generator:** `ch09-retrieval-evaluator-1.0.0`

This constructed evaluation does not certify a retriever or authorize promotion, production access, or tool execution.

## Aggregate results

Every rate displays its numerator and eligible denominator.

| Metric | Numerator / denominator = value |
|---|---:|
| Hit@3 (any adequate document served) | 5 / 7 = 0.714 |
| Recall@3 (adequate documents served / adequate documents) | 5 / 7 = 0.714 |
| Mean reciprocal rank | 4.5 / 7 = 0.643 |
| Corpus answerable coverage | 7 / 10 = 0.700 |
| Overall abstention | 4 / 10 = 0.400 |
| Correct no-answer abstention | 3 / 3 = 1.000 |
| False abstention | 1 / 7 = 0.143 |
| Non-abstaining miss | 1 / 7 = 0.143 |
| Polluted answerable queries | 2 / 7 = 0.286 |
| No-answer leak | 0 / 3 = 0.000 |
| Retired/superseded lifecycle candidates served | 0 / 2 = 0.000 |
| Wrong-scope candidates served | 0 / 1 = 0.000 |
| Access-denied candidates served | 0 / 1 = 0.000 |
| Hostile instruction-like candidates served | 0 / 1 = 0.000 |
| Served policy violations | 0 / 7 = 0.000 |

Hit@K counts a query once if any adequate document reached the responder.
Recall@K is the share of that query's adequate documents that reached the
responder, averaged over answerable queries. The two agree here only because
every answerable query in this fixture has exactly one adequate document; a
query with two adequate documents of which one is served reads Hit 1.000 and
Recall 0.500. The last five rows are measured invariants: the numerator is
re-derived from the served artifact, so a weakened eligibility filter would
show up as a non-zero count.

## Per-query inspection

| Query | Class | Answerable | Abstained | Served | First adequate rank | Hit | Recall | RR | Flags |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| q01-answerable-rank1 | answerable | true | false | 1 | 1 | 1 | 1.000 | 1.000 | — |
| q02-polluted-rank2 | answerable_polluted | true | false | 2 | 2 | 1 | 1.000 | 0.500 | pollution |
| q03-eligible-miss | miss | true | false | 1 | — | 0 | 0.000 | 0.000 | miss, pollution |
| q04-no-document | no_answer | false | true | 0 | — | — | — | — | correct no-answer |
| q05-stale-blocked-active-rank2 | stale_index | true | false | 1 | 1 | 1 | 1.000 | 1.000 | lifecycle blocked |
| q06-hostile-content-blocked | hostile_content | false | true | 0 | — | — | — | — | correct no-answer, hostile content blocked |
| q07-access-limited-no-answer | access_limited | false | true | 0 | — | — | — | — | correct no-answer, access blocked |
| q08-scope-filter-active-rank2 | scope_mismatch | true | false | 1 | 1 | 1 | 1.000 | 1.000 | scope blocked |
| q09-false-abstention | false_abstention | true | true | 0 | — | 0 | 0.000 | 0.000 | false abstention |
| q10-answerable-rank1 | answerable | true | false | 1 | 1 | 1 | 1.000 | 1.000 | — |

## Lifecycle and content boundary

Eligibility is deterministic: only `active_verified`, in-scope, access-allowed, non-hostile candidates may be served. Retired and superseded versions remain in the audit trail but not in active guidance. Denied identifiers are withheld in generated output. Instruction-like content is classified and blocked as untrusted data; this program has no network or tool-execution path.

## Limits

- The ten constructed queries demonstrate mechanics and are not a statistically sufficient promotion corpus.
- Candidate rankings are frozen fixture inputs; this evaluator does not compare lexical, semantic, hybrid, or reranked retrieval systems.
- Adequacy labels are constructed reviewer judgments, not observed production outcomes.
- Blocked hostile text is never interpreted and no denied document identifier is emitted.
