# Local saved FPL login

Implemented and live-tested 11 September 2026. This is optional, single-user local authentication,
not a hosted credential store or permission to make transfers in the official game.

## Setup

The sibling MCP server reads this default file:

```text
/home/lewis/Workspace/fpl-mcp-server/.local/fpl-credentials.json
```

Its format is:

```json
{
  "email": "",
  "password": ""
}
```

Enter the credentials directly in a local editor. Keep valid JSON: a double quote or backslash in
a password must be escaped as `\"` or `\\`. Password whitespace is preserved. Do not paste the
contents into chat, screenshots, command-line arguments, issue reports or logs.

The directory is mode `700`, the file mode `600`, and the MCP repository ignores all of `.local/`,
including editor backups. The loader refuses symlinks, non-regular files, files owned by another
user, group/world permissions, oversized files and malformed JSON. If an editor changes permissions,
restore them with:

```bash
chmod 600 /home/lewis/Workspace/fpl-mcp-server/.local/fpl-credentials.json
```

The file is **plaintext, not encrypted**. Anyone controlling this Linux account/root or its backups
could read it. For deployment beyond this one-user machine, use an OS keyring/secret manager and
review authentication, access control and session isolation. Do not expose the local MCP service.

## Behaviour

Start the MCP, API and frontend as usual. The app's existing authentication-status check starts one
background saved-file sign-in when no session is connected. Concurrent checks/login requests join
that attempt. The MCP process reads the file directly and uses the existing FPL browser flow;
credentials do not pass through React, the FPLAgent API, an LLM or shell command arguments.

The token must successfully identify an FPL manager through `/me` before connection is reported.
The app can then sync the current squad and request a decision refresh. A fresh authentication is
not itself a fresh decision: confirm the sync and publication timestamps separately.

Missing/empty files leave the normal manual form available. Unsafe or malformed files are not
used. A failed saved-file attempt does not retry continually on each browser poll: editing/saving
the file permits another attempt, or use manual sign-in. Errors returned from saved authentication
are redacted. Existing sessions/tokens remain in memory, not in the credentials file.

This does not bypass CAPTCHA, MFA or Premier League verification. It is not a token-refresh daemon:
if an already connected session expires, reconnect through the app; the saved-file login request
can obtain a new session without retyping credentials. Clearing/removing the credentials file stops
new automatic sign-ins but does not revoke an already active session. Stop/restart MCP to clear that
in-memory session, and use the official account controls if session revocation is needed.

An operator may override the file location with `FPL_CREDENTIALS_FILE` in the MCP environment. The
same ownership/permission checks apply; never point it at a shared or publicly served file.

## Validation and implementation

- MCP implementation: `src/fpl_server/saved_login.py`; integration in `mcp_tools.py`.
- Embedded login rendering no longer resets an existing pending/successful request.
- Authentication no longer saves failure screenshots or interpolates raw browser exceptions.
- Tests cover private-file enforcement, JSON redaction, secret-free representations, missing/empty
  files, single-flight attempts, failed-attempt suppression, edited-file retry, `/me` validation,
  and preserving successful embedded-page state.
- Live test: saved-file login connected and synced all 15 players on 11 September at 08:08 BST.

```bash
cd /home/lewis/Workspace/fpl-mcp-server
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```
