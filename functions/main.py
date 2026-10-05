"""Authenticated API for the Padua workshop grouping app."""

from __future__ import annotations

from datetime import datetime, timezone
from secrets import SystemRandom
from typing import Any

from firebase_admin import firestore, initialize_app
from firebase_functions import https_fn, options

from matching import check_groups, input_hash, match_people

initialize_app()

WORKSHOP = "padua-2026"
ADMIN_EMAIL = "ben@bengolub.net"
REGION = "europe-west1"
PHASES = {"setup", "enrollment", "preferences", "matching"}
CAREERS = {"student_under_3", "student_3_plus", "junior_faculty", "senior_faculty", "other"}
FAMILIARITY = {"low", "medium", "high", "very_high"}
SUBSCRIPTIONS = {"none", "20", "100"}
GENDERS = {"woman", "man", "nonbinary", "other", "prefer_not_to_say"}


def db():
    return firestore.client()


def root():
    return db().collection("workshops").document(WORKSHOP)


def config_ref():
    return root().collection("meta").document("config")


def _time() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(code: https_fn.FunctionsErrorCode, message: str):
    raise https_fn.HttpsError(code=code, message=message)


def _auth(req: https_fn.CallableRequest) -> tuple[str, str, bool]:
    if req.auth is None:
        _error(https_fn.FunctionsErrorCode.UNAUTHENTICATED, "Sign in first")
    uid = req.auth.uid
    email = str(req.auth.token.get("email", "")).strip().lower()
    verified = req.auth.token.get("email_verified") is True
    if not email or not verified:
        _error(https_fn.FunctionsErrorCode.PERMISSION_DENIED, "A verified email is required")
    return uid, email, email == ADMIN_EMAIL


def _admin(is_admin: bool) -> None:
    if not is_admin:
        _error(https_fn.FunctionsErrorCode.PERMISSION_DENIED, "Organizer access required")


def _config() -> dict[str, Any]:
    snap = config_ref().get()
    return snap.to_dict() if snap.exists else {"phase": "setup", "activeRun": None, "version": 1}


def _profile_ref(uid: str):
    return root().collection("profiles").document(uid)


def _pref_ref(uid: str):
    return root().collection("preferences").document(uid)


def _profiles() -> list[dict[str, Any]]:
    return [{"id": snap.id, **snap.to_dict()} for snap in root().collection("profiles").stream()]


def _preferences() -> dict[str, dict[str, Any]]:
    return {snap.id: snap.to_dict() for snap in root().collection("preferences").stream()}


def _people() -> list[dict[str, Any]]:
    pref = _preferences()
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "institution": p.get("institution", ""),
            "career": p["career"],
            "familiarity": p["familiarity"],
            "subscription": p["subscription"],
            "gender": p["gender"],
            "wishes": pref.get(p["id"], {}).get("wishes", []),
            "vetoes": pref.get(p["id"], {}).get("vetoes", []),
        }
        for p in _profiles()
        if p.get("approved") is True
    ]


def _clean_string(value: Any, label: str, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, f"{label} must be text")
    text = value.strip()
    if (required and not text) or len(text) > limit:
        _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, f"{label} has an invalid length")
    return text


def _enum(value: Any, allowed: set[str], label: str) -> str:
    if value not in allowed:
        _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, f"Invalid {label}")
    return value


def _state(uid: str, email: str, is_admin: bool) -> dict[str, Any]:
    config = _config()
    profile_snap = _profile_ref(uid).get()
    profile = profile_snap.to_dict() if profile_snap.exists else None
    pref_snap = _pref_ref(uid).get()
    preferences = pref_snap.to_dict() if pref_snap.exists else None
    result: dict[str, Any] = {
        "config": config,
        "email": email,
        "isAdmin": is_admin,
        "profile": profile,
        "preferences": preferences,
    }
    if profile and profile.get("approved") and config.get("phase") in {"preferences", "matching", "published"}:
        result["roster"] = [
            {"id": p["id"], "name": p["name"], "institution": p.get("institution", "")}
            for p in _profiles()
            if p.get("approved")
        ]
    if profile and profile.get("approved") and config.get("phase") == "published":
        assigned = root().collection("assignments").document(uid).get()
        if assigned.exists:
            result["assignment"] = assigned.to_dict()
    if is_admin:
        profiles = _profiles()
        pref = _preferences()
        reflections = [p["reflection"] for p in profiles if p.get("reflection")]
        SystemRandom().shuffle(reflections)
        result["admin"] = {
            "profiles": [{key: value for key, value in p.items() if key != "reflection"} for p in profiles],
            "reflections": reflections,
            "preferences": pref,
            "runs": [
                {"id": snap.id, **snap.to_dict()}
                for snap in root().collection("runs").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(5).stream()
            ],
        }
    return result


@https_fn.on_call(region=REGION, memory=options.MemoryOption.MB_512, max_instances=3, min_instances=0)
def workshop_api(req: https_fn.CallableRequest) -> dict[str, Any]:
    uid, email, is_admin = _auth(req)
    data = req.data if isinstance(req.data, dict) else {}
    action = data.get("action", "state")
    config = _config()
    phase = config["phase"]

    if action == "state":
        return _state(uid, email, is_admin)

    if action == "saveProfile":
        if phase != "enrollment":
            _error(https_fn.FunctionsErrorCode.FAILED_PRECONDITION, "Enrollment is closed")
        payload = data.get("profile") or {}
        if not isinstance(payload, dict):
            _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Invalid profile")
        record = {
            "email": email,
            "name": _clean_string(payload.get("name"), "Name", 100),
            "institution": _clean_string(payload.get("institution", ""), "Institution", 120, False),
            "career": _enum(payload.get("career"), CAREERS, "career stage"),
            "familiarity": _enum(payload.get("familiarity"), FAMILIARITY, "AI familiarity"),
            "subscription": _enum(payload.get("subscription"), SUBSCRIPTIONS, "subscription"),
            "gender": _enum(payload.get("gender"), GENDERS, "gender"),
            "reflection": _clean_string(payload.get("reflection", ""), "Reflection", 2000, False),
            "updatedAt": _time(),
        }
        previous = _profile_ref(uid).get()
        record["approved"] = previous.to_dict().get("approved", False) if previous.exists else False
        _profile_ref(uid).set(record)
        return _state(uid, email, is_admin)

    if action == "savePreferences":
        if phase != "preferences":
            _error(https_fn.FunctionsErrorCode.FAILED_PRECONDITION, "Preferences are closed")
        mine = _profile_ref(uid).get()
        if not mine.exists or not mine.to_dict().get("approved"):
            _error(https_fn.FunctionsErrorCode.PERMISSION_DENIED, "Your registration has not been approved")
        roster = {p["id"] for p in _profiles() if p.get("approved")}
        wishes = data.get("wishes")
        vetoes = data.get("vetoes")
        if not isinstance(wishes, list) or not isinstance(vetoes, list):
            _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Choose groupmates from the roster")
        if any(not isinstance(x, str) for x in wishes + vetoes):
            _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Invalid roster selection")
        if len(wishes) < min(10, len(roster) - 1):
            _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Select at least ten preferred groupmates")
        if len(wishes) != len(set(wishes)) or len(vetoes) != len(set(vetoes)):
            _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Duplicate groupmate selection")
        if uid in wishes + vetoes or not set(wishes + vetoes) <= roster or set(wishes) & set(vetoes):
            _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Invalid or conflicting groupmate selection")
        _pref_ref(uid).set({"wishes": wishes, "vetoes": vetoes, "updatedAt": _time()})
        return _state(uid, email, is_admin)

    _admin(is_admin)
    if action == "setPhase":
        target = data.get("phase")
        if target not in PHASES:
            _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Invalid phase")
        config_ref().set({"phase": target, "activeRun": config.get("activeRun"), "version": 1, "updatedAt": _time()})
        return _state(uid, email, is_admin)

    if action == "approve":
        if phase not in {"setup", "enrollment", "preferences"}:
            _error(https_fn.FunctionsErrorCode.FAILED_PRECONDITION, "Roster approval is closed")
        ids = data.get("ids", [])
        if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(x, str) for x in ids):
            _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Invalid participant list")
        approve = data.get("approved") is True
        batch = db().batch()
        for participant_id in ids:
            ref = _profile_ref(participant_id)
            if ref.get().exists:
                batch.update(ref, {"approved": approve})
        batch.commit()
        return _state(uid, email, is_admin)

    if action == "publish":
        if phase != "matching":
            _error(https_fn.FunctionsErrorCode.FAILED_PRECONDITION, "Open the matching phase first")
        run_id = data.get("runId")
        if not isinstance(run_id, str):
            _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Missing run ID")
        run_snap = root().collection("runs").document(run_id).get()
        if not run_snap.exists:
            _error(https_fn.FunctionsErrorCode.NOT_FOUND, "Match run not found")
        run = run_snap.to_dict()
        people = _people()
        if run["inputHash"] != input_hash(people):
            _error(https_fn.FunctionsErrorCode.FAILED_PRECONDITION, "Responses changed; rerun matching")
        checked = check_groups(people, run["groups"])
        if checked["partitionErrors"]:
            _error(https_fn.FunctionsErrorCode.FAILED_PRECONDITION, "The grouping is incomplete")
        if checked["violations"] and data.get("acknowledgeViolations") is not True:
            _error(https_fn.FunctionsErrorCode.FAILED_PRECONDITION, "Acknowledge every hard-rule violation before publishing")
        by_id = {p["id"]: p for p in people}
        batch = db().batch()
        for previous in root().collection("assignments").stream():
            batch.delete(previous.reference)
        for number, group in enumerate(run["groups"], 1):
            names = [{"id": pid, "name": by_id[pid]["name"]} for pid in group]
            for pid in group:
                batch.set(root().collection("assignments").document(pid), {
                    "group": number, "teammates": names, "runId": run_id, "publishedAt": _time()
                })
        batch.set(config_ref(), {"phase": "published", "activeRun": run_id, "version": 1, "updatedAt": _time()})
        batch.update(run_snap.reference, {"publishedAt": _time(), "publishedBy": uid})
        batch.commit()
        return _state(uid, email, is_admin)

    _error(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "Unknown action")


@https_fn.on_call(
    region=REGION,
    memory=options.MemoryOption.GB_1,
    timeout_sec=300,
    max_instances=1,
    min_instances=0,
    concurrency=1,
)
def generate_groups(req: https_fn.CallableRequest) -> dict[str, Any]:
    uid, _, is_admin = _auth(req)
    _admin(is_admin)
    if _config()["phase"] != "matching":
        _error(https_fn.FunctionsErrorCode.FAILED_PRECONDITION, "Open the matching phase first")
    people = _people()
    if len(people) < 3:
        _error(https_fn.FunctionsErrorCode.FAILED_PRECONDITION, "At least three approved participants are needed")
    result = match_people(people, seconds=90)
    result["createdAt"] = _time()
    result["createdBy"] = uid
    result["participantCount"] = len(people)
    result["missingPreferences"] = [p["id"] for p in people if not p["wishes"]]
    ref = root().collection("runs").document()
    ref.set(result)
    return {"id": ref.id, **result}
