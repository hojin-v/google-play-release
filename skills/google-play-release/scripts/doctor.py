"""Read-only local setup diagnostics. Never authenticates, uploads, or prints secrets."""
import json
import os
from pathlib import Path
import shutil


def inspect(root, config):
    checks = []
    def add(name, ok, hint, required=True):
        checks.append({"name": name, "ok": bool(ok), "required": required, "hint": "" if ok else hint})
    for name in ["package_name", "bundle_path", "apk_path", "metadata_path", "output_path", "gradle_tasks", "min_target_sdk"]:
        add(name, config.get(name), f"Set {name} in play/release.json; use examples/release.json as a starting point")
    add("gradle-wrapper", (root / "gradlew").is_file() and os.access(root / "gradlew", os.X_OK), "Provide an executable project Gradle wrapper")
    for name in ["java", "keytool", "jarsigner"]:
        add(name, shutil.which(name), f"Install the project's JDK and configure JAVA_HOME/PATH (CI java_version is app-specific)")
    sdk = Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or Path.home() / "android-sdk")
    add("android-sdk", sdk.is_dir(), "Set ANDROID_HOME or ANDROID_SDK_ROOT")
    tools = sdk / "build-tools" / config.get("build_tools_version", "unset")
    for name in ["apksigner", "zipalign"]:
        add(name, (tools / name).is_file(), f"Install build-tools;{config.get('build_tools_version', '<version>')} in the configured SDK")
    signing_path = os.environ.get("PLAY_SIGNING_CONFIG")
    keys = ["PLAY_KEYSTORE_FILE", "PLAY_STORE_PASSWORD", "PLAY_KEY_ALIAS", "PLAY_KEY_PASSWORD"]
    signing = {key: os.environ.get(key) for key in keys}
    if signing_path:
        try:
            signing = json.loads(Path(signing_path).read_text())
        except (ValueError, OSError):
            signing = {}
    add("upload-signing", all(isinstance(signing.get(k), str) and signing[k].strip() for k in keys)
        and Path(signing.get("PLAY_KEYSTORE_FILE") or "/nonexistent").is_file(),
        "Set PLAY_SIGNING_CONFIG to a private signing JSON, or supply all four PLAY signing variables", required=False)
    credential = os.environ.get("PLAY_SERVICE_ACCOUNT_JSON")
    add("publisher-credentials", credential and Path(credential).is_file(), "Set PLAY_SERVICE_ACCOUNT_JSON for remote operations; never commit it", required=False)
    add("ruby-bundler", (shutil.which("ruby") and shutil.which("bundle")) or
        (Path(os.environ.get("PLAY_RUBY_ROOT") or Path.home() / ".local/share/play-release/ruby") / "root/usr/bin/ruby3.2").is_file(),
        "Install Ruby/Bundler and bundle install in the tooling repo; PLAY_RUBY_ROOT can select an existing local runtime", required=False)
    add("console-bootstrap", config.get("bootstrap_complete") is True, "Bootstrap unconfirmed: verify_access/status can inspect actual API readiness; complete required Console signing/setup when the API requires it", required=False)
    add("metadata", (root / config.get("metadata_path", "play/metadata/android")).is_dir(), "Prepare this app's listing, images, policy and release notes", required=False)
    return {"project": str(root), "package_name": config.get("package_name"), "checks": checks,
            "ready": all(c["ok"] for c in checks if c["required"]),
            "note": "Local checks only. API permissions, Console forms and policy approval are separate."}
