# Startup on the Windows PC

The connector stays a normal program in the signed-in user's session. The
helpers below register a logon task for that user. They do not install a
Windows service, store a Windows password, change Tailscale ACLs, or enable
Funnel.

This starts only after that user signs in. It does not run at the lock
screen and it does not survive as a pre-login service. The machine still
has to be awake and online.

The task runs `scripts\windows\run-at-logon.ps1`. That script:

1. If `127.0.0.1:8765` is already accepting TCP, it exits without starting
   another connector and without stopping the one that is running.
2. Otherwise it waits up to 90 seconds for TCP connections to
   `127.0.0.1:1143` and `127.0.0.1:1025`. Those checks do not send IMAP or
   SMTP commands and do not read Credential Manager.
3. If Bridge is not listening by then, the script exits with an error. Task
   Scheduler retries that up to 3 times, one minute apart.
4. It sets `PYTHON_EXE` to the installed runtime
   `runtimes\Python314\python.exe` next to the package, unless
   `PYTHON_EXE` is already a full path, then it calls the existing
   `start-proton-mail-mcp.ps1`.

The task waits 45 seconds after sign-in before the script starts, so
Tailscale's automatic service and Bridge have time to come up. The task
runs only while the user is logged on (`Interactive`), at limited rights,
ignores a second start while one is still running, and has no execution
time limit because the connector is meant to keep running. The action is
Windows PowerShell 5.1. The task description does not contain the bearer
token, the Bridge password, or the account password.

Installing the task does not start it and does not stop a connector that
is already running. Removing the task does not stop that process either.
Close the existing window with Ctrl+C when you want that process to stop.

## Install, check, and remove

From the installed package
`C:\Users\skcar\AppData\Local\GrokBot\ProtonMailMCP\c28b7da-install-20261108\package\proton-mail-mcp-windows-c28b7da`:

```text
$env:PYTHON_EXE = "C:\Users\skcar\AppData\Local\GrokBot\ProtonMailMCP\c28b7da-install-20261108\runtimes\Python314\python.exe"
powershell -NoProfile -File .\scripts\windows\install-logon-task.ps1
powershell -NoProfile -File .\scripts\windows\check-startup.ps1
```

`config\windows.env` must keep `BIND_HOST=127.0.0.1`, `BIND_PORT=8765`,
and `PROTON_MCP_EXTRA_HOSTS=dell-sean.tail545f1e.ts.net`. The installer
refuses any other binding. It does not print the rest of the file.

A check that does not require signing out, and does not start a second
connector when port 8765 is already open:

```text
Start-ScheduledTask -TaskName ProtonMailMCP-Loopback
powershell -NoProfile -File .\scripts\windows\check-startup.ps1
```

Run that only while `check-startup.ps1` already reports
`connector-port 127.0.0.1:8765 open`. If the port is closed, starting the
task starts the connector. This proves the task can run and that an open
port is left alone. It does not prove the next sign-in. The next sign-in
is the first time the 45-second delay and the Bridge wait run on their own.

After that later sign-in, the protocol check is the existing one. It does
not call a mail tool:

```text
powershell -NoProfile -File .\scripts\windows\check-endpoint.ps1 -Endpoint "https://dell-sean.tail545f1e.ts.net/mcp"
```

Remove the task:

```text
powershell -NoProfile -File .\scripts\windows\remove-logon-task.ps1
```

Removal refuses a task whose action is not this package's
`run-at-logon.ps1`. Run install and remove from the installed package, not
from a different copy of the scripts.

## Bridge

Proton's supported setting is Bridge's own Settings switch, **Open on
startup**. That switch is on by default and creates Bridge's startup
entry. This repository does not read or edit Bridge's config files, and it
has not verified the switch on this PC. The logon script only waits for
the localhost IMAP and SMTP ports.

## Private Serve handover

`tailscale serve status` can say `No serve config` while a foreground
`tailscale serve` window is still the thing publishing
`https://dell-sean.tail545f1e.ts.net/mcp`. Do not treat that window as
persistent, and do not stop it until a saved config is in place and the
same URL still returns 401 without a token.

This repository does not run the handover. From the package directory,
save the current status and print the plan:

```text
powershell -NoProfile -File .\scripts\windows\plan-serve-handoff.ps1 -ReadLocalStatus
```

That writes `state\serve-status-*.txt`, `state\serve-status-*.json`, and
the command lines of `tailscale.exe` processes whose command contains
`serve` and not `funnel`. It does not change Serve and it does not stop
the Tailscale service.

When the saved status is `No serve config`, the plan's apply command is:

```text
tailscale serve --bg --set-path=/mcp http://127.0.0.1:8765/mcp
```

The rollback command, used only if that apply does not preserve the
private mount, is:

```text
tailscale serve --bg --set-path=/mcp off
```

There is no `--yes` and no `tailscale funnel`. If status is already the
exact private mount, the plan says not to apply it again. Any other
config, a root mount, a different host, or Funnel is refused.

After apply, before closing the old foreground Serve window, an
unauthenticated request to
`https://dell-sean.tail545f1e.ts.net/mcp` must still return 401. Then
close that old window with Ctrl+C. Do not stop the Tailscale service and
do not reboot. If 401 fails, run the rollback command and leave the
foreground window running if it is still open.

## What the tests cover

CI registers the task on the GitHub Windows runner, checks its principal,
delay, restart, and execution limit, and removes it. It also opens
`127.0.0.1:8765` and checks that the logon script does not launch Python
while that port is open, and that a closed Bridge port does not launch
Python. Those runs use a dummy `windows.env` and do not read Credential
Manager. They do not sign out, reboot, or contact the tailnet.
