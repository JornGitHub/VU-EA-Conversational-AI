# Pseudo-gold evaluation workflow

This repository uses a **pseudo-gold** evaluation dataset for broad local coverage of 1cHO definition retrieval. It is not a true human gold standard. Cases are generated from existing source-backed curated definitions and can later be strengthened with `developer_corrected` or `human_reviewed` labels.

## Generate pseudo-gold cases

```bash
python scripts/generate_pseudo_gold.py
```

The generator reads `data/ho_definities_curated.json`, `data/ho_definities_index.jsonl`, and `data/chunks.jsonl`, then writes `data/evaluation/pseudo_gold_questions.jsonl`. It only creates cases when source fragments support the expectations.

## Run evaluation

```bash
python scripts/run_evaluation.py
python scripts/run_evaluation.py --case-type definition
python scripts/run_evaluation.py --limit 100
python scripts/run_evaluation.py --fail-on pseudo_generated
```

The runner calls `answer_definition_question_json(question)` and writes:

- `data/evaluation/evaluation_results.jsonl`
- `data/evaluation/evaluation_report.md`

By default, `developer_corrected` failures fail hard. Pseudo-generated failures are reported; use `--fail-on pseudo_generated` when you want high-confidence pseudo cases to gate a run.

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

During evaluation, `developer_feedback_overrides.jsonl` is loaded after `pseudo_gold_questions.jsonl`. A developer-corrected row with the same normalized question replaces the pseudo-generated case. The `developer_corrected` label wins over `pseudo_generated`.

## Full local verification

```bash
python scripts/verify_all.py
```

`verify_all.py` runs the evaluation suite only if `data/evaluation/pseudo_gold_questions.jsonl` exists. If the pseudo-gold file has not been generated yet, verification skips the evaluation suite instead of failing.

## Recommended workflow

1. Generate or refresh pseudo-gold cases.
2. Run the evaluation suite.
3. Record developer feedback for wrong or unsupported answers.
4. Re-run evaluation so corrected cases override pseudo labels.
5. Periodically review `evaluation_report.md` for problematic terms and cases requiring human review.
