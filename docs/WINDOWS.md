# Windows loopback connector

Proton Mail Bridge stays on the Windows PC. IMAP `127.0.0.1:1143` and SMTP
`127.0.0.1:1025` are not published. Grok Bot, which runs on its own Linux
box, cannot be given the Bridge password. It later reaches only an
authenticated HTTP MCP endpoint on this PC.

This repository does not install Bridge, log in, create a Windows service,
or open a firewall rule.

The Linux stdio wrapper stays the process for a Bridge on that same Linux
box. It waits on its pipes with `select()`, which cannot watch pipes on
Windows, so it is not the Windows launcher. Windows uses
`scripts/proton-mail-mcp-http.py`. Node on Windows also needs the normal
process environment (`SYSTEMROOT` in particular). Replacing that environment
makes Node abort before it speaks MCP.

## What runs where

```
Grok Bot (Linux)  -- later, private HTTPS, not set up here -->
Windows 127.0.0.1:8765  proton-mail-mcp-http.py
    bearer token from Windows Credential Manager (proton-mail-mcp:http-auth)
    Node build/index.js
        Bridge IMAP password from Credential Manager (proton-mail-mcp:bridge-imap)
        only inside the Node process environment, never on argv
    Proton Bridge on this same PC, localhost only
```

The PC has to stay awake, online, and unlocked far enough for Bridge and
this process to keep running. Message text the bot reads is decrypted by
Bridge and returned to the bot, so it leaves the PC.

Registering the 32 tools, or accepting the bearer token, does not ask a
person before send, reply, forward, draft, move, delete, flag, label,
folder, bulk, or thread calls. Asking first is an assistant rule. It is
not enforced by this process. `empty_folder` still has the upstream
`confirm: true` argument, which the client can fill in by itself.

## Build the Node server

On a machine with Node 24, Python 3, git, and npm:

```text
python scripts/build_pinned_mcp.py
```

That clones `sethbang/proton-mail-mcp` at
`db671d9592f85b3b4f4ae6c32a27021258332abc`, copies `patches/harden.ts`,
applies the five documented patches, and runs `npm ci`. Output:

```text
build/proton-mail-mcp/build/index.js
```

Copy that directory to the PC, for example
`C:\Users\YOU\AppData\Local\proton-mail-mcp\`. The `build/` tree is not
committed.

`PROTONMAIL_ALLOWED_ACTIONS=ALL` and `*` mean every mutating tool, in both
the Python policy and `harden.ts`. A comma list of real tool names still
restricts. Send tools also need `PROTONMAIL_ALLOW_SEND=true`.
`empty_folder` also needs `ALLOW_EMPTY_FOLDER=true`.

## Secrets

Two different secrets, both in Windows Credential Manager. Neither is a
parameter, an env file value, or a git object.

```text
powershell -File scripts\windows\store-credential.ps1 -Name bridge-imap
powershell -File scripts\windows\new-http-auth.ps1
```

`store-credential.ps1 -Name bridge-imap` prompts for the IMAP password
Bridge shows after login. It is not the Proton account password.
`new-http-auth.ps1` generates a separate random bearer token and stores it
as `proton-mail-mcp:http-auth`. The token is not printed, not an argument,
and not written to a file. If that credential already exists, the script
stops and leaves it unchanged. Delete it in Credential Manager yourself
before generating another. Do not point `new-http-auth.ps1` at the bridge
credential.

The connector refuses to start if either secret is missing, if the bearer
is shorter than 16 characters, or if the two values are the same. The
bearer is what a later Grok Bot registration would send. The Bridge
password is never put in that registration.

After both secrets are stored, a local check can start a temporary
loopback listener, run `initialize` and `tools/list`, and exit. It does
not send `tools/call`:

```text
powershell -File scripts\windows\check-local.ps1
```

The Node process may still make its existing non-fatal SMTP connectivity
check to `127.0.0.1:1025`. That is not a mailbox command. The check prints
the protocol version and tool names only.

## Private HTTPS check

Tailscale Serve on the PC forwards
`https://dell-sean.tail545f1e.ts.net/mcp` to `http://127.0.0.1:8765/mcp`.
This repository does not change that Serve config, the ACL, or Funnel.
`PROTON_MCP_EXTRA_HOSTS` on the running connector is what allows that Host
header. The bearer stays in Credential Manager.

To test the endpoint that is already running, without starting another
server and without reading the Bridge password:

```text
powershell -File scripts\windows\check-endpoint.ps1 -Endpoint https://dell-sean.tail545f1e.ts.net/mcp
```

The endpoint argument must be that exact URL. Certificate verification stays
on. Redirects are refused, so the bearer is not sent to another host. The
script sends one unauthenticated request, which must be rejected, then
`initialize`, `notifications/initialized`, and `tools/list`. It does not
send `tools/call`. `check-local.ps1` is unchanged and still starts a
temporary loopback server for a local-only check.

## Non-secret config

```text
copy config\windows.env.example config\windows.env
```

Edit account username, `NODE_BIN`, `MCP_JS`, and the attachment directory.
The example enables the full 32-tool surface on purpose. `config/windows.env`
is gitignored. The starter script refuses any line whose name contains
`PASSWORD`, `SECRET`, `TOKEN`, or `AUTH`.

`NODE_BIN` is the directory that contains `node.exe`, or the full path of
`node.exe` when Node is a portable copy that is not on `PATH`. A path may
contain spaces (`C:\Program Files\nodejs\node.exe`). Both
`start-proton-mail-mcp.ps1` and `check-local.ps1` load
`config\windows.env` from the package root (the folder that contains
`scripts` and `config`), not from the current directory. A non-empty
process variable already set by the caller wins. Otherwise the file value
is used. The check script also reads that same file itself, so the username
is visible even when the checker is what starts Python.

Mail hosts other than `127.0.0.1`, `localhost`, and `::1` are rejected at
startup.

## Start and stop

```text
powershell -File scripts\windows\start-proton-mail-mcp.ps1
```

The process listens on `127.0.0.1` and the port in `BIND_PORT` (8765 unless
changed). Ctrl+C stops it and closes Node children. There is no service and
no scheduled task. Rollback is in `docs/ROLLBACK.md`.

A client sends MCP Streamable HTTP `POST` to `http://127.0.0.1:8765/mcp`:

- `Authorization: Bearer <http-auth secret>`
- `Accept: application/json, text/event-stream`
- `Content-Type: application/json`
- one JSON-RPC object per POST
- the `Mcp-Session-Id` returned by `initialize` on later requests

Missing, malformed, or wrong bearer tokens get HTTP 401 and do not start
Node. `GET` (the optional 2025 server stream) returns 405. `DELETE` with
the session id closes that session's Node process. A 2025 client keeps one
Node process per `Mcp-Session-Id`. A 2026 client does not send that header,
so each of its POSTs gets its own short-lived Node process. Requests are
limited to 8 MiB. An idle published session is closed.
`Origin`, when present, must be the loopback origin. `Host` must be the
loopback host and port. Tailscale user headers are not accepted as
authorization.

`PROTON_MCP_EXTRA_HOSTS` is empty unless a later Tailscale proxy preserves a
non-loopback Host header. It does not replace the bearer token. Wildcards
and `0.0.0.0` are rejected.

## Authorization value on the clipboard

The native connector form takes the header value as a paste. This helper
copies it from Credential Manager onto the clipboard. It does not open the
form, press Add, contact the network, read `proton-mail-mcp:bridge-imap`,
or change Windows clipboard settings.

`-Confirm` is required because the current clipboard contents are replaced.
Run it only when the form is ready for that paste, and leave the window
open until it says the clipboard was cleared or left in place.

```text
powershell -File scripts\windows\copy-http-auth.ps1 -Confirm
```

`PYTHON_EXE`, when set, is the Python that reads Credential Manager. For
the installed layout that is
`C:\Users\skcar\AppData\Local\GrokBot\ProtonMailMCP\c28b7da-install-20261108\runtimes\Python314\python.exe`.
The token is not a command-line argument.

The clipboard value is the word `Bearer`, one space, and the existing
`proton-mail-mcp:http-auth` token. It stays for 45 seconds unless
`-Seconds` is set from 15 through 90. When the time ends, the helper
removes it only if the clipboard still holds that same value. A newer copy
is left alone. Closing the console window also tries to remove it when it
is still unchanged.

The copy carries the documented Windows formats
`ExcludeClipboardContentFromMonitorProcessing`,
`CanIncludeInClipboardHistory` with a DWORD of 0, and
`CanUploadToCloudClipboard` with a DWORD of 0. Those ask Windows to keep
that one copy out of clipboard history and cloud clipboard. If any of them
cannot be set, or Windows is older than Windows 10 version 1809, the
helper clears the clipboard and stops. It does not copy without them.
Windows clipboard settings are not changed. A third-party clipboard
manager can still ignore those formats.

## Grok Bot registration

The server URL is `https://dell-sean.tail545f1e.ts.net/mcp`. The header
name is `Authorization`. Paste the clipboard into the header value. Do not
put the Bridge IMAP password in the form. This repository does not submit
the form, and the helper does not fill Client ID.
