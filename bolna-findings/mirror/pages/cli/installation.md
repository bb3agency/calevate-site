> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Installation

> Install the Bolna CLI using go install or by building from source on macOS, Linux, and Windows, with version checks and Gatekeeper notes.

`bolna-cli` is a single static Go binary — no runtime, no interpreter, no CGO dependency. There's no Homebrew tap or prebuilt GitHub release binary yet, so these two paths are the only way to install it right now.

### go install (Recommended)

**Best for almost everyone** with [Go](https://go.dev/doc/install) installed locally — the binary is built on your machine, so it never triggers an OS code-signing warning.

```bash theme={"system"}
go install github.com/bolna-ai/cli/cmd/bolna@latest
```

This installs `bolna` into `$(go env GOPATH)/bin`.

```bash theme={"system"}
echo $PATH | tr ':' '\n' | grep "$(go env GOPATH)/bin"
```

If nothing prints, add it to your shell profile:

```bash theme={"system"}
export PATH="$PATH:$(go env GOPATH)/bin"
```

### Build from Source

**Best for contributors** or anyone who wants a specific commit, or wants to inspect the source before running it. Requires Go 1.21 or later.

```bash theme={"system"}
# 1. Clone the repository
git clone https://github.com/bolna-ai/cli
cd cli

# 2. Build the binary
go build -o bolna ./cmd/bolna

# 3. Move it onto your PATH
sudo mv bolna /usr/local/bin/bolna
```

## Verify Installation

```bash theme={"system"}
bolna version
```

<Note>
  `bolna version` prints the installed version, commit hash, and build date. `bolna-cli` is in beta — pin a version in CI if you depend on exact output shapes.
</Note>

***

## macOS: "cannot be opened because the developer cannot be verified"

This Gatekeeper warning shows up on any binary that isn't signed with an Apple Developer certificate — a one-time speed bump, not a sign anything is wrong.

<Tabs>
  <Tab title="Right-click to open">
    In Finder, right-click the `bolna` binary, choose **Open**, then confirm in the dialog. macOS remembers your choice after that.
  </Tab>

  <Tab title="Remove the quarantine flag">
    ```bash theme={"system"}
    xattr -d com.apple.quarantine bolna
    ```
  </Tab>
</Tabs>

<Tip>
  `go install` builds the binary locally, so it never picks up the quarantine attribute in the first place.
</Tip>

***

## Community Contribution

We welcome community contributions to `bolna-cli`. If you'd like to add features, fix bugs, or improve documentation:

* Visit the [Bolna CLI GitHub repository](https://github.com/bolna-ai/cli)
* Fork the repo and create a feature branch
* Open a Pull Request with a clear description of your changes and we'll review and merge it
