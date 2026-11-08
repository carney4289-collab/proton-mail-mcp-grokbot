# Tailscale

Nothing in this repository creates a Tailscale account, auth key, Serve
config, Funnel endpoint, or ACL. The private Serve on
`https://dell-sean.tail545f1e.ts.net/mcp` is already running from a
foreground process. `docs/STARTUP.md` is the handover plan for saving that
same mount. It does not enable Funnel and it does not change the ACL.

The connector is already bound to loopback and requires its own bearer
token. Tailscale identity headers are not treated as that token. TLS in
front of the connector does not replace the bearer check.

When that later step is authorized, the intended shape is:

1. Install Tailscale on the Windows PC and on the Grok Bot Linux box, on a
   private tailnet.
2. Use Tailscale Serve, not Funnel. Serve publishes a private HTTPS name
   and forwards it to `http://127.0.0.1:8765` on that same PC. Funnel would
   put the endpoint on the public internet. Do not enable Funnel.
3. ACL: only the Grok Bot node may connect to that Serve port. No other
   tailnet devices, and no `autogroup:internet`.
4. Confirm the `Host` header that arrives at the connector. Direct clients
   use `127.0.0.1:8765`. If Serve preserves the tailnet host name, set
   `PROTON_MCP_EXTRA_HOSTS` to that exact `name:port` and restart. This is
   a host allow-list, not authentication.
5. Register the MCP on Grok Bot with the private HTTPS URL and the static
   header `Authorization: Bearer <http-auth secret>`. The Bridge IMAP
   password stays in Windows Credential Manager.

The Windows PC must remain awake, online, and able to keep Bridge and the
connector running. Mail that Bridge decrypts is returned to the bot over
that channel, so the message contents leave the PC. Shut the connector or
the tailnet route off to stop that.
