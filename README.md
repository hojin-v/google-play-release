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
# Only after an explicit production release request:
google-play-release/bin/play-fastlane --project ./your-app android release aab:build/release.aab rollout:1.0
google-play-release/bin/play-fastlane --project ./your-app android status output:build/play-status.json
```

Python 3.11+, JDK 17, the Android SDK and the project's Gradle wrapper are required. Fastlane additionally needs Ruby/Bundler (`bundle install` in this repository). `PLAY_RUBY_ROOT` supports an existing portable local Ruby runtime. Signing and service account files stay outside Git.

## Store preview automation

Device screenshots remain supported by `tools/capture_play_screenshots.sh`. For an explicitly chosen HTML preview workflow, set `screenshot_config` in the app's release JSON to a project-owned scene configuration. It names the self-contained preview page, locale, device description, source files, capture selector, control actions and 2–8 ordered PNG filenames. Keep app-specific markup, device presets and illustrative system UI labels in the app repository.

```bash
npm ci --prefix google-play-release
(cd google-play-release && npx playwright install chromium)
google-play-release/bin/play-screenshots --project ./your-app generate
google-play-release/bin/play-screenshots --project ./your-app check
```

The generator captures the entire selected frame, converts it to opaque 1080×1920 RGB PNG, and records source fingerprints and ordered image hashes in the configured manifest. `prepare` regenerates the images; store audits reject stale or changed images and extra old screenshots. Raw captures remain under the app's ignored `build/play-captures/` for visual review. `PLAY_CHROMIUM_EXECUTABLE` can select an existing compatible local Chromium. Browser previews are not real-device validation. Use explicit example labels for reconstructed system settings or notifications.

For the first app, create it and save its first AAB in Play Console before API uploads. A draft is not a published test or production release. The [skill](skills/google-play-release/SKILL.md) and [workflow](skills/google-play-release/references/workflow.md) describe the full process.

## App-specific declaration questions

```bash
google-play-release/bin/play-declarations --project ./your-app interview
# For an agent/UI: render the pending titles, guidance and choices, then record the reply.
google-play-release/bin/play-declarations --project ./your-app questions --json
google-play-release/bin/play-declarations --project ./your-app answer --id pricing --value free --source user
google-play-release/bin/play-declarations --project ./your-app status --json
```

The guided terminal interview has no default answers. It saves each explicit response in the app's `play/declarations.json`, retains skipped questions, resumes after interruption, and asks conditional follow-ups for data handling, accounts, restricted access, regulated features and foreground services. `answer --file /path/to/answers.json --source console` accepts a JSON object mapping question IDs to verified values; a batch is validated before saving. Sources distinguish user decisions, operator input, code inspection and actual Console values. Package checks prevent accidentally reusing another app's answers. Countries, pricing and target audience cannot be decided from code.

Production `promote` runs `status --require-complete` before accessing Play. Missing facts stop promotion so the caller can collect answers; internal draft preparation remains available. Promotions use the same commit policy that refuses to cancel an existing review. Facts must be revisited when an app's features, SDKs or service operation change.

An agent should ask only for facts it cannot establish from this app's existing instructions or evidence, using the available interactive user-input tool. These questions do not submit forms or replace the current Console questionnaires, IARC rating, SDK/data audit, account testing requirements or policy review. No credentials belong in the answer file. Conditional features can require additional Console questions or evidence beyond these initial facts.

## Real Android video automation

Connect and authorize an unlocked test device, install the exact APK to demonstrate, and supply an app-specific JSON scenario. The runner uses actual app/system UI controls, records on the device, verifies foreground service start/stop through `dumpsys`, and produces `raw.mp4`, `captioned.mp4`, `captions.srt`, screenshots and `evidence.json`.

```bash
python3 google-play-release/tools/setup_video_tools.py  # Linux x86_64 FFmpeg; optional if installed
python3 google-play-release/tools/capture_android_video.py \
  --config your-app/play/video-scenario.json --serial DEVICE_SERIAL \
  --output your-app/build/play-video/run-001
```

ADB selection: `--adb /path/to/adb` and `--adb-port 5037`. WSL can call Windows `adb.exe` directly, including another server port. `--reset-app` explicitly erases only the configured test app's data. `--emulator-setup` enables developer options only on an emulator and fails on a physical phone. A recording run never grants the app secure-setting permissions or invents pairing success. Only the scenario's own recorder PID can be stopped.

Each step has `action`, `caption`, optional `hold` seconds, and action-specific fields. Actions: `launch`, `tap` (`selector` using actual UI attributes, optional `optional`/`timeout`), `notifications`, `swipe` (`coordinates`), `back`, and `service` (`active`). The configuration also specifies `name`, `package`, launcher `component`, `service`, integer `service_type`, the evidence `scope` and optional `video_caption`. Captions identify emulator vs physical-device footage throughout the actual MP4 duration. Step timings stay in the evidence log because encoder time can differ from the host clock. Refine selectors when a manufacturer uses different system UI.

The current built-in recorder has no audio. It can prove actual UI/FGS lifecycle; it cannot establish manufacturer camera behavior. ADB loss can interrupt UI automation; the on-device recorder remains bounded to 170 seconds and its recovery path is saved in `evidence.json`. Reconnect and retrieve that file if necessary. An incomplete scenario is reported as failed.

## CI and deployment

This repository's CI runs tooling tests without an Android account. App repositories check out a pinned tooling commit in their manually triggered Play workflow and supply their own Secrets. `prepare` builds artifacts; `draft` uploads an internal draft. Explicit `release` submits a new validated production AAB and listing together, while `promote` reuses an existing internal version without rebuilding. Both use an explicit rollout fraction and require completed app facts. Remote snapshots run before and after mutations, including upload errors. Neither a successful API commit nor a completed track proves review approval/public availability. Public tooling code does not require public app source or credentials.
