# Champion promotion policy

Declared before selecting a real champion. `configs/promotion.yaml` holds the
thresholds: every scored family >= 0.50, false abstention <= 0.20, failure <= 0.05.
Missing required rates or p95 latency prevent automatic promotion; unknown is
never zero. At least one scored family is required, with n >= 1 per family.

Among eligible dev systems in the same eval_set with **identical scored family
coverage**, choose highest answer.macro (unweighted over scored families).
Within 0.01 of the best macro, prefer lower latency.p95_ms. Different coverage
requires an explicit policy override; no pooled score hides missing families.
`pilot125` is a PILOT subset, not the full dev set. Review-only runs lack the
metrics needed for automatic promotion. Their results can populate a dashboard.

A named `--override-policy` reason is stored on the registry version; it may
waive selection thresholds but can NEVER waive execute-mode configuration
validation, dev-only restrictions, or contract checks. Publishing a preset also
requires a deployable configuration. Do not silently reduce an archived 12K
S5 dossier to fit serving: evaluate a new compliant configuration instead.

Registry writes are explicit `--apply` actions. Dry-run compares candidate and
current champion and explains all gates. No production champion has been chosen
by the coding agent. Presets and champion are configuration packages, not weights.
