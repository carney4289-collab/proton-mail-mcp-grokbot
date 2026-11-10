#!/bin/bash
# Prompt for the Bridge IMAP/SMTP password and store it in the login keychain.
# Nothing typed is shown. The password is not a command argument.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$DIR/lib.sh"
macos_refuse_xtrace
PY="$(macos_python)"
echo "Type the password Bridge shows for IMAP. Bridge uses that same password for SMTP."
echo "It is not your Proton account password. Nothing you type is shown."
echo "If macOS asks to use the keychain, click Always Allow."
read -r -s -p "Bridge password: " first
printf '\n'
read -r -s -p "Type it again: " second
printf '\n'
set +e
printf '%s\n%s\n' "$first" "$second" | "$PY" -u "$DIR/store_bridge.py"
status=$?
set -e
unset first second
exit "$status"
