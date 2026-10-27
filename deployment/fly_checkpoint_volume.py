"""One-shot Fly volume provisioning. Never log API bodies, headers, or credentials.

The reviewed workflow runs this only against an exact main commit. An ambiguous
POST is *not* retried: an operator must inspect Fly before deciding next steps.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

APP = "personalised-travel-itinerary-planner"
NAME = "planner_checkpoints"
BASE = "https://api.machines.dev/v1/apps/" + APP

# Runs on the *currently deployed* image, which may not yet have any newly
# added CLI module. It returns only aggregate counts, not user data or IDs.
QUIESCENCE_PROBE = '''import json,os,sqlite3,sys
from pathlib import Path
from app.adaptive_sqlite_runtime import verify_volume
try:
    path=verify_volume()
    if os.geteuid() not in (0,10001): raise ValueError("unexpected uid")
    os.umask(0o077)
    if os.geteuid()==0:
        os.setgroups([]); os.setgid(10001); os.setuid(10001)
    if os.geteuid()!=10001 or verify_volume()!=path: raise ValueError("unsafe storage user")
    with sqlite3.connect(Path(path).as_uri()+"?mode=ro",uri=True,timeout=5) as c:
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")
        invalid_plans=c.execute("SELECT EXISTS(SELECT 1 FROM plans WHERE json_type(data) IS NOT 'object' OR json_type(data,'$.status') IS NOT 'text' OR json_extract(data,'$.status') NOT IN ('active','paused','completed','cancelled'))").fetchone()[0]
        invalid_sections=c.execute("SELECT EXISTS(SELECT 1 FROM sections WHERE json_type(data) IS NOT 'object' OR json_type(data,'$.status') IS NOT 'text' OR json_extract(data,'$.status') NOT IN ('queued','submitting','running','succeeded','failed','submission_unknown','cancelled'))").fetchone()[0]
        if invalid_plans or invalid_sections: raise ValueError("unknown status")
        version=c.execute("PRAGMA user_version").fetchone()[0]
        if version not in (1,2): raise ValueError("unknown schema")
        tables={row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        phase2={"research_jobs","revision_jobs","revision_controls"}
        if (version==1 and tables.intersection(phase2)) or (version==2 and not phase2.issubset(tables)): raise ValueError("incomplete schema")
        counts={"active_plans":c.execute("SELECT count(*) FROM plans WHERE json_extract(data,'$.status')='active'").fetchone()[0]}
        for status in ("queued","submitting","running","submission_unknown"):
            counts[status]=c.execute("SELECT count(*) FROM sections WHERE json_extract(data,'$.status')=?",(status,)).fetchone()[0]
        for table, prefix, statuses in (("research_jobs","research",("queued","submitting","running","succeeded","failed","submission_unknown","cancelled")),("revision_jobs","revision",("queued","submitting","running","candidate","accepted","rejected","failed","submission_unknown"))):
            if version==2:
                marks=','.join('?' for _ in statuses)
                if c.execute("SELECT EXISTS(SELECT 1 FROM "+table+" WHERE json_type(data) IS NOT 'object' OR json_type(data,'$.status') IS NOT 'text' OR json_extract(data,'$.status') NOT IN ("+marks+"))",statuses).fetchone()[0]: raise ValueError("unknown job status")
            for status in ("queued","submitting","running","submission_unknown"):
                counts[prefix+"_"+status]=c.execute("SELECT count(*) FROM "+table+" WHERE json_extract(data,'$.status')=?",(status,)).fetchone()[0] if version==2 else 0
    busy=any(value for key,value in counts.items() if not key.endswith('submission_unknown'))
    uncertain=any(value for key,value in counts.items() if key.endswith('submission_unknown'))
    ready=not busy and not uncertain
    print(json.dumps({"ready":ready,"code":"READY" if ready else "PLANNING_IN_PROGRESS" if busy else "PLANNING_UNCERTAIN","counts":counts},sort_keys=True))
    sys.exit(0 if ready else 1)
except Exception:
    print(json.dumps({"ready":False,"code":"PREFLIGHT_FAILED"},sort_keys=True))
    sys.exit(1)
'''


class Stop(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib's default redirect handling can forward Authorization to a
        # different host. Never follow a redirect with an app-scoped token.
        return None


def request(method: str, suffix: str, body=None):
    token = os.environ.get("FLY_API_TOKEN", "")
    if not token:
        raise Stop("Fly token unavailable; stopped.")
    data = None if body is None else json.dumps(body).encode()
    try:
        req = urllib.request.Request(BASE + suffix, data=data, method=method,
                                     headers={"Authorization": "Bearer " + token,
                                              "Content-Type": "application/json"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(req, timeout=30) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise Stop("Fly response too large; operation outcome uncertain, inspect before retry." if method == "POST" else "Fly response too large; stopped.")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        # A client error is a rejection, but a server error may follow a write.
        if method == "POST" and 400 <= exc.code < 500:
            raise Stop(f"Fly rejected operation (HTTP {exc.code}); no retry.") from None
        if method == "POST":
            raise Stop(f"Fly operation outcome uncertain (HTTP {exc.code}); inspect before retry.") from None
        raise Stop(f"Fly read rejected or failed (HTTP {exc.code}); stopped.") from None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        if method == "POST":
            raise Stop("Operation outcome uncertain or rejected; inspect Fly before any retry.") from None
        raise Stop("Fly read failed or returned invalid JSON; stopped.") from None
    except Stop:
        raise
    except Exception:
        # No raw exception details: these may contain request headers or data.
        if method == "POST":
            raise Stop("Operation outcome uncertain; inspect Fly before any retry.") from None
        raise Stop("Unexpected Fly read failure; stopped.") from None


def validate_machine_list(machines, require_disabled=True, allow_transition=False):
    if not isinstance(machines, list) or len(machines) != 1 or not isinstance(machines[0], dict):
        raise Stop("Expected exactly one existing Machine; stopped.")
    m = machines[0]
    guest = m.get("config", {}).get("guest", {}) if isinstance(m.get("config"), dict) else {}
    if not isinstance(guest, dict):
        raise Stop("Machine guest configuration unavailable; stopped.")
    if (not isinstance(m.get("id"), str) or not re.fullmatch(r"[a-f0-9]{12,32}", m["id"])
            or m.get("region") != "sin" or m.get("state") not in ({"started","starting","created","replacing"} if allow_transition else {"started"})
            or guest.get("cpu_kind") != "shared" or type(guest.get("cpus")) is not int or guest["cpus"] != 1
            or type(guest.get("memory_mb")) is not int or guest["memory_mb"] != 512):
        raise Stop("Existing Machine does not match approved Singapore 512 MB configuration; stopped.")
    env = m["config"].get("env", {})
    if not isinstance(env, dict) or (require_disabled and any(env.get(k, "false") != "false" for k in (
        "ADAPTIVE_PLANNING_ENABLED", "PLANNING_JOBS_ENABLED", "ADAPTIVE_RESEARCH_ENABLED", "ADAPTIVE_STREAMING_ENABLED"
    ))):
        raise Stop("Planning flags are not verified disabled; stopped.")
    return m["id"]


def validate_volume(volumes, machine_id=None, require_attached=False):
    if not isinstance(volumes, list) or len(volumes) != 1 or not isinstance(volumes[0], dict):
        raise Stop("Expected exactly one volume; stopped.")
    v = volumes[0]
    vid = v.get("id")
    if (not isinstance(vid, str) or not re.fullmatch(r"vol_[a-z0-9]+", vid)
            or v.get("name") != NAME or v.get("region") != "sin"
            or type(v.get("size_gb")) is not int or v["size_gb"] != 1
            or v.get("encrypted") is not True or v.get("auto_backup_enabled") is not False
            or v.get("state") != "created"):
        raise Stop("Created volume attributes or attachment are not as approved; stopped.")
    attached = v.get("attached_machine_id")
    if attached not in (None, "", machine_id) or (require_attached and attached != machine_id):
        raise Stop("Volume attachment does not match the approved Machine; stopped.")
    return vid


def verify(require_attached=False, require_disabled=False):
    machine_id = validate_machine_list(request("GET", "/machines"), require_disabled=require_disabled)
    vid = validate_volume(request("GET", "/volumes"), machine_id, require_attached)
    snapshots = request("GET", "/volumes/" + vid + "/snapshots")
    if not isinstance(snapshots, list) or snapshots:
        raise Stop("Volume snapshot list is not verified empty; stopped before ingest.")
    print("Verified one encrypted 1 GB Singapore volume; scheduled snapshots disabled and no snapshots present.")
    if require_attached:
        print("Verified volume attached to the sole approved Machine.")
    print("Volume ID:", vid)
    return machine_id


def run_store_preflight(initialize=False):
    machine_id = verify(require_attached=True, require_disabled=initialize)
    command = ["env", "PYTHONPATH=/app", "ADAPTIVE_PREFLIGHT_APPROVED=true"]
    if initialize:
        command.append("ADAPTIVE_SQLITE_INITIALIZE_APPROVED=true")
    command += ["python", "-m", "app.adaptive_sqlite_preflight"]
    if initialize:
        command.append("--initialize")
    # This is a fixed command, with no shell or user-controlled arguments.
    # Initialization must never be retried automatically after uncertain POST.
    result = request("POST", "/machines/" + machine_id + "/exec", {"command": command, "timeout": 25})
    if (not isinstance(result, dict) or type(result.get("exit_code")) is not int
            or type(result.get("exit_signal", 0)) is not int or result.get("exit_signal", 0) != 0):
        raise Stop("Store operation did not report success; inspect before retry.")
    try:
        data = json.loads(result.get("stdout", ""))
    except (ValueError, TypeError):
        raise Stop("Store operation returned an invalid readiness response; inspect before retry.") from None
    safe_failures = {"SQLITE_VOLUME_UNVERIFIED", "SQLITE_STORAGE_UNVERIFIED", "SQLITE_ALREADY_INITIALIZED",
                     "SQLITE_DIRECTORY_CREATE_DENIED", "SQLITE_PRIVILEGE_DROP_FAILED", "SECTIONS_SCHEMA_NOT_READY",
                     "SECTION_STORAGE_UNCONFIRMED", "PREFLIGHT_FAILED"}
    if (isinstance(data, dict) and set(data) == {"ready", "code"} and data["ready"] is False
            and isinstance(data["code"], str) and data["code"] in safe_failures and result["exit_code"] != 0):
        raise Stop("Store operation failed: " + data["code"] + "; inspect before retry.")
    if (result["exit_code"] != 0 or not isinstance(data, dict) or set(data) != {"ready", "code"}
            or data["ready"] is not True or data["code"] != "READY"):
        raise Stop("Store operation did not confirm readiness; inspect before retry.")
    print("Checkpoint storage initialized and ready." if initialize else "Checkpoint storage preflight ready.")


def check_quiescence():
    """Point-in-time gate only; does not prevent a new user admission."""
    machine_id = verify(require_attached=True)
    command = ["env", "PYTHONPATH=/app", "python", "-c", QUIESCENCE_PROBE]
    result = request("POST", "/machines/" + machine_id + "/exec", {"command": command, "timeout": 25})
    if (not isinstance(result, dict) or type(result.get("exit_code")) is not int
            or type(result.get("exit_signal", 0)) is not int or result.get("exit_signal", 0) != 0):
        raise Stop("Quiescence check unavailable; deployment stopped.")
    try:
        data = json.loads(result.get("stdout", ""))
    except (ValueError, TypeError):
        raise Stop("Quiescence check unavailable; deployment stopped.") from None
    if not isinstance(data, dict) or set(data) != {"ready", "code", "counts"} or not isinstance(data["counts"], dict):
        raise Stop("Quiescence check unavailable; deployment stopped.")
    counts = data["counts"]
    required = {"active_plans", "queued", "submitting", "running", "submission_unknown"} | {prefix + "_" + status for prefix in ("research", "revision") for status in ("queued", "submitting", "running", "submission_unknown")}
    if set(counts) != required or any(type(n) is not int or n < 0 for n in counts.values()):
        raise Stop("Quiescence check unavailable; deployment stopped.")
    if result["exit_code"] == 1 and data["ready"] is False and data["code"] == "PLANNING_IN_PROGRESS" and any(counts.values()):
        raise Stop("Planning is in progress; deployment stopped.")
    if result["exit_code"] == 1 and data["ready"] is False and data["code"] == "PLANNING_UNCERTAIN" and any(value for key,value in counts.items() if key.endswith('submission_unknown')):
        raise Stop("An earlier submission has an uncertain outcome; deployment stopped.")
    if result["exit_code"] != 0 or data["ready"] is not True or data["code"] != "READY" or any(counts.values()):
        raise Stop("Quiescence check unavailable; deployment stopped.")
    print("No active planning observed at this instant.")


def grounded_store_action(check_only=False):
    """Fixed operator upgrade or read-only verification; never initialize/retry."""
    machine_id = verify(require_attached=True, require_disabled=True)
    command = ["env", "PYTHONPATH=/app", "ADAPTIVE_PLANNING_ENABLED=false", "PLANNING_JOBS_ENABLED=false",
               "ADAPTIVE_RESEARCH_ENABLED=false", "ADAPTIVE_STREAMING_ENABLED=false",
               "python", "-m", "app.grounded_sqlite_upgrade", "--path", "/data/checkpoints/planning.sqlite3", "--check" if check_only else "--approve"]
    result = request("POST", "/machines/" + machine_id + "/exec", {"command": command, "timeout": 25})
    if (not isinstance(result, dict) or type(result.get("exit_code")) is not int
            or type(result.get("exit_signal", 0)) is not int or result.get("exit_signal", 0) != 0):
        raise Stop("Schema operation outcome unconfirmed; inspect before retry.")
    try:
        data = json.loads(result.get("stdout", ""))
    except (ValueError, TypeError):
        raise Stop("Schema operation outcome unconfirmed; inspect before retry.") from None
    failures = {"GROUNDED_MIGRATION_NOT_APPROVED", "SECTIONS_STORAGE_UNAVAILABLE", "GROUNDED_SCHEMA_NOT_READY", "PLANNING_IN_PROGRESS", "GROUNDED_MIGRATION_UNCONFIRMED", "SQLITE_VOLUME_UNVERIFIED", "SQLITE_STORAGE_UNVERIFIED", "SQLITE_PRIVILEGE_DROP_FAILED", "GROUNDED_STAGE_REQUIRED"}
    if (result["exit_code"] != 0 and isinstance(data, dict) and set(data) == {"ready", "code"}
            and data["ready"] is False and isinstance(data["code"], str) and data["code"] in failures):
        raise Stop("Schema operation stopped: " + data["code"] + "; inspect before retry.")
    if (result["exit_code"] != 0 or not isinstance(data, dict)
            or set(data) != {"ready", "code"} or data["ready"] is not True or data["code"] != "READY"):
        raise Stop("Schema operation outcome unconfirmed; inspect before retry.")
    print("Verified grounded schema v2." if check_only else "Explicit grounded schema upgrade completed; separate verification required.")


def verify_after_deploy():
    """Bounded GET-only wait; never rerun a deploy or create."""
    for attempt in range(12):
        machines = request("GET", "/machines")
        validate_machine_list(machines, require_disabled=False, allow_transition=True)
        if machines[0]["state"] == "started":
            return verify(require_attached=True)
        if attempt == 11:
            raise Stop("Machine did not reach started state within 12 read-only checks; stopped.")
        time.sleep(5)


def provision():
    validate_machine_list(request("GET", "/machines"))
    existing = request("GET", "/volumes")
    if not isinstance(existing, list) or existing:
        raise Stop("Volume list is not verified empty; inspect before proceeding.")
    # One request only. Do not infer failure from a timeout or automatically retry.
    request("POST", "/volumes", {"name": NAME, "region": "sin", "size_gb": 1,
            "encrypted": True, "auto_backup_enabled": False,
            "compute": {"cpu_kind": "shared", "cpus": 1, "memory_mb": 512}})
    vid = validate_volume(request("GET", "/volumes"))
    snapshots = request("GET", "/volumes/" + vid + "/snapshots")
    if not isinstance(snapshots, list) or snapshots:
        raise Stop("Volume snapshot list is not verified empty; stopped before ingest.")
    print("Verified one unattached encrypted 1 GB Singapore volume; scheduled snapshots disabled and no snapshots present.")
    print("Volume ID:", vid)


def main():
    try:
        if sys.argv[1:] == []:
            provision()
        elif sys.argv[1:] == ["--verify"]:
            verify()
        elif sys.argv[1:] == ["--verify-after-deploy"]:
            verify_after_deploy()
        elif sys.argv[1:] == ["--verify-attached"]:
            verify(require_attached=True)
        elif sys.argv[1:] == ["--initialize-store"]:
            run_store_preflight(initialize=True)
        elif sys.argv[1:] == ["--preflight-store"]:
            run_store_preflight()
        elif sys.argv[1:] == ["--check-quiescence"]:
            check_quiescence()
        elif sys.argv[1:] == ["--upgrade-grounded-store"]:
            grounded_store_action()
        elif sys.argv[1:] == ["--check-grounded-store"]:
            grounded_store_action(check_only=True)
        else:
            raise Stop("Invalid mode; stopped.")
    except Stop as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
