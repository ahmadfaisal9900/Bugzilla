# Demo runbook

## S8v2 serving prerequisite (2026-11-23)

The owner confirmed the running registry champion was S2 / R7b / C1, Fast was
S1, and Deep read was unpublished. The reported 1809146 question used Smart
search. The local bundle has no comments for 1809146; do not promise a cited
comment answer for that ID.

The serving adapter now selects `AnswerGraphV2` and `ToolsV2` for S8v2, preserving
all research files. Four synthetic routes pass API TestClient / Lab experiment
runner parity (identical answers, routes and config hashes). This proves wiring,
not live answer quality. The 92.5% figure describes the historical development
composite; the serving dossier cap differs from the evaluated 12,000-byte cap.

Contract changes for Faiz:

- `RunConfig.system_id` additionally accepts `S8v2` (no S8 substitution).
- Optional `router_rules_version` and `tool_route_version` accept `json-tools-v2`,
  applicable to S8v2. Unset extension fields preserve legacy config hashes.
- S8v2 execute validation caps `s5_dossier_budget` at 4,096 UTF-8 bytes.
  Existing legacy S5/S8 record limits are retained for historical compatibility.
- `/v1/options` exposes corresponding choices; OpenAPI snapshot includes the new
  enum and optional fields. Answer, evidence, SSE and endpoint shapes are unchanged.

## Owner-run promotion and rollback

From the existing repository root, activate `iqfm`. Set `PYTHONPATH=src` and use
`.env` for existing MLflow credentials. Never paste credentials into commands.
The following commands make no Groq calls. Preview is the default. The B9 CLI's
`--serving-demo` path publishes only capped serving configurations, leaving the
immutable evaluated registrations alone.

1. Preview and save the **previous_champion** version (S2) for rollback:

   ```bash
   PYTHONPATH=src python scripts/mlops/register_all_systems.py --env-file .env --serving-demo --dry-run
   ```

   Expected: `state: DRY_RUN`, S8v2 Recommended, S5 Deep read (4096), and
   `fast_unchanged` identifying S1. If fast is missing or is not S1, it refuses.

2. Apply explicitly:

   ```bash
   PYTHONPATH=src python scripts/mlops/register_all_systems.py --env-file .env --serving-demo --apply
   ```

   Expected: `state: APPLIED`, new/reused Recommended and Deep read versions,
   champion points to the capped S8v2 version. Fast alias is never written.

3. Stop the existing launcher with Ctrl-C, then restart:

   ```bash
   TRACE_SAMPLE=1.0 bash scripts/app/run_local.sh
   ```

   In another terminal with `SERVING_API_KEY` loaded:

   ```bash
   curl -fsS --max-time 10 -H "X-API-Key: ${SERVING_API_KEY}" http://localhost:8000/v1/presets
   ```

   Expected: Recommended `is_champion=true`, `config.system_id=S8v2`; Fast=S1;
   Deep read=S5 and `s5_dossier_budget=4096`. A fallback preset has
   `is_champion=false`; that is not proof of registry promotion.

4. Roll back if live checks fail (replace `S2_VERSION` with step 1's version):

   ```bash
   PYTHONPATH=src python scripts/mlops/register_all_systems.py --env-file .env --serving-demo --rollback-version S2_VERSION --dry-run
   PYTHONPATH=src python scripts/mlops/register_all_systems.py --env-file .env --serving-demo --rollback-version S2_VERSION --apply
   ```

   Restart and check presets again. Rollback refuses any target whose config is
   not S2; Fast remains unchanged. YAML fallback deliberately remains S8v2, so
   verify registry connectivity and `is_champion=true` after rollback.
