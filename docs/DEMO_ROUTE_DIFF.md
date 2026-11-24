# Offline serving route diff

2026-11-23: 122 fixed development questions, 6 changes, zero model calls.

All changes follow the required explicit-ID dossier fallback. None of these questions can establish an export timestamp from observation/ingestion times. No tuning was performed on these questions, and no new answer accuracy is claimed. Old null routes mean classifier-dependent, so this comparison cannot establish which final route the old live classifier would have chosen.

- `phase05/q_27791f312c9c478bfaed`: Using the specified frozen evidence, what exact UTC export timestamp establishes the archived fields for Firefox bug 1789818? Local observation and ingestion timestamps identify different events.
  Old: `None` / `ambiguous_id_query`; new: `S5` / `explicit_id_dossier_fallback_serving`.

- `phase05/q_8635c48a2ee113d4c738`: Using the specified frozen evidence, what exact UTC export timestamp establishes the archived fields for Firefox bug 1852092? Local observation and ingestion timestamps identify different events.
  Old: `None` / `ambiguous_id_query`; new: `S5` / `explicit_id_dossier_fallback_serving`.

- `phase05/q_878bcc2579afe2d4b68f`: Using the specified frozen evidence, what exact UTC export timestamp establishes the archived fields for Firefox bug 1892181? Local observation and ingestion timestamps identify different events.
  Old: `None` / `ambiguous_id_query`; new: `S5` / `explicit_id_dossier_fallback_serving`.

- `phase05/q_9940488831c9bb81264a`: Using the specified frozen evidence, what exact UTC export timestamp establishes the archived fields for Firefox bug 1925682? Local observation and ingestion timestamps identify different events.
  Old: `None` / `ambiguous_id_query`; new: `S5` / `explicit_id_dossier_fallback_serving`.

- `phase05/q_e39e28aa7f034f2ef4f4`: Using the specified frozen evidence, what exact UTC export timestamp establishes the archived fields for Firefox bug 1863827? Local observation and ingestion timestamps identify different events.
  Old: `None` / `ambiguous_id_query`; new: `S5` / `explicit_id_dossier_fallback_serving`.

- `phase05/q_faccb3ba563ab7ca68c7`: Using the specified frozen evidence, what exact UTC export timestamp establishes the archived fields for Firefox bug 1707396? Local observation and ingestion timestamps identify different events.
  Old: `None` / `ambiguous_id_query`; new: `S5` / `explicit_id_dossier_fallback_serving`.

Reproduce: `PYTHONPATH=src python scripts/testing/demo_route_diff.py --limit 122`.
