# Managed by AI Tool. This shell always runs as the unprivileged terminal user.
umask 077
export PATH="/usr/local/bin:/usr/bin:/bin"
export SHELL="/bin/bash"
export COLORTERM="truecolor"
export HISTFILE="$HOME/.bash_history"
export HISTCONTROL="ignoreboth:erasedups"
export HISTSIZE=2000
export HISTFILESIZE=4000
export PROMPT_DIRTRIM=4
export LESS="-R"

shopt -s checkwinsize histappend
stty sane 2>/dev/null || true

PS1='\[\e[38;5;72m\]\u@\h\[\e[0m\]:\[\e[38;5;75m\]\w\[\e[0m\]\$ '

alias ll='ls -alF'
alias la='ls -A'
