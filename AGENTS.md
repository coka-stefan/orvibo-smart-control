# Agent instructions

## Release version policy

- Releases are temporary diagnostic versions by default and must use a `0.x.ybN` version, for example, use `0.2.6b9` after `0.2.6b8`. Ordinary phrases such as “release,” “publish a release,” “update the version,” and “publish the latest version” all mean a temporary version.
- Only when the user explicitly says “publish a stable release” should a stable version without the `bN` suffix be used, such as `0.2.6`. Do not infer a request for a stable release from “latest,” “installable,” “HACS update,” or completed testing; when ambiguous, still use a temporary `bN` version. Discussing, quoting, or giving “publish a stable release” as an example does not constitute an actual release instruction.
- Both temporary and stable versions are published as ordinary GitHub Releases / Latest, with `Pre-release` set to `false` so HACS can detect updates. `bN` distinguishes temporary diagnostic versions; it does not indicate GitHub's Pre-release status.
- Before release, update `manifest.json`, `README.md`, `CHANGELOG.md`, and the corresponding `docs/releases/<version>.md` together. The version tag, Release name, and package version must match exactly.
- Never move or overwrite an already published version tag, Release, or package. To release new code, increment the version first: increment `bN` for a temporary version, or remove the current `bN` suffix for a stable version unless the user specified a stable version number.

## User-facing release steps

1. Run tests appropriate to the change scope and record the actual results.
2. After committing and pushing, wait for `unit-tests`, HACS validation, and hassfest to all succeed.
3. Verify that the GitHub Release is an ordinary Release / Latest and that the downloadable ZIP matches the release commit.
4. Tell the user the actual version, installation method, test results, and anything that still requires verification on real hardware.
