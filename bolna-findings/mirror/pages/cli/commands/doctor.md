> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# bolna doctor

> Use the bolna doctor command to check your bolna-cli environment: config, keychain, auth, and API reachability.

Run a full health check of your `bolna-cli` environment, with an animated checklist on a real terminal.

## Syntax

```bash theme={"system"}
bolna doctor [flags]
```

## What it checks

| Check               | What it verifies                                      |
| ------------------- | ----------------------------------------------------- |
| Config directory    | Whether the config directory exists and is writable   |
| OS keychain         | Whether the platform credential store is reachable    |
| API key configured  | Whether a key is set, and where it came from          |
| Bolna API reachable | Whether `api.bolna.ai` responds                       |
| API key valid       | Whether the configured key authenticates, and as whom |
| TUI support         | Whether the current terminal supports the dashboard   |

## Flags

| Flag                  | Description                                        | Default |
| --------------------- | -------------------------------------------------- | ------- |
| `-h, --help`          | Show help for the command                          | –       |
| `-o, --output string` | Output format: `table` (animated) or `json` for CI | `table` |

## Example

```bash theme={"system"}
bolna doctor
```

```
✓ Config directory writable       ~/.config/bolna
✓ OS keychain reachable            macOS Keychain
✓ API key configured                from keychain (profile: default)
✓ Bolna API reachable               api.bolna.ai (142ms)
✓ API key valid                     authenticated as ops@acme.com
✓ Terminal supports interactive UI  xterm-256color

All checks passed.
```

## In CI

```bash theme={"system"}
bolna doctor --json | jq -e '.checks[] | select(.status != "ok")' && exit 1
```
