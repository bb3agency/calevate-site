> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Global Flags

> Reference for global flags in the Bolna CLI like output, no-color, profile, verbose, and quiet available with every bolna command.

## Available Flags

| Flag                  | Default   | Env Var    |
| --------------------- | --------- | ---------- |
| `-h, --help`          | –         | –          |
| `-o, --output string` | `table`   | –          |
| `--json`              | Disabled  | –          |
| `-n, --no-color`      | Disabled  | `NO_COLOR` |
| `--profile string`    | `default` | –          |
| `-v, --verbose`       | Disabled  | –          |
| `-q, --quiet`         | Disabled  | –          |

## Syntax and Example Usage

### --help, -h

Show help information for any command.

```bash theme={"system"}
bolna --help
bolna agents --help
bolna agents list --help
```

### --output, -o

**string**\
Default `table`. Output format: `table`, `json`, or `csv`. Use `json` or `csv` when piping results to other tools or scripts, and `table` for human-friendly interactive use.

```bash theme={"system"}
bolna agents list --output json | jq -r '.[].id'
bolna agents list -o csv > agents.csv
```

### --json

Shorthand for `--output json`.

```bash theme={"system"}
bolna whoami --json | jq -r '.balance_usd'
```

### --no-color, -n

By default, output is colored. Disable colors when piping results to scripts, log files, or CI systems where ANSI codes may cause issues. Can also be set globally via the `NO_COLOR` environment variable.

```bash theme={"system"}
bolna --no-color agents list

# Set globally via environment variable
export NO_COLOR=1
```

<Note>
  You rarely need this flag directly — output is already plain and colorless whenever it isn't attached to a real terminal (a pipe, a redirect, or CI). `--no-color` is for forcing that on a real terminal too.
</Note>

### --profile

**string**\
Default `default`. Named credential profile to use — see [Authentication](/docs/cli/authentication#stored-login).

```bash theme={"system"}
bolna agents list --profile client-acme
```

### --verbose, -v

Verbose logging — request timing, retries, and underlying API calls. Useful when troubleshooting.

```bash theme={"system"}
bolna agents list --verbose
```

### --quiet, -q

List commands only. Prints just the bare ID of each row, one per line, nothing else — built for piping into `xargs`.

```bash theme={"system"}
bolna agents list -q | xargs -I{} bolna agents view {}
```
