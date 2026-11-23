"""Display-only names and formatting, independent of serving contracts."""

import logging
from functools import lru_cache

import yaml

from bugzilla_serving.contracts.run_config import ROOT

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def catalog():
    return yaml.safe_load((ROOT / "configs/display_catalog.yaml").read_text())


def entry(kind, identifier):
    identifier = str(identifier)
    values = catalog().get(kind, {})
    key = identifier.split("@", 1)[0] if kind == "eval_sets" else identifier
    if key in values:
        return values[key]
    if kind == "eval_sets" and key.startswith("family-"):
        return {"name": values["family-*"]["name"].format(family=name("families", key[7:]))}
    log.warning("Unknown display catalog ID: %s / %s", kind, identifier)
    return {"name": identifier}


def name(kind, identifier):
    return entry(kind, identifier)["name"]


def short(kind, identifier):
    row = entry(kind, identifier)
    return row.get("short", row["name"])


def long(kind, identifier):
    row = entry(kind, identifier)
    return row.get("long", row.get("short", row["name"]))


def fmt_score(value):
    return f"{value:.0%}" if isinstance(value, (float, int)) else "Not available"


def fmt_delta(value):
    return f"{value * 100:+.0f} pts"


def fmt_seconds(value):
    return f"{value:.1f} s" if isinstance(value, (float, int)) else "Not available"


def fmt_int(value):
    return f"{value:,.0f}" if isinstance(value, (float, int)) else "Not available"


def system_id(run):
    return run.tags.get("system_id", run.params.get("system_id", "?"))


def run_labels(runs):
    """Smallest field that distinguishes the whole visible same-system group."""
    result = {}
    for system in dict.fromkeys(system_id(r) for r in runs):
        group = [r for r in runs if system_id(r) == system]
        base = name("systems", system)
        suffixes = [""] * len(group)
        if len(group) > 1:
            for field, label in [
                ("s5_dossier_budget", "dossier"),
                ("context_budget_tokens", "context"),
                ("top_k", "sources"),
                ("temperature", "temperature"),
                ("corpus", "archive"),
                ("retriever", "search"),
            ]:
                values = [r.params.get(field) for r in group]
                if len(set(values)) == len(group):
                    suffixes = [
                        f"{label} {fmt_int(float(v))} tokens"
                        if field.endswith("budget") or field == "context_budget_tokens"
                        else f"{label} {v}"
                        for v in values
                    ]
                    if field in ("corpus", "retriever"):
                        suffixes = [
                            name("corpora" if field == "corpus" else "retrievers", v)
                            for v in values
                        ]
                    break
            else:
                values = [
                    r.tags.get("eval_set_name", r.tags.get("eval_set", "unknown")) for r in group
                ]
                if len(set(values)) == len(group):
                    suffixes = [name("eval_sets", v) for v in values]
                else:
                    import datetime as dt

                    suffixes = [
                        dt.datetime.fromtimestamp(r.started / 1000, dt.timezone.utc).strftime(
                            "%d %b %Y %H:%M:%S"
                        )
                        for r in group
                    ]
        for index, (run, suffix) in enumerate(zip(group, suffixes)):
            label = base + (" · " + suffix if suffix else "")
            if label in result.values():
                label += f" · record {index + 1}"
            result[run.id] = label
    return result
