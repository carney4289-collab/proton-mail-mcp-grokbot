# macOS loopback connector

Proton Mail Bridge stays on the Mac mini. IMAP `127.0.0.1:1143` and SMTP
`127.0.0.1:1025` are not published. Grok Bot reaches only
`https://seans-mac-mini.tail545f1e.ts.net/mcp`, and only with the bearer
token. Tailscale Funnel is not used.

This is the same connector as the Windows path: loopback HTTP on
`127.0.0.1:8765/mcp`, the same patched Node server, and the same policy.
The process defaults still hide mutation until `config/macos.env` opts in.
The installed example opts in to the full 32-tool list on purpose, matching
`config/windows.env.example`. Listing a tool is not approval to send, move,
delete, or otherwise change mail.

The Mac this was written for is Apple Silicon, macOS 27, user `seancarney`,
with no Homebrew and no Node already installed. Bridge 3.27.1 is already
signed in and set to open at login. Tailscale 1.104.5 is already logged in
to `tail545f1e.ts.net`. These scripts do not change Bridge's settings.

## What runs where

```text
Grok Bot  -- private HTTPS, tailnet only -->
Mac 127.0.0.1:8765  proton-mail-mcp-http.py
    bearer token from the login Keychain (proton-mail-mcp:http-auth)
    Node build/index.js
        Bridge password from the login Keychain (proton-mail-mcp:bridge-imap)
        used for both IMAP and SMTP, only inside the Node process
    Proton Bridge on this same Mac, localhost only
```

The login Keychain is the trust boundary. While you are signed in and the
keychain is unlocked, programs running as you can read those two items.
They are not files in this repository. The Mac has to stay awake, online,
and signed in. The LaunchAgent does not run at the login window before you
sign in. Message text the bot reads is decrypted by Bridge and returned to
the bot, so it leaves the Mac.

## Install, one step at a time

Open **Terminal** from Applications. Do not use SSH. The Tailscale app CLI
often fails from an SSH-like shell with `The Tailscale GUI failed to start:
Tailscale.CLIError error 3`.

Paste one block, press Return, and wait until it finishes.

1. Download this branch.

```bash
mkdir -p "$HOME/Library/Application Support/ProtonMailMCP"
cd "$HOME/Library/Application Support/ProtonMailMCP"
curl -fsSL -o proton-mail-mcp.tar.gz "https://github.com/carney4289-collab/proton-mail-mcp-grokbot/archive/refs/heads/cursor/macos-launchagent-48a9.tar.gz"
tar -xzf proton-mail-mcp.tar.gz
rm -rf package
mv proton-mail-mcp-grokbot-cursor-macos-launchagent-48a9 package
rm proton-mail-mcp.tar.gz
```

2. Install a self-contained Python and Node, build the connector, and write
   `config/macos.env`.

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/install.sh"
```

   Python comes from the uv standalone binary
   (`uv` 0.13.7), which downloads CPython 3.12 into
   `~/Library/Application Support/ProtonMailMCP/runtimes`. Apple's
   `/usr/bin/python3` is not used to run the connector. Node is the official
   darwin-arm64 tarball for 24.22.1, the same major line the tests use.
   Neither install uses Homebrew or sudo. The script asks for the Proton
   account email. That is not a password.

3. Store the Bridge password in the login Keychain.

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/store-bridge.sh"
```

   Type the password Bridge shows for IMAP. Bridge uses that same password
   for SMTP, so there is one prompt, not two. It is not the Proton account
   password. The characters are not shown, and the password is not a
   command-line argument.

4. Generate the bearer token into the Keychain. It is not printed.

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/new-http-auth.sh"
```

   If that item already exists, the script stops and leaves it unchanged.
   Delete `proton-mail-mcp:http-auth` yourself in Keychain Access before
   generating another. Do not delete `proton-mail-mcp:bridge-imap` to do
   that.

5. Bridge's **Open at login** switch is yours. These files do not read or
   edit Bridge's settings and they do not report the switch as on. The
   login helper only waits until TCP connections to `127.0.0.1:1143` and
   `127.0.0.1:1025` succeed. Those checks do not send IMAP or SMTP commands.

6. Install the per-user LaunchAgent.

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/install-agent.sh"
```

   The label is `local.proton-mail-mcp.loopback`. It is `RunAtLoad`, with
   `KeepAlive` so a crash is restarted, and a 10 second throttle so a
   failure does not spin. If `127.0.0.1:8765` is already open, the helper
   exits and does not start a second connector. Logs:

```text
~/Library/Logs/ProtonMailMCP/connector.out.log
~/Library/Logs/ProtonMailMCP/connector.err.log
```

7. Status.

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/status.sh"
```

   Expect `agent: loaded`, `connector-port 127.0.0.1:8765 open`,
   `bridge-imap-port 127.0.0.1:1143 open`, and
   `bridge-smtp-port 127.0.0.1:1025 open`. This check does not read the
   Keychain and does not change Tailscale.

8. Save the Tailscale Serve handler. This is the only Serve change the
   script will make, and only when the current config is empty or is
   already exactly this `/mcp` proxy:

```text
tailscale serve --bg --https=443 --set-path=/mcp http://127.0.0.1:8765/mcp
```

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/apply-serve.sh"
```

   There is no `tailscale funnel` and no Serve reset. Any other handler
   makes the script stop without changing Tailscale.

9. Confirm an unauthenticated request is rejected. No token is sent.

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/check-endpoint.sh"
```

   Success looks like this. A status of 403 means the Host header did not
   match this Mac's name. Leave `PROTON_MCP_EXTRA_HOSTS` as `install.sh`
   wrote it.

```text
endpoint https://seans-mac-mini.tail545f1e.ts.net/mcp
unauth 401
```

10. When the Grok Bot form is ready for the header value:

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/copy-http-auth.sh" --confirm
```

    The clipboard value is the word `Bearer`, one space, and the token. It
    is marked concealed and transient, and it is limited to this Mac so it
    is not offered to Universal Clipboard. If those marks cannot be set, the
    clipboard is cleared and nothing is left on it. The value stays for 45
    seconds unless you copied something newer. The script does not read the
    Bridge password and does not submit the form.

    Server URL: `https://seans-mac-mini.tail545f1e.ts.net/mcp`

    Header name: `Authorization`

    Do not put the Bridge password in the form.

## Prompts you have to answer

- **Keychain, twice.** Storing the Bridge password and generating the token
  can each show "python wants to access the keychain" or similar. Click
  **Always Allow**. The items are also given an access list that lets
  programs running as you read them without a later prompt, so the login
  helper can start while you are not at the keyboard. If that access list
  cannot be saved, the script says so, and a later start may ask again.
- **Login Keychain locked.** macOS asks for the Mac login password. That
  unlocks the keychain. It is not the Proton password and not the Bridge
  password.
- **Tailscale Install CLI.** Only if `apply-serve.sh` says the GUI failed
  to start. The menu bar Tailscale icon has **Install CLI**. macOS may ask
  for the Mac login password to put `tailscale` in `/usr/local/bin`. Run
  `apply-serve.sh` again after that. Prefer Terminal.app on the Mac over
  SSH either way.
- **No sudo** for Python, Node, the LaunchAgent, or the Keychain items.
  The Tailscale CLI install is the one step that may ask for an admin
  password, and only if you choose Install CLI.

## Tailscale CLI

The file `/Applications/Tailscale.app/Contents/MacOS/Tailscale` is the app.
From a non-GUI shell it can exit with `Tailscale.CLIError error 3` before
it talks to the tailnet. The scripts try, in order:

1. `TAILSCALE_BIN`, if you set it to a full path
2. `/usr/local/bin/tailscale` (what Install CLI provides)
3. `/opt/homebrew/bin/tailscale` (not expected on this Mac)
4. the app binary, last

A GUI failure prints those steps and does not keep retrying.

## Undo

Stop the connector and remove the login helper. Keychain items, Bridge, and
Tailscale are left as they are.

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/uninstall-agent.sh"
```

Remove only the `/mcp` handler on HTTPS port 443:

```bash
bash "$HOME/Library/Application Support/ProtonMailMCP/package/scripts/macos/rollback-serve.sh"
```

That runs `tailscale serve --https=443 --set-path=/mcp off` only when every
`/mcp` proxy points at `http://127.0.0.1:8765/mcp` and Funnel is off. Other
handlers are not reset. If `/mcp` points somewhere else, the script stops
and changes nothing.

To delete the secrets later, open Keychain Access, select the login
keychain, and remove `proton-mail-mcp:bridge-imap` and
`proton-mail-mcp:http-auth`. The scripts do not do that.

## What the tests cover

CI on a macOS runner checks `bash -n` for `scripts/macos/*.sh`, runs
`plutil -lint` on a generated LaunchAgent plist, and runs the unit tests.
Those tests check the plist keys (`RunAtLoad`, `KeepAlive`, the 10 second
throttle, logs under `Library/Logs`), the Serve apply and rollback command
lists, the 401 rules, and that a planted password is absent from script
output. A separate test on macOS creates a temporary keychain file and
round-trips a dummy value. CI does not call the live tailnet, does not read
Sean's login Keychain, and does not enable Funnel.
