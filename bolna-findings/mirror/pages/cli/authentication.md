> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Authentication

> Set up Bolna CLI authentication using login and environment variables, including where the key is stored and the priority order the CLI uses to resolve it.

## Get Your API Key

1. Log in to the [Bolna Dashboard](https://platform.bolna.ai)
2. Go to **Developers**
3. Create a new API key or copy an existing one

## Authentication Methods

The CLI resolves authentication using this priority order:

| Priority | Method                     | When to Use                              | Duration      |
| -------- | -------------------------- | ---------------------------------------- | ------------- |
| 1        | Environment Variable       | **CI/CD pipelines, containers, servers** | Session-based |
| 2        | Stored login (OS keychain) | **Local, interactive use**               | Persistent    |

### Environment Variable

**Best for CI/CD jobs, containers, or scripts.** Define it once per session and every command uses it — no keychain lookup happens at all.

```bash theme={"system"}
export BOLNA_API_KEY="your-api-key"
```

### Stored Login

**Best for local, day-to-day use.** [`bolna login`](/docs/cli/commands/login) validates your key live, then stores it in your OS's native credential store — never in a plaintext file.

```bash theme={"system"}
bolna login
```

| Platform | Backend                    |
| -------- | -------------------------- |
| macOS    | Keychain                   |
| Linux    | Secret Service (via D-Bus) |
| Windows  | Credential Manager         |

Remove it with [`bolna logout`](/docs/cli/commands/logout).

<Info>
  **Multiple accounts?** Every auth command accepts `--profile <name>` (see [Global Flags](/docs/cli/global-flags)), so you can keep separate credentials for separate Bolna accounts side by side — `bolna login --profile client-acme`, then `bolna agents list --profile client-acme`. Omitting `--profile` uses a default profile.
</Info>

***

## Never a Dead End

Any command that needs auth — including bare `bolna` opening the dashboard — checks for credentials first. If none are configured **and you're on a real terminal**, it offers to log you in right there instead of erroring out:

```
$ bolna agents list
No API key found for profile "default".
Would you like to log in now? (y/n) y

? Bolna API key: ****************************************
✓ Verified — logged in as ops@acme.com

NAME                    STATUS    ID
Front Desk Concierge    active    3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02
...
```

It logs in, then falls straight through into the command you originally ran. In a non-interactive context (a script, a pipe, CI), this prompt never appears — it fails fast with a clear error instead, since there's no one there to answer it.

## Security Best Practices

* **Do not commit API keys** in scripts, repositories, or configuration files.
* Prefer **environment variables** in CI/CD, since the keychain isn't available in most containers.
* **Rotate API keys regularly** and scope keys to the minimum access required.

## Commands

<CardGroup cols={3}>
  <Card title="bolna login" icon="right-to-bracket" href="/docs/cli/commands/login" />

  <Card title="bolna logout" icon="right-from-bracket" href="/docs/cli/commands/logout" />

  <Card title="bolna whoami" icon="circle-user" href="/docs/cli/commands/whoami" />
</CardGroup>
