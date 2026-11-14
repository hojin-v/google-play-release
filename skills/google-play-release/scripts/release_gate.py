"""Offline, artifact-bound release review. Records are operator evidence, not human authentication."""
import datetime
import hashlib
import json
import re
from pathlib import Path

DEFAULT_CHECKS = [
    {"id": "core-function", "description": "Core flow on a physical target device"},
    {"id": "upgrade", "description": "Update an existing installation without clearing data"},
    {"id": "platform-compatibility", "description": "Current target OS/device and supported baseline"},
]


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def required_checks(config):
    checks = config.get("production_device_checks", DEFAULT_CHECKS)
    if not isinstance(checks, list) or not checks:
        raise ValueError("production_device_checks must contain at least one real-device check")
    ids = [c.get("id") for c in checks if isinstance(c, dict)]
    if len(ids) != len(checks) or any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("production_device_checks must have distinct, nonempty IDs")
    return checks


def binding(root, config, aab, audit):
    if audit.get("technical_issues") or audit.get("store_issues"):
        raise ValueError("Resolve technical and store issues before release review")
    if audit["package_name"] != config["package_name"] or audit["aab_sha256"] != digest(aab):
        raise ValueError("Audit does not match this app/AAB")
    metadata = root / config["metadata_path"]
    files = {str(p.relative_to(metadata)): digest(p) for p in sorted(metadata.rglob("*")) if p.is_file()}
    if not files:
        raise ValueError("Store metadata is missing")
    return {"package_name": audit["package_name"], "version_code": int(audit["version_code"]),
            "version_name": audit["version_name"], "aab_sha256": digest(aab),
            "apk_sha256": digest(root / config["apk_path"]),
            "metadata_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            "config_sha256": digest(root / "play/release.json")}


def review(root, config, aab, audit, output):
    identity = binding(root, config, aab, audit)
    if output.exists():
        existing = json.loads(output.read_text())
        if existing.get("artifact") != identity:
            raise ValueError("Existing review belongs to different artifacts; use a new output path")
        return existing  # Never erase observations when repeating preparation.
    result = {"schema_version": 1, "created_at": now(), "artifact": identity,
              "note": "Preparation is not production authorization. Fill observations from actual tests; do not infer them from unit tests or another APK.",
              "device_checks": [{**c, "status": "pending", "device": "", "os": "", "installation": "",
                                  "sdk": None, "tested_apk_sha256": "", "evidence": ""} for c in required_checks(config)]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def validate_evidence(document, identity, config):
    if document.get("artifact") != identity:
        raise ValueError("Device evidence is stale or belongs to another app/AAB/APK/listing/config")
    entries = document.get("device_checks", [])
    ids = [e.get("id") for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate device check IDs")
    by_id = {e["id"]: e for e in entries}
    for requirement in required_checks(config):
        item = by_id.get(requirement["id"], {})
        if item.get("status") != "passed":
            raise ValueError(f"Physical-device check is not passed: {requirement['id']}")
        for field in ("device", "os", "evidence"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"{requirement['id']}: actual {field} is required")
        sdk = item.get("sdk")
        if not isinstance(sdk, int) or isinstance(sdk, bool) or sdk <= 0:
            raise ValueError(f"{requirement['id']}: record the actual Android SDK level")
        if sdk < requirement.get("min_sdk", 1) or sdk > requirement.get("max_sdk", 10000):
            raise ValueError(f"{requirement['id']}: device SDK is outside the required compatibility range")
        if requirement.get("device_pattern") and not re.search(requirement["device_pattern"], item["device"]):
            raise ValueError(f"{requirement['id']}: wrong device family for this check")
        if item.get("installation") not in ("play", "aab-derived", "play-variant-apk"):
            raise ValueError(f"{requirement['id']}: test the Play variant, not a separate sideload/debug app")
        # Even a Play-delivered installation must name the matching local validation APK.
        # The operator records the observed Play version/installation in evidence as well.
        if item.get("tested_apk_sha256") != identity["apk_sha256"]:
            raise ValueError(f"{requirement['id']}: tested APK differs from the validated Play build")


def approve(root, config, aab, audit, evidence, authorization, rollout, output):
    identity = binding(root, config, aab, audit)
    validate_evidence(json.loads(evidence.read_text()), identity, config)
    fraction = float(rollout)
    if not 0 < fraction <= 1:
        raise ValueError("rollout must be greater than zero and at most one")
    if not authorization.strip():
        raise ValueError("Record the user's explicit production request; a generic deploy/test request is insufficient")
    if output.exists():
        raise ValueError("Approval already exists; do not overwrite it or reuse it for a different scope")
    result = {"schema_version": 1, "created_at": now(), "track": "production", "rollout": fraction,
              "artifact": identity, "evidence_sha256": digest(evidence),
              "authorization_source": "user", "authorization": authorization,
              "scope": "This app, version, artifact, listing and rollout only; not future releases"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def validate_approval(root, config, aab, audit, approval, evidence, rollout):
    if not approval or not evidence:
        raise ValueError("Production blocked: approval and real-device evidence are required. Prepare/review the test candidate first.")
    identity = binding(root, config, aab, audit)
    document = json.loads(Path(approval).read_text())
    if document.get("track") != "production" or document.get("artifact") != identity:
        raise ValueError("Production approval is for another app/version/artifact/listing/config")
    if document.get("rollout") != float(rollout):
        raise ValueError("Production rollout differs from the approved fraction")
    if document.get("authorization_source") != "user" or not document.get("authorization", "").strip():
        raise ValueError("Explicit user production authorization is missing")
    if document.get("evidence_sha256") != digest(evidence):
        raise ValueError("Device observations changed after approval")
    validate_evidence(json.loads(Path(evidence).read_text()), identity, config)
    return document
