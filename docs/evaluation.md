# Pseudo-gold evaluation workflow

This repository uses layered evaluation data for local 1cHO definition retrieval checks. The generated data is **not** a true human gold standard. It is source-backed pseudo data plus candidate mining that can be strengthened over time with `developer_corrected` or `human_reviewed` labels.

## Evaluation tiers

`data/evaluation/gold_core_questions.jsonl` is the recommended benchmark for model comparison. It contains developer-corrected or human-reviewed cases plus clean high-confidence `pseudo_generated` cases.

`data/evaluation/pseudo_gold_questions.jsonl` contains only gateable high-confidence `pseudo_generated` cases. These are still not human gold labels, but they pass strict quality gates and can be used for local regression checks.

`data/evaluation/pseudo_candidate_questions.jsonl` contains broad `pseudo_uncertain` cases for discovery and review only. Candidate rows have `needs_human_review: true`, `extraction_reason`, and `candidate_quality_warnings` where relevant. Do not use pseudo-candidate cases to compare models unless they have been manually reviewed or converted into developer-corrected/human-reviewed cases.

`data/evaluation/developer_feedback_overrides.jsonl` contains developer corrections. Developer-corrected cases are stronger than `pseudo_generated` cases and override generated cases with the same normalized question.

## Generate evaluation data

```bash
python scripts/generate_pseudo_gold.py
```

The generator reads `data/ho_definities_curated.json`, `data/ho_definities_index.jsonl`, and `data/chunks.jsonl`, then writes the split tier files under `data/evaluation/`. It only creates gateable pseudo-gold cases when source fragments, source-document evidence, clean term shape, clean dataset expectations, and clean expected snippets support the expectations. Broader medium-confidence index/chunk-derived rows are written to `pseudo_candidate_questions.jsonl` for review.

## Run evaluation

```bash
python scripts/run_evaluation.py
python scripts/run_evaluation.py --dataset gold_core
python scripts/run_evaluation.py --dataset pseudo_gold
python scripts/run_evaluation.py --dataset candidates
python scripts/run_evaluation.py --dataset all
python scripts/run_evaluation.py --include-candidates
python scripts/run_evaluation.py --case-type definition
python scripts/run_evaluation.py --limit 100
python scripts/run_evaluation.py --fail-on pseudo_generated
```

By default, the runner uses `gold_core_questions.jsonl` if it exists, otherwise `pseudo_gold_questions.jsonl`. Candidate cases are not part of the default benchmark. `--include-candidates` evaluates candidates as a separate report tier, but candidate failures do not fail the run unless explicitly requested.

The runner writes:

- `data/evaluation/evaluation_results.jsonl`
- `data/evaluation/evaluation_report.md`

By default, `developer_corrected` failures fail hard. High-confidence `pseudo_generated` failures are reported; use `--fail-on pseudo_generated` when you want them to gate a run.

## Record developer feedback

```bash
python scripts/record_feedback.py --from-json feedback_case.json
```

Or provide fields directly:

```bash
python scripts/record_feedback.py \
  --question "wat betekent wettelijk collegegeld (laag)?" \
  --wrong-answer "Uitval betekent..." \
  --corrected-answer "Ik heb geen betrouwbare definitie gevonden..." \
  --expected-main-term "" \
  --expected-curated-definition-found false \
  --reason "No source-backed definition exists in current 1cHO documentation."
```

Feedback is stored in `data/evaluation/developer_feedback_overrides.jsonl`. Cases are upserted by normalized question, so repeating the same question updates the previous correction instead of duplicating it.

## Override semantics

During gate/core evaluation, `developer_feedback_overrides.jsonl` is loaded after generated cases. A developer-corrected row with the same normalized question replaces the generated case. The `developer_corrected` label wins over `pseudo_generated`.

## Full local verification

```bash
python scripts/verify_all.py
```

`verify_all.py` runs the evaluation suite only if gate/core evaluation data exists. If the pseudo-gold file has not been generated yet, verification skips the evaluation suite instead of failing.

## Recommended workflow

1. Generate or refresh evaluation data.
2. Run the default evaluation suite against `gold_core_questions.jsonl`.
3. Inspect `pseudo_candidate_questions.jsonl` for useful candidate cases.
4. Record developer feedback for wrong or unsupported answers.
5. Re-run generation/evaluation so corrected cases override pseudo labels and gradually grow the reliable core.
