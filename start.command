#!/bin/sh
cd "$(dirname "$0")" || exit 1
sh ./start.sh "$@"
result=$?
if [ "$result" -ne 0 ]; then
    printf '%s' 'Press Enter to close / Нажмите Enter, чтобы закрыть: '
    read -r reply
fi
exit "$result"
