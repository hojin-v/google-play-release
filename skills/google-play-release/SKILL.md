---
name: google-play-release
description: Prepare Android Google Play releases, validate signed AABs and store assets, bootstrap Play Console submissions, and automate subsequent uploads with fastlane. Use for first publication or recurring Play releases; distinguish preparation, draft upload, testing, and production rollout.
---

# Google Play release

Read the project's release configuration and [workflow](references/workflow.md), then carry the requested release through the stages that available account access permits. Keep app-specific decisions in the project's `play/` and `docs/` files rather than this skill.

1. Inspect repository instructions, working tree, application ID, version, signing setup, manifests, SDKs, external updates and network/data flows. Verify current requirements against the official sources in the workflow; never assume last year's target API or account testing requirements still apply.
2. Establish release artifacts and account prerequisites first. Ask for missing public contact details or credential **paths**, while continuing independent preparation. Never invent developer identity, testers, device-test results or declaration video URLs.
3. Build the store variant and run `scripts/release.py --project <root> prepare`. This creates a versioned package with a signed AAB, manifest, checksums and technical audit. `check --aab <path> --store` additionally requires complete listing assets and public contact/URL values.
4. For a first app, follow the Console bootstrap steps. Preserve package ID and existing key continuity. Explain the irreversible app-signing choice before the user configures Play App Signing; preparing an AAB does not choose the Google-held signing key.
5. Use the project's fastlane draft lane after bootstrap and credentials exist. Draft upload is a remote mutation; use existing session authorization, and identify exactly which app, version and track are affected. Do not infer production rollout authorization merely from a request to prepare artifacts.
6. Follow required testing and declarations before production. Record which steps actually passed and which require Console access or a physical device. After any upload error, inspect remote track state before retrying; version codes may already be consumed. Keep the same validated AAB when promoting a tested version.

Generated artifacts belong in the project, secrets belong outside version control. The validator checks technical submission properties; it does not certify policy approval or actual manufacturer-specific functionality.
