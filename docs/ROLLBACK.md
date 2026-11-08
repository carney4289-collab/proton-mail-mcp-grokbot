# Rollback

This connector is a user process. It does not install a Windows service,
firewall rule, or Tailscale config. The optional logon task is separate
and is removed without stopping a connector that is still running:

```text
powershell -File scripts\windows\remove-logon-task.ps1
```

That command refuses the task when its action is not this package's
`run-at-logon.ps1`. It does not delete Credential Manager entries and it
does not change Serve. A Serve handover that was applied by hand is undone
with the rollback command saved in `docs/STARTUP.md`, not by rebooting.

1. Stop `scripts/windows/start-proton-mail-mcp.ps1` with Ctrl+C, or end that
   `python.exe` process, only when you want the current listener to stop.
   Node children for open sessions exit with it. Removing the logon task
   does not do this.
2. If Grok Bot was pointed at the endpoint, remove that MCP registration.
   That registration must not have contained the Bridge password.
3. Optional: delete the two Credential Manager entries
   `proton-mail-mcp:bridge-imap` and `proton-mail-mcp:http-auth`.
4. Optional: delete the copied `proton-mail-mcp` build directory and
   `config/windows.env`.

The Linux stdio wrapper (`scripts/proton-mail-mcp-wrapper.py`) is unchanged
in role. Stopping the Windows HTTP process does not affect a Bridge that
you leave running for other mail clients.

No public endpoint is created by these files, so there is no Funnel route
to remove.
