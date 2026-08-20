> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Log in with the Bolna CLI

> Use the bolna login command to authenticate and store your API key in the OS credential store.

Authenticate and store your API key in your OS's native credential store. See [Authentication](/docs/cli/authentication) for how storage and profiles work.

## Syntax

```bash theme={"system"}
bolna login [flags]
```

On a real terminal, this opens an interactive form with a masked input for your API key. The key is validated live before anything is saved.

## Flags

| Flag               | Description                                            | Default |
| ------------------ | ------------------------------------------------------ | ------- |
| `-h, --help`       | Show help for the command                              | –       |
| `--api-key string` | Pass the key directly, skipping the interactive prompt | –       |

Plus the [global flags](/docs/cli/global-flags) — `--profile` in particular.

## Example

```bash theme={"system"}
bolna login
```

```
? Bolna API key: ****************************************
✓ Verified — logged in as ops@acme.com
```

```bash theme={"system"}
# Non-interactive, for CI
bolna login --api-key "$BOLNA_API_KEY"

# Log in to a second, named profile
bolna login --profile client-acme
```

<Tip>
  You rarely need to run this at all — any command that needs auth and finds none offers to log you in inline. See [Never a Dead End](/docs/cli/authentication#never-a-dead-end).
</Tip>
