> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Autocompletion

> Generate shell autocompletion scripts for the Bolna CLI in bash, zsh, fish, or PowerShell so you can tab-complete commands and flags without typos.

Autocomplete commands and flags with the press of <kbd>tab</kbd> to avoid typos and for ease of use.

## Shell Setup

<Tabs>
  <Tab title="Bash">
    This script depends on the `bash-completion` package. If it isn't installed already, install it via your OS's package manager.

    ### Setup completions for current shell session

    ```bash theme={"system"}
    source <(bolna completion bash)
    ```

    ### Persistent setup for all sessions

    ```bash theme={"system"}
    # Linux
    bolna completion bash > /etc/bash_completion.d/bolna

    # macOS
    bolna completion bash > $(brew --prefix)/etc/bash_completion.d/bolna
    ```

    You'll need to start a new shell for this to take effect.
  </Tab>

  <Tab title="Zsh">
    If shell completion isn't already enabled in your environment, enable it once:

    ```bash theme={"system"}
    echo "autoload -U compinit; compinit" >> ~/.zshrc
    ```

    ### Setup completions for current shell session

    ```bash theme={"system"}
    source <(bolna completion zsh)
    ```

    ### Persistent setup for all sessions

    ```bash theme={"system"}
    # Linux
    bolna completion zsh > "${fpath[1]}/_bolna"

    # macOS
    bolna completion zsh > $(brew --prefix)/share/zsh/site-functions/_bolna
    ```

    You'll need to start a new shell for this to take effect.
  </Tab>

  <Tab title="Fish">
    ### Setup completions for current shell session

    ```bash theme={"system"}
    bolna completion fish | source
    ```

    ### Persistent setup for all sessions

    ```bash theme={"system"}
    bolna completion fish > ~/.config/fish/completions/bolna.fish
    ```

    You'll need to start a new shell for this to take effect.
  </Tab>

  <Tab title="PowerShell">
    ### Setup completions for current shell session

    ```powershell theme={"system"}
    bolna completion powershell | Out-String | Invoke-Expression
    ```

    ### Persistent setup for all sessions

    Add the output of the above command to your PowerShell profile:

    ```powershell theme={"system"}
    bolna completion powershell >> $PROFILE
    ```

    You'll need to start a new shell for this to take effect.
  </Tab>
</Tabs>

***

## Flags

| Flag                | Description                                 |
| ------------------- | ------------------------------------------- |
| `--no-descriptions` | Disable completion descriptions             |
| `-h, --help`        | Show help for the specific shell completion |

## Verify your setup

```bash theme={"system"}
bolna <TAB>
bolna agents <TAB>
bolna --<TAB>
```
