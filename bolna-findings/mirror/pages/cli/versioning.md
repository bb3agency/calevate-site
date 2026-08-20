> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Versioning and Support Policy

> Understand the Bolna CLI beta status, the semantic versioning policy planned for 1.0, and which platforms are supported.

<Warning>
  `bolna-cli` is currently in **beta** (pre-1.0). Commands, flags, and output shapes may still change between releases — pin a version in CI if you depend on exact behavior.
</Warning>

## Versioning Policy

Once `bolna-cli` reaches 1.0, releases will follow **[Semantic Versioning (SemVer)](https://semver.org/)**: `MAJOR.MINOR.PATCH`.

**Major.** Breaking changes that are backward incompatible (renaming commands, changing flag names, changing output shapes).

**Minor.** New features that are backward compatible (new commands, new optional flags).

**Patch.** Backward-compatible bug fixes.

During beta (`0.x.y`), any release may include breaking changes — check the [Changelog](/docs/cli/changelog) before upgrading in CI.

## Platform Support

The CLI is a single static Go binary, buildable for macOS, Linux, and Windows on both `arm64` and `x86_64`.

## Best Practices

* **Check the version after upgrading** – Run `bolna version` to confirm what's installed.
* **Review the changelog before upgrading** – Skim the [Changelog](/docs/cli/changelog) for behavior changes, especially during beta.
* **Pin the version in CI** – Since `go install ...@latest` always resolves to the newest commit, pin an explicit tag or commit in CI pipelines to avoid unexpected differences across environments.

## Open Source

`bolna-cli` is open source, hosted on [GitHub](https://github.com/bolna-ai/cli). We welcome contributions — fork the repo, open a Pull Request, and we'll review it. See [Installation](/docs/cli/installation#community-contribution).
