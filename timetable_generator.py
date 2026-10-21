"""SmartClass timetable generator.

Fast, bounded constraint-based scheduler.
Rules enforced:
- No teacher clash across divisions/classes.
- Practical lectures always occupy two consecutive periods.
- The same theory subject is never placed in adjacent periods.
- A division's lectures on each day stay contiguous; therefore Free can only
  appear before the first lecture or after the last lecture.
- Selected working days and selected periods/day are respected.
- Teacher and division availability are respected for every occupied period.
"""
from __future__ import annotations

import random
from copy import deepcopy
from datetime import datetime
from typing import Any


def _time_to_minutes(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        h, m = str(value).strip().split(":", 1)
        return int(h) * 60 + int(m)
    except (ValueError, TypeError):
        return None


def _normalise_availability(data: dict[str, Any] | None) -> dict[str, Any]:
    return data if isinstance(data, dict) else {}


def _slot_available(availability, person, day, period_start, period_end):
    if not person:
        return True
    data = availability.get(person)
    if not isinstance(data, dict):
        return True

    # Current format: one global range.
    if "start" in data or "end" in data:
        start = _time_to_minutes(data.get("start"))
        end = _time_to_minutes(data.get("end"))
        if start is None and end is None:
            return True
        start = 0 if start is None else start
        end = 24 * 60 if end is None else end
        return period_start >= start and period_end <= end

    # Backward compatibility with old day-wise availability.
    day_data = data.get(day)
    if not isinstance(day_data, dict):
        return True
    start = _time_to_minutes(day_data.get("start"))
    end = _time_to_minutes(day_data.get("end"))
    if start is None and end is None:
        return True
    start = 0 if start is None else start
    end = 24 * 60 if end is None else end
    return period_start >= start and period_end <= end


def _period_times(start_time, end_time, periods_per_day, custom_times=None):
    """Return actual clock times for each period.

    custom_times is the settings format:
    {"1": {"start": "09:30", "end": "10:30"}, ...}
    Falls back to the old overall start/end range for backward compatibility.
    """
    custom_times = custom_times if isinstance(custom_times, dict) else {}

    parsed = {}
    complete = True
    for p in range(1, periods_per_day + 1):
        item = custom_times.get(str(p), custom_times.get(p))
        if not isinstance(item, dict):
            complete = False
            break
        a = _time_to_minutes(item.get("start"))
        b = _time_to_minutes(item.get("end"))
        if a is None or b is None or b <= a:
            complete = False
            break
        parsed[p] = (a, b)

    if complete and len(parsed) == periods_per_day:
        return parsed

    start = _time_to_minutes(start_time)
    if start is None:
        start = 570  # 09:30
    end = _time_to_minutes(end_time)
    if end is None or end <= start:
        end = start + periods_per_day * 60
    total = end - start
    return {
        p: (
            start + round(total * (p - 1) / periods_per_day),
            start + round(total * p / periods_per_day),
        )
        for p in range(1, periods_per_day + 1)
    }


def _build_allowed_slots(availability, people, days, period_times):
    """Parse availability once; never parse time strings inside the search."""
    allowed = {}
    for person in people:
        allowed[person] = {}
        for day in days:
            allowed[person][day] = {}
            for p, (a, b) in period_times.items():
                allowed[person][day][p] = _slot_available(
                    availability, person, day, a, b
                )
    return allowed


def create_empty_timetable(divisions, working_days, periods_per_day):
    return {
        d: {
            day: {p: None for p in range(1, periods_per_day + 1)}
            for day in working_days
        }
        for d in divisions
    }


def _division_class_map(divisions, classes=None):
    result = {}
    for c in classes or []:
        name = str(c.get("class_name", "")).strip()
        for div in c.get("divisions", []) or []:
            div = str(div).strip()
            if name and div:
                result[f"{name}-{div}"] = (name, div)
    for d in divisions:
        if d not in result:
            result[d] = d.rsplit("-", 1) if "-" in d else ("", d)
    return result

def _subject_tasks_for_division(division_id, subjects, class_name):
    tasks = []

    for subject in subjects:

        subject_class = str(
            subject.get("class_name", "")
        ).strip()

        if subject_class and class_name and subject_class != class_name:
            continue

        if subject_class and not class_name:
            continue

        name = str(
            subject.get("subject_name", "")
        ).strip()

        teacher = str(
            subject.get("teacher_name", "")
        ).strip()

        if not name:
            continue

        try:
            theory = max(
                0,
                int(subject.get("theory", 0) or 0)
            )
        except (ValueError, TypeError):
            theory = 0

        try:
            practical = max(
                0,
                int(subject.get("practical", 0) or 0)
            )
        except (ValueError, TypeError):
            practical = 0

        # ----------------------------------------------------
        # PRACTICAL
        # ----------------------------------------------------
        # Practical value means TOTAL practical PERIODS.
        #
        # Example:
        # practical = 2
        # -> ONE practical session
        # -> occupying 2 consecutive periods
        #
        # practical = 4
        # -> TWO practical sessions
        # -> each session occupies 2 consecutive periods
        # ----------------------------------------------------

        practical_sessions = practical // 2

        # If an odd practical value is entered, keep one
        # single-period practical so the entered requirement
        # is not silently lost.
        practical_remainder = practical % 2

        for i in range(practical_sessions):

            tasks.append({
                "division": division_id,
                "subject": name,
                "teacher": teacher,
                "type": "Practical",
                "duration": 2,
                "sequence": i,
            })

        # Handle an odd value such as Practical = 3.
        if practical_remainder:

            tasks.append({
                "division": division_id,
                "subject": name,
                "teacher": teacher,
                "type": "Practical",
                "duration": 1,
                "sequence": practical_sessions,
            })

        # ----------------------------------------------------
        # THEORY
        # ----------------------------------------------------

        for i in range(theory):

            tasks.append({
                "division": division_id,
                "subject": name,
                "teacher": teacher,
                "type": "Theory",
                "duration": 1,
                "sequence": i,
            })

    return tasks



def _occupied(day_data):
    return [p for p, slot in day_data.items() if slot is not None]


def _candidate_starts(day_data, periods_per_day, duration):
    """Return only placements that preserve a contiguous occupied block."""
    occ = sorted(_occupied(day_data))
    if not occ:
        return [
            list(range(s, s + duration))
            for s in range(1, periods_per_day - duration + 2)
        ]

    lo, hi = occ[0], occ[-1]
    out = []

    # Extend immediately before the current block.
    if lo - duration >= 1:
        out.append(list(range(lo - duration, lo)))

    # Extend immediately after the current block.
    if hi + duration <= periods_per_day:
        out.append(list(range(hi + 1, hi + duration + 1)))

    return out


def _same_theory_neighbor(timetable, division, day, period, subject):
    if period < 1:
        return False
    slot = timetable[division][day].get(period)
    return bool(
        slot
        and slot.get("type") == "Theory"
        and slot.get("subject") == subject
    )


def _task_members(task):
    return task.get("members") or [{"division": task["division"], "teacher": task.get("teacher", ""), "class_name": task.get("class_name", ""), "division_name": task.get("division_name", task["division"])}]


def _placement_valid(timetable, teacher_busy, task, day, periods, teacher_allowed, division_allowed):
    members = _task_members(task); teachers = {m.get("teacher", "") for m in members if m.get("teacher", "")}
    if any(timetable[m["division"]][day][p] is not None for m in members for p in periods): return False
    if any(any(t in teacher_busy[day][p] for t in teachers) for p in periods): return False
    for m in members:
        d, teacher = m["division"], m.get("teacher", "")
        if teacher and any(not teacher_allowed.get(teacher, {}).get(day, {}).get(p, True) for p in periods): return False
        if any(not division_allowed.get(d, {}).get(day, {}).get(p, True) for p in periods): return False
        if task["type"] == "Theory" and (_same_theory_neighbor(timetable,d,day,periods[0]-1,task["subject"]) or _same_theory_neighbor(timetable,d,day,periods[-1]+1,task["subject"])): return False
    return True


def _candidates(timetable, teacher_busy, task, days, ppd, teacher_allowed, division_allowed):
    members=_task_members(task); result=[]
    for day in sorted(days,key=lambda d:sum(1 for m in members for x in timetable[m["division"]][d].values() if x is not None)):
        starts=[_candidate_starts(timetable[m["division"]][day],ppd,task["duration"]) for m in members]
        possible=set(tuple(x) for x in starts[0]) if starts else set()
        for ss in starts[1:]: possible.intersection_update(tuple(x) for x in ss)
        for pp in possible:
            periods=list(pp)
            if _placement_valid(timetable,teacher_busy,task,day,periods,teacher_allowed,division_allowed): result.append((day,periods))
    return result


def _place(timetable, teacher_busy, task, day, periods):
    for m in _task_members(task):
        value={"subject":task["subject"],"teacher":m.get("teacher", ""),"type":task["type"],"class_name":m.get("class_name", ""),"division_name":m.get("division_name", ""),"combined_group":bool(task.get("members"))}
        for p in periods:
            timetable[m["division"]][day][p]=deepcopy(value)
            if value["teacher"]: teacher_busy[day][p].add(value["teacher"])


def _remove(timetable, teacher_busy, task, day, periods):
    for m in _task_members(task):
        teacher=m.get("teacher", "")
        for p in periods:
            timetable[m["division"]][day][p]=None
            if teacher and not any(timetable[d][day][p] and timetable[d][day][p].get("teacher")==teacher for d in timetable): teacher_busy[day][p].discard(teacher)

def _validate_final(timetable, divisions, days, ppd, ta, da, period_times):
    errors = []

    # No middle Free periods.
    for division in divisions:
        for day in days:
            occ = _occupied(timetable[division][day])
            if occ:
                lo, hi = min(occ), max(occ)
                if any(
                    timetable[division][day][p] is None
                    for p in range(lo, hi + 1)
                ):
                    errors.append(
                        f"Middle free period found in {division} on {day}."
                    )

    # No teacher clash.
    for day in days:
        for p in range(1, ppd + 1):
            seen = {}
            for division in divisions:
                slot = timetable[division][day][p]
                if not slot or not slot.get("teacher"):
                    continue
                teacher = slot["teacher"]
                if teacher in seen:
                    prior = seen[teacher]
                    if not (slot.get("combined_group") and prior.get("combined_group") and slot.get("subject") == prior.get("subject")):
                        errors.append(f"Teacher clash: {teacher} on {day}, period {p}.")
                else:
                    seen[teacher] = slot

    # Availability and practical/theory rules.
    for division in divisions:
        for day in days:
            for p in range(1, ppd + 1):
                slot = timetable[division][day][p]
                if not slot:
                    continue
                a, b = period_times[p]
                teacher = slot.get("teacher", "")
                if not _slot_available(ta, teacher, day, a, b):
                    errors.append(
                        f"Teacher {teacher} is unavailable for {day}, period {p}."
                    )
                if not _slot_available(da, division, day, a, b):
                    errors.append(
                        f"Division {division} is unavailable for {day}, period {p}."
                    )

    # Practical must be in exact two-period blocks.
    for division in divisions:
        for day in days:
            p = 1
            while p <= ppd:
                slot = timetable[division][day][p]
                if slot and slot.get("type") == "Practical":
                    if p == ppd:
                        errors.append(
                            f"Practical {slot.get('subject','')} is not consecutive."
                        )
                        break
                    nxt = timetable[division][day][p + 1]
                    if not nxt or nxt.get("type") != "Practical" or nxt.get("subject") != slot.get("subject"):
                        errors.append(
                            f"Practical {slot.get('subject','')} is not consecutive."
                        )
                    p += 2
                else:
                    p += 1

    # Same theory subject must not be adjacent.
    for division in divisions:
        for day in days:
            for p in range(1, ppd):
                a = timetable[division][day][p]
                b = timetable[division][day][p + 1]
                if (
                    a
                    and b
                    and a.get("type") == "Theory"
                    and b.get("type") == "Theory"
                    and a.get("subject") == b.get("subject")
                ):
                    errors.append(
                        f"Same theory subject is consecutive: {a.get('subject')} on {day}."
                    )

    return errors


def generate_timetable(
    subjects,
    divisions,
    working_days,
    periods_per_day,
    teacher_availability=None,
    division_availability=None,
    start_time="09:30",
    end_time="16:30",
    period_times=None,
    classes=None,
    max_attempts=8,
    generation_seed=None,
    combined_rules=None,
):
    """Generate a fast, clash-free timetable using bounded backtracking.

    generation_seed is supplied by the Flask route so that every
    "Generate Again" request can explore a fresh arrangement while
    keeping all the same constraints.
    """
    rng = random.Random(generation_seed)
    subjects = subjects or []
    divisions = [str(x).strip() for x in (divisions or []) if str(x).strip()]
    working_days = [
        str(x).strip() for x in (working_days or []) if str(x).strip()
    ]

    try:
        ppd = int(periods_per_day)
    except (ValueError, TypeError):
        ppd = 0

    if not divisions:
        raise ValueError("No divisions were provided.")
    if not working_days:
        raise ValueError("No working days were selected.")
    if ppd <= 0:
        raise ValueError("Periods per day must be greater than zero.")

    ta = _normalise_availability(teacher_availability)
    da = _normalise_availability(division_availability)
    period_times = _period_times(
        start_time,
        end_time,
        ppd,
        period_times,
    )
    class_map = _division_class_map(divisions, classes)

    tasks = []
    per_division = {}
    for division in divisions:
        cn, dn = class_map.get(division, ("", division))
        per_division[division] = _subject_tasks_for_division(division, subjects, cn)
        for t in per_division[division]: t["class_name"], t["division_name"] = cn, dn
    rules = (combined_rules or {}).get("rules", []) if isinstance(combined_rules, dict) else []
    shared = []
    for rule in rules:
        if not isinstance(rule, dict): continue
        selected = [str(d) for d in rule.get("divisions", []) if str(d) in per_division]
        sn, rc = str(rule.get("subject_name", "")).strip(), str(rule.get("class_name", "")).strip()
        if len(selected) < 2 or not sn: continue
        matches = {d: [t for t in per_division[d] if t.get("subject", "").strip().casefold()==sn.casefold() and (not rc or t.get("class_name", "").strip()==rc)] for d in selected}
        count=min((len(v) for v in matches.values()),default=0)
        for i in range(count):
            members=[]; base=None
            for d in selected:
                t=matches[d][i]; per_division[d].remove(t)
                members.append({"division":d,"teacher":t.get("teacher", ""),"class_name":t.get("class_name", ""),"division_name":t.get("division_name",d)})
                if base is None: base=t
            shared.append({"division":selected[0],"members":members,"subject":sn,"teacher":members[0].get("teacher", ""),"type":base["type"],"duration":base["duration"],"sequence":base.get("sequence",i),"class_name":rc,"division_name":selected[0]})
    for d in divisions: tasks.extend(per_division[d])
    tasks.extend(shared)
    if not tasks: raise ValueError("No theory or practical lecture requirements were entered.")
    total_cap=len(working_days)*ppd
    for d in divisions:
        needed=sum(t["duration"] for t in tasks if d in {m["division"] for m in _task_members(t)})
        if needed>total_cap: raise ValueError(f"{d} needs {needed} periods, but only {total_cap} are available.")
    teacher_required={}
    for t in tasks:
        for teacher in {m.get("teacher", "") for m in _task_members(t) if m.get("teacher", "")}:
            teacher_required[teacher]=teacher_required.get(teacher,0)+t["duration"]

    # Precompute every usable slot once.
    teacher_allowed = _build_allowed_slots(
        ta, teacher_required.keys(), working_days, period_times
    )
    division_allowed = _build_allowed_slots(
        da, divisions, working_days, period_times
    )

    # Quick teacher weekly-capacity check.
    for teacher, needed in teacher_required.items():
        possible = sum(
            1
            for day in working_days
            for p in range(1, ppd + 1)
            if teacher_allowed.get(teacher, {}).get(day, {}).get(p, True)
        )
        if needed > possible:
            raise ValueError(
                f"{teacher} needs {needed} periods but is available for only "
                f"{possible} periods in the selected week."
            )

    # Hardest tasks first: practical blocks, then heavily loaded teachers.
    teacher_load = teacher_required
    base = sorted(
        tasks,
        key=lambda t: (
            -t["duration"],
            -teacher_load.get(t["teacher"], 0),
            t["division"],
            t["subject"],
            t["sequence"],
        ),
    )

    best_error = "No valid timetable could be generated."

    for attempt in range(max(1, int(max_attempts))):
        timetable = create_empty_timetable(divisions, working_days, ppd)
        teacher_busy = {
            day: {p: set() for p in range(1, ppd + 1)}
            for day in working_days
        }

        remaining = base[:]

        # Randomise every attempt. This is important for the
        # "Generate Again" button: the first attempt must not always
        # follow the exact same deterministic task order.
        rng.shuffle(remaining)
        remaining.sort(
            key=lambda t: (
                -t["duration"],
                -teacher_load.get(t["teacher"], 0),
            )
        )

        nodes = 0
        max_nodes = max(
            15000,
            len(tasks) * len(working_days) * ppd * 300,
        )

        def search(left):
            nonlocal nodes, best_error
            nodes += 1
            if nodes > max_nodes:
                return False
            if not left:
                errors = _validate_final(
                    timetable,
                    divisions,
                    working_days,
                    ppd,
                    ta,
                    da,
                    period_times,
                )
                if not errors:
                    return True
                best_error = errors[0]
                return False

            # MRV: choose the task with the fewest legal placements.
            selected_i = -1
            selected_candidates = None
            selected_task = None

            for i, task in enumerate(left):
                candidates = _candidates(
                    timetable,
                    teacher_busy,
                    task,
                    working_days,
                    ppd,
                    teacher_allowed,
                    division_allowed,
                )
                if not candidates:
                    return False
                if selected_candidates is None or len(candidates) < len(selected_candidates):
                    selected_i = i
                    selected_candidates = candidates
                    selected_task = task
                    if len(candidates) == 1:
                        break

            # Explore valid placements in a different order on every
            # generation. All hard constraints are still checked.
            rng.shuffle(selected_candidates)

            next_left = left[:selected_i] + left[selected_i + 1:]
            task = selected_task
            division = task["division"]
            teacher = task["teacher"]

            for day, periods in selected_candidates:
                _place(timetable, teacher_busy, task, day, periods)

                # Only tasks whose domain can change are forward-checked.
                feasible = True
                for other in next_left:
                    if division not in {m["division"] for m in _task_members(other)} and teacher not in {m.get("teacher", "") for m in _task_members(other)}:
                        continue
                    if not _candidates(
                        timetable,
                        teacher_busy,
                        other,
                        working_days,
                        ppd,
                        teacher_allowed,
                        division_allowed,
                    ):
                        feasible = False
                        break

                if feasible and search(next_left):
                    return True

                _remove(timetable, teacher_busy, task, day, periods)

            return False

        if search(remaining):
            # Fill only the remaining leading/trailing empty positions with Free.
            for division in divisions:
                class_name, division_name = class_map.get(
                    division, ("", division)
                )
                for day in working_days:
                    for p in range(1, ppd + 1):
                        if timetable[division][day][p] is None:
                            timetable[division][day][p] = {
                                "subject": "Free",
                                "teacher": "",
                                "type": "FREE",
                                "class_name": class_name,
                                "division_name": division_name,
                            }
            return timetable

    raise ValueError(
        "SmartClass could not find a timetable satisfying all rules. "
        f"{best_error} Try adding another working day/period or widening teacher availability."
    )
