#!/usr/bin/env python3
"""Generate and verify ordered store previews; record their source without claiming device tests."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Screenshot path leaves project: {value}")
    return path


def load(root):
    release = json.loads((root / "play/release.json").read_text())
    path = inside(root, release["screenshot_config"])
    config = json.loads(path.read_text())
    if config.get("source_kind") != "html-preview":
        raise ValueError("Browser renders must declare source_kind=html-preview; use the ADB capture tool for devices")
    scenes = config["scenes"]
    names = [s["file"] for s in scenes]
    if not 2 <= len(names) <= 8 or len(names) != len(set(names)):
        raise ValueError("Provide 2–8 uniquely named scenes")
    for name in names:
        if Path(name).name != name or not name.endswith(".png"):
            raise ValueError("Scene files must be plain PNG filenames")
    sources = {str(path.relative_to(root)): sha(path)}
    for source in [config["page"], *config.get("source_files", [])]:
        sources[source] = sha(inside(root, source))
    config["metadata_path"] = release["metadata_path"]
    if Path(config["locale"]).name != config["locale"] or config["locale"].startswith("."):
        raise ValueError("Invalid screenshot locale")
    inside(root, f'{config["metadata_path"]}/{config["locale"]}/images/phoneScreenshots')
    inside(root, config["manifest"])
    return config, sources


def check(root):
    from release import png_info
    config, sources = load(root)
    manifest = inside(root, config["manifest"])
    if not manifest.exists():
        return ["Screenshot manifest missing; run play-screenshots generate"]
    receipt = json.loads(manifest.read_text())
    issues = []
    if receipt.get("sources") != sources:
        issues.append("Store previews are stale: source/configuration changed; regenerate screenshots")
    if receipt.get("source_kind") != config["source_kind"] or receipt.get("device") != config["device"]:
        issues.append("Screenshot source/device differs from its configuration")
    directory = inside(root, f'{config["metadata_path"]}/{config["locale"]}/images/phoneScreenshots')
    expected = [s["file"] for s in config["scenes"]]
    actual = sorted(p.name for p in directory.iterdir() if p.is_file()) if directory.exists() else []
    if expected != sorted(expected) or actual != expected:
        issues.append("Screenshot filenames/order differ from the configured scenes")
    images = receipt.get("images", [])
    if [image.get("file") for image in images] != expected:
        issues.append("Screenshot receipt order differs from configured scenes")
    for image in images:
        if image.get("file") not in expected:
            continue
        path = directory / image["file"]
        if not path.is_file() or sha(path) != image.get("sha256"):
            issues.append(f'Screenshot changed/missing: {image["file"]}')
            continue
        width, height, depth, _, alpha, _ = png_info(path)
        if (width, height) != (1080, 1920) or depth != 8 or alpha:
            issues.append(f'Invalid store preview PNG: {image["file"]}')
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("operation", choices=["generate", "check"])
    args = parser.parse_args()
    root = args.project.resolve()
    config, sources = load(root)
    if args.operation == "generate":
        result = subprocess.run(["node", str(Path(__file__).with_suffix(".cjs")), str(root)], check=True, capture_output=True, text=True)
        images = json.loads(result.stdout)
        manifest = inside(root, config["manifest"])
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"schema_version": 1, "source_kind": config["source_kind"],
            "device": config["device"], "sources": sources, "images": images}, ensure_ascii=False, indent=2) + "\n")
    issues = check(root)
    if issues:
        raise ValueError("; ".join(issues))
    print(f'{len(config["scenes"])} ordered {config["source_kind"]} images verified ({config["device"]})')


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        print(f"Store screenshot preparation failed: {error}", file=sys.stderr)
        sys.exit(1)
