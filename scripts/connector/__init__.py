"""Loopback HTTP connector for the patched proton-mail-mcp stdio server.

The Bridge IMAP password stays in an OS secret store and is placed only in
the local Node child's environment. Callers authenticate with a separate
bearer token. Registering tools is not approval to use them.
"""
