> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# CLI Changelog

> Browse the Bolna CLI changelog for release notes covering new commands, bug fixes, and breaking changes across every beta version.

The Bolna CLI Changelog tracks every release — new commands, bug fixes, and breaking changes. The [GitHub Releases page](https://github.com/bolna-ai/cli/releases) is the authoritative source; this page summarizes each one in the same format.

## Release History

<AccordionGroup>
  <Accordion title="v0.2.0 — Docs from the terminal" icon="book" iconType="solid">
    Adds a new **Utility** command group for reading Bolna's own documentation — no `bolna login` or API key required.

    * `docs search <query>` — search Bolna's documentation index (`llms.txt`) by title, description, and path, ranked best-match-first
    * `docs fetch <page>` — fetch one documentation page as rendered Markdown, accepting a bare path, a path with `.md`, or a full URL
    * `doctor` moves into the same **Utility** group, alongside `version` — it doesn't touch account data either
  </Accordion>

  <Accordion title="v0.1.0 — Initial Beta" icon="flask" iconType="solid">
    First public beta of `bolna-cli`.

    * `agents` — `list`, `view`, `create`, `update`, `delete`
    * `call start`, `calls list`, `calls view`
    * `numbers list`, `batches list`
    * `login`, `logout`, `whoami`
    * `doctor`, `version`, `completion`
    * Full-screen dashboard (`bolna` with no arguments), built on the [Charm](https://charm.sh) TUI stack
  </Accordion>
</AccordionGroup>

<Note>
  `bolna-cli` is pre-1.0 — expect breaking changes between beta releases. See [Versioning](/docs/cli/versioning) for what to expect and how to pin a version in CI.
</Note>
