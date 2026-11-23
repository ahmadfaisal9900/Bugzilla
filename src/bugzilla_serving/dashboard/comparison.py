"""Pure paired-comparison presentation; never infer pairing from equal counts."""

import math

from bugzilla_serving.dashboard.labels import fmt_delta, fmt_score, name


def delta_to_questions(delta, n):
    return round(delta * n)


def noise_marker(delta, n, discordant=None):
    if discordant is None:
        return dict(noise=abs(delta_to_questions(delta, n)) <= 2 or n < 15, p=None)
    better, worse = discordant
    total = better + worse
    p = (
        min(1.0, 2 * sum(math.comb(total, k) for k in range(min(better, worse) + 1)) / 2**total)
        if total
        else 1.0
    )
    return dict(noise=p >= 0.05, p=p)


def paired_counts(a, b, family, n=None):
    def keyed(rows):
        return {
            (r.get("dataset"), r.get("qid")): r["score"]
            for r in (rows or [])
            if r.get("family") == family and r.get("qid") and r.get("score") in (0, 1)
        }

    left, right = keyed(a), keyed(b)
    if not left or left.keys() != right.keys() or (n is not None and len(left) != n):
        return None
    return (sum(right[k] > left[k] for k in left), sum(right[k] < left[k] for k in left))


def summary(candidate, baseline, cells, overall_a=None, overall_b=None):
    groups = {"better": [], "worse": [], "same": []}
    for row in cells:
        delta, n = row["delta"], row["n"]
        count = delta_to_questions(delta, n)
        label = name("families", row["family"])
        if delta:
            groups["better" if delta > 0 else "worse"].append(
                f"{label} ({fmt_delta(delta)}, {abs(count)} "
                f"{'more' if count > 0 else 'fewer'} of {n} right)"
            )
        else:
            groups["same"].append(label)
    parts = [f"{key} on {', '.join(groups[key])}" for key in ("better", "worse") if groups[key]]
    if groups["same"]:
        parts.append(
            "no difference elsewhere" if parts else "no difference in the comparable families"
        )
    text = (
        f"{candidate} vs {baseline}: "
        + ("; ".join(parts) if parts else "no comparable scored families")
        + "."
    )
    if overall_a is not None and overall_b is not None:
        text += f" Overall: {fmt_score(overall_b)} vs {fmt_score(overall_a)}."
    return text
