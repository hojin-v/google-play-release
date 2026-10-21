#!/usr/bin/env python3
"""Build and audit a Play AAB. Standard library only; never uploads anything."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ANDROID = "{http://schemas.android.com/apk/res/android}"
BUNDLETOOL_VERSION = "1.18.3"
BUNDLETOOL_SHA256 = "a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29"


def run(args, root, capture=False):
    return subprocess.run(args, cwd=root, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def bundletool(root):
    p = root / "build/tools" / f"bundletool-{BUNDLETOOL_VERSION}.jar"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        url = f"https://github.com/google/bundletool/releases/download/{BUNDLETOOL_VERSION}/bundletool-all-{BUNDLETOOL_VERSION}.jar"
        tmp = p.with_suffix(".download")
        urllib.request.urlretrieve(url, tmp)
        if sha(tmp) != BUNDLETOOL_SHA256:
            tmp.unlink()
            raise ValueError("bundletool download checksum mismatch")
        tmp.replace(p)
    if sha(p) != BUNDLETOOL_SHA256:
        raise ValueError("bundletool checksum mismatch")
    return p


def elf_issues(data):
    if data[:4] != b"\x7fELF":
        return ["invalid ELF"]
    if data[4] != 2:
        return []  # The 16 KB requirement concerns 64-bit ABIs.
    endian = "<" if data[5] == 1 else ">"
    offset = struct.unpack_from(endian + "Q", data, 32)[0]
    size, count = struct.unpack_from(endian + "HH", data, 54)
    issues = []
    loads = 0
    for i in range(count):
        kind, flags, file_offset, vaddr, _, filesz, memsz, align = struct.unpack_from(
            endian + "IIQQQQQQ", data, offset + i * size)
        if kind == 1:
            loads += 1
            if align < 16384 or (vaddr - file_offset) % 16384:
                issues.append(f"LOAD alignment {align} or offset is incompatible with 16 KB")
        if kind == 0x6474E552 and (vaddr + memsz) % 16384:
            issues.append("RELRO end is incompatible with 16 KB")
    if not loads:
        issues.append("no LOAD segments")
    return issues


def manifest_issues(doc, config):
    issues = []
    if doc.get("package") != config["package_name"]:
        issues.append("applicationId mismatch")
    sdk = doc.find("uses-sdk")
    if sdk is None or int(sdk.get(ANDROID + "targetSdkVersion", "0")) < config["min_target_sdk"]:
        issues.append("targetSdk below configured current Play requirement")
    app = doc.find("application")
    if app is None or app.get(ANDROID + "debuggable", "false") == "true":
        issues.append("missing application or debuggable release")
    permissions = {p.get(ANDROID + "name") for p in doc.findall("uses-permission")}
    issues += [f"forbidden permission: {p}" for p in config.get("forbidden_permissions", []) if p in permissions]
    if app is not None:
        for service in app.findall("service"):
            fgs = service.get(ANDROID + "foregroundServiceType", "")
            kinds = fgs.split("|") if fgs else []
            if fgs.startswith("0x") or fgs.isdigit():
                flags = int(fgs, 0)
                types = {1: "dataSync", 2: "mediaPlayback", 4: "phoneCall", 8: "location", 16: "connectedDevice",
                         32: "mediaProjection", 64: "camera", 128: "microphone", 256: "health",
                         512: "remoteMessaging", 8192: "mediaProcessing", 0x40000000: "specialUse", 0x80000000: "systemExempted"}
                kinds = [name for bit, name in types.items() if flags & bit]
                unknown = flags & ~sum(types) & ~2048
                if unknown:
                    issues.append(f"unknown FGS flags: {hex(unknown)}")
            for kind in kinds:
                permission = "android.permission.FOREGROUND_SERVICE_" + re.sub(r"(?<!^)(?=[A-Z])", "_", kind).upper()
                if permission not in permissions:
                    issues.append(f"FGS permission missing: {permission}")
            if "specialUse" in kinds:
                subtype = next((p for p in service.findall("property") if p.get(ANDROID + "name") == "android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"), None)
                if subtype is None or not subtype.get(ANDROID + "value", "").strip():
                    issues.append("specialUse FGS explanation missing")
        for name in config.get("required_foreground_services", []):
            service = next((s for s in app.findall("service") if s.get(ANDROID + "name") in (name, config["package_name"] + name)), None)
            if service is None or not service.get(ANDROID + "foregroundServiceType", "").strip():
                issues.append(f"required FGS service/type missing: {name}")
        names = {p.get(ANDROID + "name", "") for p in app}
        for name in config.get("forbidden_components", []):
            full = config["package_name"] + name if name.startswith(".") else name
            if name in names or full in names:
                issues.append(f"forbidden component: {name}")
    return issues


def png_info(path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"expected PNG: {path}")
    w, h, depth, color = struct.unpack_from(">IIBB", data, 16)
    has_alpha = color in (4, 6)
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        if data[offset + 4:offset + 8] == b"tRNS":
            has_alpha = True
        offset += length + 12
    return w, h, depth, color, has_alpha, len(data)


def store_issues(root, config, version_code):
    issues = []
    if config.get("screenshot_config"):
        from screenshots import check as check_screenshots
        try:
            issues += check_screenshots(root)
        except (OSError, ValueError, KeyError) as error:
            issues.append(f"Store screenshot configuration invalid: {error}")
    if not config.get("developer_name", "").strip():
        issues.append("developer_name missing")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", config.get("contact_email", "")):
        issues.append("contact_email missing/invalid")
    if not config.get("privacy_policy_url", "").startswith("https://"):
        issues.append("public HTTPS privacy_policy_url missing")
    else:
        try:
            req = urllib.request.Request(config["privacy_policy_url"], headers={"User-Agent": "Mozilla/5.0 (PlayReleasePreflight)"})
            with urllib.request.urlopen(req, timeout=10) as response:
                policy = response.read(262144).decode("utf-8", errors="replace")
                if not response.geturl().startswith("https://"):
                    issues.append("privacy policy redirects to an insecure URL")
                if (config["contact_email"] not in policy or config["developer_name"] not in policy
                        or config.get("policy_app_name", "") not in policy):
                    issues.append("public privacy policy does not identify the configured developer/contact")
        except (OSError, ValueError) as e:
            issues.append(f"public privacy policy unavailable: {e}")
    metadata = root / config["metadata_path"]
    locales = sorted(p for p in metadata.iterdir() if p.is_dir()) if metadata.exists() else []
    if not locales:
        issues.append("no listing locales")
    for locale in locales:
        for name, limit in [("title", 30), ("short_description", 80), ("full_description", 4000)]:
            p = locale / f"{name}.txt"
            s = p.read_text().strip() if p.exists() else ""
            if not s or len(s) > limit:
                issues.append(f"{locale.name}/{name}: empty or exceeds {limit} characters")
        notes = locale / "changelogs" / f"{version_code}.txt"
        if not notes.exists() or not 0 < len(notes.read_text().strip()) <= 500:
            issues.append(f"{locale.name}: version-specific release notes missing/over 500 characters")
        for name, dimensions in [("icon", (512, 512)), ("featureGraphic", (1024, 500))]:
            p = locale / "images" / f"{name}.png"
            if not p.exists():
                issues.append(f"{locale.name}/{name} missing")
                continue
            w, h, depth, color, alpha, length = png_info(p)
            if (w, h) != dimensions or (name == "featureGraphic" and (alpha or depth != 8)):
                issues.append(f"{locale.name}/{name}: invalid dimensions/format")
            if name == "icon" and (length > 1024 * 1024 or depth != 8 or color != 6):
                issues.append(f"{locale.name}/icon: requires 32-bit RGBA PNG <= 1 MB")
        screenshots = sorted((locale / "images/phoneScreenshots").glob("*.png"))
        if not 2 <= len(screenshots) <= 8:
            issues.append(f"{locale.name}: requires 2–8 phone screenshots/store previews")
        for p in screenshots:
            w, h, depth, _, alpha, _ = png_info(p)
            if min(w, h) < 320 or max(w, h) > 3840 or max(w, h) > 2 * min(w, h) or alpha or depth != 8:
                issues.append(f"{p.name}: invalid screenshot dimensions/format")
    return issues


def audit(root, config, aab):
    bt = bundletool(root)
    java = ["java", "-jar", str(bt)]
    run(java + ["validate", f"--bundle={aab}"], root, capture=True)
    xml = run(java + ["dump", "manifest", f"--bundle={aab}", "--module=base"], root, capture=True)
    doc = ET.fromstring(xml)
    issues = manifest_issues(doc, config)
    alignment = run(java + ["dump", "config", f"--bundle={aab}"], root, capture=True)
    native = []
    with zipfile.ZipFile(aab) as z:
        for bundled, source in config.get("bundled_documents", {}).items():
            if bundled not in z.namelist() or z.read(bundled) != (root / source).read_bytes():
                issues.append(f"bundled document is missing/stale: {bundled}; rebuild the AAB")
        for n in sorted(z.namelist()):
            if n.endswith(".so"):
                data = z.read(n)
                problems = elf_issues(data)
                native.append({"path": n, "issues": problems})
                issues += [f"{n}: {p}" for p in problems]
        if not any(n.upper().endswith((".RSA", ".DSA", ".EC")) and n.startswith("META-INF/") for n in z.namelist()):
            issues.append("AAB signature missing")
    if native and "PAGE_ALIGNMENT_16K" not in alignment:
        issues.append("AAB packaging is not PAGE_ALIGNMENT_16K")
    verified = run(["jarsigner", "-J-Duser.language=en", "-verify", str(aab)], root, capture=True)
    if "jar verified." not in verified:
        issues.append("AAB signature did not verify")
    code = int(doc.get(ANDROID + "versionCode", "0"))
    if code <= 0:
        issues.append("invalid versionCode")
    result = {"package_name": doc.get("package"), "version_code": code,
              "version_name": doc.get(ANDROID + "versionName"), "aab_sha256": sha(aab),
              "target_sdk": int(doc.find("uses-sdk").get(ANDROID + "targetSdkVersion")),
              "native_libraries": native, "technical_issues": issues,
              "store_issues": store_issues(root, config, code)}
    return result, xml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--signing-config", type=Path, default=os.environ.get("PLAY_SIGNING_CONFIG"),
                         help="private JSON file containing the four PLAY signing environment values")
    package = sub.add_parser("package", help="refresh metadata in an already-built, re-audited release")
    package.add_argument("--aab", type=Path, required=True)
    package.add_argument("--store", action="store_true")
    check = sub.add_parser("check")
    check.add_argument("--aab", type=Path, required=True)
    check.add_argument("--store", action="store_true", help="also require listing readiness")
    args = parser.parse_args()
    root = args.project.resolve()
    config = json.loads((root / "play/release.json").read_text())
    if args.command == "prepare":
        if args.signing_config:
            signing = json.loads(args.signing_config.read_text())
            keys = ("PLAY_KEYSTORE_FILE", "PLAY_STORE_PASSWORD", "PLAY_KEY_ALIAS", "PLAY_KEY_PASSWORD")
            if not all(isinstance(signing.get(key), str) and signing[key].strip() for key in keys):
                raise ValueError("private signing configuration requires all four PLAY signing values")
            if not Path(signing["PLAY_KEYSTORE_FILE"]).is_file():
                raise ValueError("configured Play upload keystore does not exist")
            os.environ.update({key: signing[key] for key in keys})
        for command in config.get("preparation_commands", []):
            run(command, root)
        if config.get("screenshot_config"):
            run([sys.executable, str(Path(__file__).with_name("screenshots.py")), "--project", str(root), "generate"], root)
        run([str(root / "gradlew"), "--no-daemon"] + config.get("gradle_args", []) + config["gradle_tasks"], root)
        aab = root / config["bundle_path"]
    else:
        aab = args.aab.resolve()
    result, xml = audit(root, config, aab)
    if result["technical_issues"] or (getattr(args, "store", False) and result["store_issues"]):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    if args.command in ("prepare", "package"):
        if config.get("build_tools_version"):
            sdk = Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or (Path.home() / "android-sdk"))
            tools = sdk / "build-tools" / config["build_tools_version"]
            run([str(tools / "zipalign"), "-c", "-P", "16", "4", str(root / config["apk_path"])], root, capture=True)
            run([str(tools / "apksigner"), "verify", str(root / config["apk_path"])], root, capture=True)
            result["device_test_apk_zipalign_16kb"] = True
            result["device_test_apk_signature_verified"] = True
        out = root / config["output_path"] / f'{result["version_name"]}-{result["version_code"]}'
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(aab, out / "app.aab")
        shutil.copy2(root / config["apk_path"], out / "device-test.apk")
        for src, dest in [(root / config["metadata_path"], out / "metadata")]:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
        submission = out / "submission"
        if submission.exists():
            shutil.rmtree(submission)
        submission.mkdir()
        # Credential files may be gitignored in play/. Never include them in upload artifacts.
        for p in (root / "play").iterdir():
            if p.is_file() and (p.suffix in (".md", ".html") or p.name in ("release.json", "video-scenario.json", "declarations.json", "screenshots.json", "screenshot-manifest.json")):
                shutil.copy2(p, submission / p.name)
        (out / "AndroidManifest.xml").write_text(xml)
        (out / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        cert = run(["keytool", "-J-Duser.language=en", "-printcert", "-jarfile", str(aab)], root, capture=True)
        (out / "upload-certificate.txt").write_text(cert)
        sources = out / "sources"
        if sources.exists():
            shutil.rmtree(sources)
        for src in config.get("source_artifacts", []):
            shutil.copytree(root / src, sources / Path(src).name,
                            ignore=shutil.ignore_patterns("build", ".cxx", ".git", "__pycache__"))
        files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
        (out / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(out)}\n" for p in files))
        archive = shutil.make_archive(str(out), "zip", root_dir=out.parent, base_dir=out.name)
        print(f"Release package: {out}")
        print(f"Release archive: {archive}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, struct.error, subprocess.CalledProcessError) as e:
        print(f"Release preparation failed: {e}", file=sys.stderr)
        sys.exit(1)
