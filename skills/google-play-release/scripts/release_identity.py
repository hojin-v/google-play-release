"""Production identity checks against the actual launcher bytecode, independent of app source."""
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

ANDROID = '{http://schemas.android.com/apk/res/android}'
PRERELEASE = re.compile(r'(?i)(?:^|[^a-z])(alpha|beta|rc\d*|snapshot|debug|dev|preview|canary|nightly|test)(?:[^a-z]|$)')
SEMVER = re.compile(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?')


def version_issues(version, code, allowed=()):
    issues = []
    if not version or PRERELEASE.search(version):
        issues.append(f'Production cannot use prerelease version name: {version}')
    for match in re.finditer(r'const-string(?:/jumbo)?\s+[vp]\d+,\s*("(?:\\.|[^"\\])*")', code):
        text = match.group(1)[1:-1]  # SemVer literals are ASCII; unrelated smali escapes are not JSON.
        if SEMVER.fullmatch(text) and text != version and text not in allowed:
            issues.append(f'Launcher contains stale/inconsistent version {text}; manifest is {version}')
    return sorted(set(issues))


def launcher_classes(xml):
    doc = ET.fromstring(xml)
    package = doc.get('package')
    result = []
    for node in doc.findall('./application/*'):
        if node.tag not in ('activity', 'activity-alias'):
            continue
        for intent in node.findall('intent-filter'):
            actions = {n.get(ANDROID+'name') for n in intent.findall('action')}
            categories = {n.get(ANDROID+'name') for n in intent.findall('category')}
            if 'android.intent.action.MAIN' in actions and 'android.intent.category.LAUNCHER' in categories:
                name = node.get(ANDROID+'targetActivity') or node.get(ANDROID+'name')
                if name.startswith('.'): name = package + name
                elif '.' not in name: name = package + '.' + name
                result.append(name)
    return sorted(set(result))


def production_identity_issues(root, config, apk, xml):
    doc = ET.fromstring(xml)
    version = doc.get(ANDROID+'versionName', '')
    issues = version_issues(version, '')
    classes = launcher_classes(xml) + config.get('version_audit_classes', [])
    if not classes or not Path(apk).is_file():
        return issues
    sdk = Path(os.environ.get('ANDROID_HOME', os.environ.get('ANDROID_SDK_ROOT', '')))
    tools = sorted(sdk.glob('cmdline-tools/*/bin/apkanalyzer'))
    if not tools:
        return issues + ['Production launcher audit requires SDK cmdline-tools/apkanalyzer (set ANDROID_HOME)']
    for name in sorted(set(classes)):
        try:
            code = subprocess.check_output([str(tools[-1]), 'dex', 'code', '--class', name, str(apk)],
                                           cwd=root, text=True, stderr=subprocess.PIPE)
            issues += [f'{name}: {issue}' for issue in version_issues(version, code, config.get('version_literal_allowlist', []))]
        except subprocess.CalledProcessError:
            issues.append(f'Could not inspect shipped launcher bytecode: {name}')
    return sorted(set(issues))
