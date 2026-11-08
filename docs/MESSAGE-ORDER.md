# Message list order and read flags

Evidence from the patched `sethbang/proton-mail-mcp` source at
`db671d9592f85b3b4f4ae6c32a27021258332abc`, plus `patches/list-date-order.patch`.
This is not a claim about why one live mailbox returned a particular five
messages.

## What the previous list did

`list_messages` searches the folder for UIDs, then `fetchSortAndLimit`
sorted by the envelope Date header. When the search returned more than 500
UIDs, only `uids.slice(-500)` was fetched. The tool text still said the
list was newest by date. `search()` order in this code is treated as
ascending UID order, so that slice is the highest 500 UIDs, not the newest
Dates.

UID 5357 is 504 below UID 5861. If every integer UID from 5362 through 5861
exists, 5357 is outside that 500-UID window and the old cap cannot be why
5357 was returned. It can be returned if the folder has 500 or fewer
messages, or if UID gaps put 5357 inside the highest 500 existing UIDs.
Which of those is true is not in this repository.

The Jan 2022 dates in that result are not evidence that messages moved
between the two list calls. A second list with the same flags is consistent
with the same selection. `\Recent` disappearing is the IMAP session flag:
each `listMessages` opens its own connection and logs out, and `\Recent` is
not stored by this client.

## What the patch changes

`fetchSortAndLimit` fetches an envelope for every UID from the search, in
chunks of 200, then sorts by the Date header and keeps `limit`. A low UID
with a newer Date stays in the result when the folder has more than 500
UIDs. `sortByUid` is still arrival order, not date order.

## What a read does

`read_message` loads flags, envelope, and body structure with `fetchOne`,
then downloads the part through imapflow `download`. imapflow 1.x builds
body fetches as `BODY.PEEK` (`node_modules/imapflow/lib/commands/fetch.js`,
`setBodyPeek`). The service test `readMessage never calls messageFlagsAdd /
messageFlagsRemove` still passes. This client does not send a flag STORE
and has no mark-as-read argument.

Whether Proton Bridge honors `BODY.PEEK` is not proven here.

## What "backend failure" is

That string is written by `scripts/connector/http_gateway.py` when the
stdio exchange throws. The tool's own failure text is `Failed to read
message: ...`. A response that says only `backend failure` did not come
from that tool catch. `BackendError` now returns its own fixed text
(`backend timed out`, `backend exited`, and the pipe error class). Any
other exception stays `backend failure` and is not copied, so a secret in
an unexpected exception is not returned. Which of those happened for UID
5359 is not in this repository.

## Files to replace

Only these compiled files, next to the installed `MCP_JS` `index.js`:

- `build/index.js`
- `build/imap-service.js`

And, for the clearer gateway error, `scripts/connector/http_gateway.py` in
the package. Leave Node, Python, `config\windows.env`, both Credential
Manager entries, the logon task, and Tailscale Serve as they are.

Back up the two compiled files and `http_gateway.py` before replacing them.
To roll back, copy those backups back. The running connector keeps the
code it already loaded until that process is restarted. This package does
not restart it.
