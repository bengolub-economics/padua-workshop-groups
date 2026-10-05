"""Workshop grouping with explicit hard-rule diagnostics.

The organizer prefers groups near four, so the live size penalty is stronger
than the original demonstration spec. All other source score terms are retained.
No candidate is represented as satisfying the hard rules unless checked.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from ortools.sat.python import cp_model

HIGH = {"high", "very_high"}
PAID = {"20", "100"}
SIZE_PENALTY = 120  # per squared person away from four; deliberate user choice
HARD_PENALTY = 100_000
MAX_PEOPLE = 100


def _canonical(people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(people, key=lambda p: p["id"])


def input_hash(people: list[dict[str, Any]]) -> str:
    payload = json.dumps(_canonical(people), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_people(people: list[dict[str, Any]]) -> None:
    if not 3 <= len(people) <= MAX_PEOPLE:
        raise ValueError(f"Matching needs 3–{MAX_PEOPLE} approved participants")
    ids = [p["id"] for p in people]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate participant ID")
    known = set(ids)
    for p in people:
        if p.get("familiarity") not in {"low", "medium", "high", "very_high"}:
            raise ValueError(f"Invalid familiarity for {p['id']}")
        if p.get("subscription") not in {"none", "20", "100"}:
            raise ValueError(f"Invalid subscription for {p['id']}")
        for field in ("wishes", "vetoes"):
            refs = p.get(field, [])
            if not isinstance(refs, list) or len(refs) != len(set(refs)):
                raise ValueError(f"Invalid {field} for {p['id']}")
            if any(x not in known or x == p["id"] for x in refs):
                raise ValueError(f"Unknown/self {field} for {p['id']}")
        if set(p.get("wishes", [])) & set(p.get("vetoes", [])):
            raise ValueError(f"Wish and veto overlap for {p['id']}")


def check_groups(people: list[dict[str, Any]], groups: list[list[str]]) -> dict[str, Any]:
    """Independent evaluation of a partition, used before any publication."""
    by_id = {p["id"]: p for p in people}
    flat = [pid for g in groups for pid in g]
    partition_errors = []
    if len(flat) != len(set(flat)):
        partition_errors.append("A participant appears in multiple groups")
    if set(flat) != set(by_id):
        partition_errors.append("Groups omit or introduce participants")
    violations = []
    details = []
    total = 0
    for number, members in enumerate(groups, 1):
        if any(pid not in by_id for pid in members):
            continue
        group = [by_id[pid] for pid in members]
        size = len(group)
        highs = sum(p["familiarity"] in HIGH for p in group)
        paid = sum(p["subscription"] in PAID for p in group)
        hundreds = sum(p["subscription"] == "100" for p in group)
        women = sum(p.get("gender") == "woman" for p in group)
        wish_count = sum(q in members for p in group for q in p.get("wishes", []))
        if size < 3:
            violations.append({"group": number, "rule": "size_at_least_3", "members": members})
        if not highs:
            for p in group:
                if p["familiarity"] == "low":
                    violations.append({"group": number, "rule": "low_has_high", "members": [p["id"]]})
        if not paid:
            violations.append({"group": number, "rule": "access_20", "members": members})
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if b["id"] in a.get("vetoes", []) or a["id"] in b.get("vetoes", []):
                    violations.append({"group": number, "rule": "veto", "members": [a["id"], b["id"]]})
        score = (
            10 * wish_count
            + 50
            - SIZE_PENALTY * (size - 4) ** 2
            - 20 * (women == 1)
            - 20 * (hundreds == 0)
        )
        total += score
        details.append(
            {
                "group": number,
                "members": members,
                "size": size,
                "wishesMet": wish_count,
                "women": women,
                "hasHundredTier": bool(hundreds),
                "needsAccessKey": not hundreds,
                "score": score,
            }
        )
    return {
        "hardRulesPass": not partition_errors and not violations,
        "partitionErrors": partition_errors,
        "violations": violations,
        "groups": details,
        "score": total,
        "sizePenalty": SIZE_PENALTY,
    }


def _solve(people: list[dict[str, Any]], seconds: float, relax: bool) -> dict[str, Any]:
    n = len(people)
    ids = {p["id"]: i for i, p in enumerate(people)}
    # No arbitrary cap on group size. The penalty makes very large groups unattractive.
    slots = n // 3
    m = cp_model.CpModel()
    x = {(i, g): m.NewBoolVar(f"x_{i}_{g}") for i in range(n) for g in range(slots)}
    label = [m.NewIntVar(0, slots - 1, f"label_{i}") for i in range(n)]
    for i in range(n):
        m.AddExactlyOne(x[i, g] for g in range(slots))
        m.Add(label[i] == sum(g * x[i, g] for g in range(slots)))
    m.Add(label[0] == 0)
    high = [i for i, p in enumerate(people) if p["familiarity"] in HIGH]
    paid = [i for i, p in enumerate(people) if p["subscription"] in PAID]
    hundred = [i for i, p in enumerate(people) if p["subscription"] == "100"]
    women = [i for i, p in enumerate(people) if p.get("gender") == "woman"]
    objective = []
    used = []
    violations = []
    for g in range(slots):
        active = m.NewBoolVar(f"active_{g}")
        size = m.NewIntVar(0, n, f"size_{g}")
        m.Add(size == sum(x[i, g] for i in range(n)))
        m.Add(size == 0).OnlyEnforceIf(active.Not())
        m.Add(size >= 1).OnlyEnforceIf(active)
        used.append(active)
        if relax:
            bad_size = m.NewBoolVar(f"bad_size_{g}")
            m.Add(size >= 3).OnlyEnforceIf([active, bad_size.Not()])
            objective.append(-HARD_PENALTY * bad_size)
            violations.append(bad_size)
        else:
            m.Add(size >= 3).OnlyEnforceIf(active)
        size_flags = [m.NewBoolVar(f"size_{g}_{s}") for s in range(n + 1)]
        m.AddExactlyOne(size_flags)
        m.Add(size == sum(s * size_flags[s] for s in range(n + 1)))
        for s in range(1, n + 1):
            objective.append((50 - SIZE_PENALTY * (s - 4) ** 2) * size_flags[s])
        one_woman = m.NewBoolVar(f"one_woman_{g}")
        m.Add(sum(x[i, g] for i in women) != 1).OnlyEnforceIf(one_woman.Not())
        objective.append(-20 * one_woman)
        no_hundred = m.NewBoolVar(f"no_hundred_{g}")
        m.Add(sum(x[i, g] for i in hundred) >= 1).OnlyEnforceIf([active, no_hundred.Not()])
        objective.append(-20 * no_hundred)
    for g in range(slots - 1):
        m.Add(used[g] >= used[g + 1])
    for i, p in enumerate(people):
        needs_high = p["familiarity"] == "low"
        needs_paid = p["subscription"] == "none"
        if not needs_high and not needs_paid:
            continue
        bad_high = m.NewBoolVar(f"bad_high_{i}") if relax and needs_high else None
        bad_paid = m.NewBoolVar(f"bad_paid_{i}") if relax and needs_paid else None
        for g in range(slots):
            if needs_high:
                condition = [x[i, g]] + ([bad_high.Not()] if bad_high is not None else [])
                m.Add(sum(x[j, g] for j in high) >= 1).OnlyEnforceIf(condition)
            if needs_paid:
                condition = [x[i, g]] + ([bad_paid.Not()] if bad_paid is not None else [])
                m.Add(sum(x[j, g] for j in paid) >= 1).OnlyEnforceIf(condition)
        for bad in (bad_high, bad_paid):
            if bad is not None:
                objective.append(-HARD_PENALTY * bad)
                violations.append(bad)
    veto_pairs = set()
    for p in people:
        for other in p.get("vetoes", []):
            veto_pairs.add(tuple(sorted((ids[p["id"]], ids[other]))))
    for a, b in sorted(veto_pairs):
        if relax:
            bad = m.NewBoolVar(f"bad_veto_{a}_{b}")
            m.Add(label[a] != label[b]).OnlyEnforceIf(bad.Not())
            objective.append(-HARD_PENALTY * bad)
            violations.append(bad)
        else:
            m.Add(label[a] != label[b])
    for p in people:
        i = ids[p["id"]]
        for other in p.get("wishes", []):
            j = ids[other]
            met = m.NewBoolVar(f"wish_{i}_{j}")
            m.Add(label[i] == label[j]).OnlyEnforceIf(met)
            objective.append(10 * met)
    m.Maximize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = 4
    solver.parameters.random_seed = 1
    start = time.monotonic()
    status = solver.Solve(m)
    result = {"status": solver.StatusName(status), "seconds": round(time.monotonic() - start, 2)}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result["groups"] = [
            [people[i]["id"] for i in range(n) if solver.Value(x[i, g])]
            for g in range(slots)
            if solver.Value(used[g])
        ]
        result["bound"] = solver.BestObjectiveBound()
        result["objective"] = solver.ObjectiveValue()
    return result


def match_people(people: list[dict[str, Any]], seconds: float = 90) -> dict[str, Any]:
    validate_people(people)
    people = _canonical(people)
    seconds = min(max(float(seconds), 5), 120)
    hard = _solve(people, seconds, False)
    result = {"hardStatus": hard["status"], "inputHash": input_hash(people), "modelVersion": 2}
    if "groups" in hard:
        result.update({"groups": hard["groups"], "solveStatus": hard["status"], "relaxed": False})
    else:
        relaxed = _solve(people, seconds, True)
        result.update({"solveStatus": relaxed["status"], "relaxed": True})
        if "groups" in relaxed:
            result["groups"] = relaxed["groups"]
    if "groups" in result:
        result["check"] = check_groups(people, result["groups"])
    return result
