# Rollback

This connector is a user process. It does not install a Windows service,
scheduled task, firewall rule, or Tailscale config.

1. Stop `scripts/windows/start-proton-mail-mcp.ps1` with Ctrl+C, or end that
   `python.exe` process. Node children for open sessions exit with it.
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
