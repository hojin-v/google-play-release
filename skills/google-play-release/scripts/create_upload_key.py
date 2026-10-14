#!/usr/bin/env python3
"""Create a private Play upload key outside the repository; never print passwords."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--developer", required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    project = Path.cwd().resolve()
    if output == project or project in output.parents:
        raise SystemExit("Choose a private directory outside the current project.")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = output / "upload.jks"
    config = output / "signing.json"
    if key.exists() or config.exists():
        raise SystemExit("An upload key or configuration already exists here; reuse it instead of rotating it.")
    if any(c in args.developer for c in ',=+\\"<>;\r\n'):
        raise SystemExit("Developer must be a simple certificate organization name.")
    password = secrets.token_urlsafe(36)
    env = dict(os.environ, HNODE_UPLOAD_STORE_PASS=password, HNODE_UPLOAD_KEY_PASS=password)
    values = {
        "PLAY_KEYSTORE_FILE": str(key), "PLAY_STORE_PASSWORD": password,
        "PLAY_KEY_ALIAS": "upload", "PLAY_KEY_PASSWORD": password,
    }
    # Persist the password before key generation so interruption cannot strand an unreadable key.
    with open(config, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as file:
        json.dump(values, file, indent=2)
        file.write("\n")
    subprocess.run([
        "keytool", "-genkeypair", "-keystore", str(key), "-storetype", "JKS",
        "-alias", "upload", "-keyalg", "RSA", "-keysize", "4096", "-validity", "10000",
        "-dname", f"CN={args.developer}, OU=Google Play Upload, O={args.developer}",
        "-storepass:env", "HNODE_UPLOAD_STORE_PASS", "-keypass:env", "HNODE_UPLOAD_KEY_PASS",
    ], env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    key.chmod(0o600)
    subprocess.run([
        "keytool", "-exportcert", "-rfc", "-keystore", str(key), "-alias", "upload",
        "-storepass:env", "HNODE_UPLOAD_STORE_PASS", "-file", str(output / "upload-certificate.pem"),
    ], env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f"Private upload key: {key}")
    print(f"Private signing configuration: {config}")
    print(f"Public upload certificate: {output / 'upload-certificate.pem'}")
    print("Back up these private files. Keep the same key for future uploads.")


if __name__ == "__main__":
    main()
