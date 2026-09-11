"""Shell completion scripts are printed, never installed into startup files."""

COMMANDS = (
    "run status watch tui menubar daemon service pool map unmap sessions resume health config "
    "mcp job completion login import-claude add-codex list doctor history enable disable"
)


def script(shell: str) -> str:
    words = COMMANDS + " claude codex --account --pool --strategy --threshold --json --cached"
    if shell == "bash":
        return f"""_agent_rotate_complete() {{
    local cur="${{COMP_WORDS[COMP_CWORD]}}" prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    local words='{words}'
    if [[ "$prev" == --account ]]; then
        words="$(agent-rotate list --names 2>/dev/null)"
    elif [[ "$prev" == --pool ]]; then
        words="$(agent-rotate pool list --names 2>/dev/null)"
    fi
    COMPREPLY=( $(compgen -W "$words" -- "$cur") )
}}
complete -F _agent_rotate_complete agent-rotate
"""
    if shell == "zsh":
        return f"""#compdef agent-rotate
_agent_rotate() {{
    local -a choices
    if [[ "$words[CURRENT-1]" == --account ]]; then
        choices=("${{(@f)$(agent-rotate list --names 2>/dev/null)}}")
    elif [[ "$words[CURRENT-1]" == --pool ]]; then
        choices=("${{(@f)$(agent-rotate pool list --names 2>/dev/null)}}")
    else
        choices=({words})
    fi
    _describe 'Agent Rotate' choices
}}
compdef _agent_rotate agent-rotate
"""
    if shell == "fish":
        return f"""complete -c agent-rotate -f -a '{COMMANDS} claude codex'
complete -c agent-rotate -l account -r -a '(agent-rotate list --names 2>/dev/null)'
complete -c agent-rotate -l pool -r -a '(agent-rotate pool list --names 2>/dev/null)'
complete -c agent-rotate -l strategy -r -a 'sticky consume-first ordered'
"""
    raise ValueError("Choose bash, zsh, or fish")
