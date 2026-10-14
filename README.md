# Google Play release automation

Reusable Android release preparation, signed AAB validation, Play listing synchronization, internal draft uploads, promotion and actual UI recording. App code, store assets and declarations belong in each Android project's `play/` directory. This repository contains no app or account credentials.

## Use with an Android project

Clone this repository beside the app. Configure `<app>/play/release.json` with package ID, Gradle tasks, artifact and metadata paths, contact details and Console bootstrap status. The preparation commands run in the app project; the toolkit works from any directory.

```bash
google-play-release/bin/play-release --project ./your-app prepare --signing-config /private/signing.json
google-play-release/bin/play-release --project ./your-app check --aab ./your-app/build/release.aab --store
google-play-release/bin/play-release --project ./your-app package --aab ./your-app/app/build/outputs/bundle/playRelease/app-play-release.aab --store

export PLAY_SERVICE_ACCOUNT_JSON=/private/service-account.json
google-play-release/bin/play-fastlane --project ./your-app android verify_access
google-play-release/bin/play-fastlane --project ./your-app android sync_listing aab:build/release.aab
google-play-release/bin/play-fastlane --project ./your-app android draft aab:build/release.aab
```

Python 3.11+, JDK 17, the Android SDK and the project's Gradle wrapper are required. Fastlane additionally needs Ruby/Bundler (`bundle install` in this repository). `PLAY_RUBY_ROOT` supports an existing portable local Ruby runtime. Signing and service account files stay outside Git.

For the first app, create it and save its first AAB in Play Console before API uploads. A draft is not a published test or production release. The [skill](skills/google-play-release/SKILL.md) and [workflow](skills/google-play-release/references/workflow.md) describe the full process.

## Real Android video automation

Connect and authorize an unlocked test device, install the exact APK to demonstrate, and supply an app-specific JSON scenario. The runner uses actual app/system UI controls, records on the device, verifies foreground service start/stop through `dumpsys`, and produces `raw.mp4`, `captioned.mp4`, `captions.srt`, screenshots and `evidence.json`.

```bash
python3 google-play-release/tools/setup_video_tools.py  # Linux x86_64 FFmpeg; optional if installed
python3 google-play-release/tools/capture_android_video.py \
  --config your-app/play/video-scenario.json --serial DEVICE_SERIAL \
  --output your-app/build/play-video/run-001
```

ADB selection: `--adb /path/to/adb` and `--adb-port 5037`. WSL can call Windows `adb.exe` directly, including another server port. `--reset-app` explicitly erases only the configured test app's data. `--emulator-setup` enables developer options only on an emulator and fails on a physical phone. A recording run never grants the app secure-setting permissions or invents pairing success. Only the scenario's own recorder PID can be stopped.

Each step has `action`, `caption`, optional `hold` seconds, and action-specific fields. Actions: `launch`, `tap` (`selector` using actual UI attributes, optional `optional`/`timeout`), `notifications`, `swipe` (`coordinates`), `back`, and `service` (`active`). The configuration also specifies `name`, `package`, launcher `component`, `service`, integer `service_type`, and the evidence `scope`. Captions identify emulator vs physical-device footage. Refine selectors when a manufacturer uses different system UI.

The current built-in recorder has no audio. It can prove actual UI/FGS lifecycle; it cannot establish manufacturer camera behavior. ADB loss can interrupt UI automation; the on-device recorder remains bounded to 170 seconds and its recovery path is saved in `evidence.json`. Reconnect and retrieve that file if necessary. An incomplete scenario is reported as failed.

## CI and deployment

This repository's CI runs tooling tests without an Android account. App repositories check out a pinned tooling commit in their manually triggered Play workflow and supply their own Secrets. `prepare` builds artifacts; `draft` uploads an internal draft. Production promotion is a separate explicit action after testing and declarations. Public tooling code does not require public app source or credentials.
