# Scoring

The desk bot answers from `surface/SYSTEM.md` only (no LLM). A case passes if every `must_include` string appears in the answer.

Write policies as general standing rules. Case-specific Q&A that only restates a train question will miss holdout wording.
