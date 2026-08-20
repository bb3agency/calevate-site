> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Quickstart

> Quickstart guide to install the Bolna CLI, authenticate with your API key, and run your first commands in minutes.

## Step 1: Install the CLI

Requires [Go](https://go.dev/doc/install) installed locally.

```bash theme={"system"}
go install github.com/bolna-ai/cli/cmd/bolna@latest
```

See [Installation](/docs/cli/installation) for building from source instead, and for fixing a macOS Gatekeeper warning if you hit one.

```bash theme={"system"}
bolna version
```

***

## Step 2: Authenticate

```bash theme={"system"}
bolna login
```

You'll be prompted for your Bolna API key — grab one from the [Bolna Dashboard → Developers](https://platform.bolna.ai) tab. The key is validated live, then stored in your OS's native credential store.

<Tip>
  You can skip this step. Run any command that needs auth — including bare `bolna` — and it offers to log you in right there, then continues into what you originally asked for.
</Tip>

***

## Step 3: Enable Autocompletion (Optional)

Enable [autocompletion](/docs/cli/autocompletion) to get command and flag suggestions with Tab and prevent typos.

***

## You're all set!

```bash theme={"system"}
bolna agents list
```

```
NAME                    STATUS    ID
Front Desk Concierge    active    3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02
Collections Reminder    active    7b2e4f10-8a3c-4d9e-b1f2-5c9a0e6d3b47
```

Or run `bolna` with no arguments to open the [dashboard](/docs/cli/dashboard/overview) instead.
