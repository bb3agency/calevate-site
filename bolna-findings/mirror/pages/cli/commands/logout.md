> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Log out with the Bolna CLI

> Use the bolna logout command to remove the stored API key for the active profile.

Remove the API key stored for the active profile from your OS credential store. Doesn't revoke the key on the Bolna platform — it only forgets it locally.

## Syntax

```bash theme={"system"}
bolna logout [flags]
```

## Flags

Only the [global flags](/docs/cli/global-flags) apply — use `--profile` to log out of a specific profile.

## Example

```bash theme={"system"}
bolna logout
```

```
✓ Logged out of profile "default"
```

```bash theme={"system"}
bolna logout --profile client-acme
```

<Note>
  If `BOLNA_API_KEY` is set in your environment, commands keep using it even after `bolna logout` — the environment variable always takes priority. Unset it separately to fully de-authenticate the shell.
</Note>
