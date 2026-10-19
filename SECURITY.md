# Security policy

## Supported versions

Only the latest minor release of podium receives security fixes. Older
versions are not patched. Please upgrade to the latest tagged release before
reporting an issue — chances are it has already been fixed on `main`.

| Release | Supported |
| --- | --- |
| Latest minor (`v0.x` line) | Yes |
| All other releases | No |

The tagged release that matches `main` at any given moment is the only
version a maintainer will issue a fix for. Backports to older minors are not
planned.

## Reporting a vulnerability

Please report security vulnerabilities privately through GitHub Security
Advisories:

1. Open the repository's **Security** tab.
2. Click **"Report a vulnerability"**.
3. Fill in the advisory form with the steps to reproduce, the impact you
   observed, and any logs that do not contain sensitive data.

Do not file a public issue for a suspected vulnerability. A public ticket
gives attackers a head start and makes coordinated disclosure harder. GitHub's
advisory workflow keeps the report private until a fix is shipped.

If you cannot use GitHub's advisory form, contact the maintainers through the
same Security Advisories channel and request an alternate route; a maintainer
will respond with options. Email addresses are not advertised in the public
repository on purpose.

## What is in scope

Anything that affects the safety of a user's machine or their data while
running podium or its installed components. Concretely:

- **Hooks executing on the user's machine.** Any Python hook shipped under
  `plugins/podium-*/hooks/` runs as the invoking user, with the invoking
  user's privileges. Bugs in those hooks (command injection, unvalidated
  paths, unsafe deserialisation, race conditions) are in scope.
- **Installer writes.** Any path written by `install.sh`,
  `podium install`, `podium migrate`, `podium uninstall`, or `agents-upgrade`
  on the user's filesystem. Bugs that overwrite, clobber, or expose foreign
  files are in scope.
- **Secrets handling.** Anything in `podium.toml` that ends with `_*` or is
  documented as a secret, the URL expansion in §4, and the `migrate` /
  `state` paths that handle credentials. Mishandling of these — writing them
  to logs, surfacing them in error messages, embedding them in rendered
  files — is in scope.
- **Configuration overwrite.** Cases where podium writes a path or JSON
  pointer it does not own (capability-parity violations from §1.2 of
  `docs/ARCHITECTURE.md`) are treated as security issues, not just bugs.

Things that are **not** in scope:

- Bugs in upstream tools podium does not control (Claude Code, OpenCode,
  MCP servers, the Python interpreter).
- Reporter-controlled environments, including the contents of the user's own
  hooks, overlays or `podium.toml`.
- Theoretical attacks that require the attacker to already have shell access
  to the user's account.

When in doubt, report it. A report that turns out to be out of scope is
always welcome — it helps us tighten the definition over time.

## Response expectations

podium is volunteer-maintained. Best-effort targets:

- **Initial acknowledgement.** Within 7 days of your advisory submission, a
  maintainer will reply to confirm the report and ask any clarifying
  questions.
- **Triage.** After acknowledgement, the maintainer will decide whether the
  issue is in scope, assess severity, and share a rough plan. Another
  message in the same thread is the expected vehicle.
- **Fix.** A patch or upgrade instruction is best-effort, prioritised by
  severity and reachability. There is no SLA.
- **Credit.** If you want it, credit for the report will appear in the
  release notes once the fix ships, alongside the standard thank-you.

If 14 days pass with no acknowledgement on an advisory, feel free to ping the
maintainers in a non-public channel (e.g. a new advisory comment referencing
the original). Public bump threads belong in Discussions, not as comments on
the advisory.

## Scope of the policy itself

This policy applies to the podium source tree at
<https://github.com/davalmeyda/podium>. It does not extend to plugins
maintained outside this repository and distributed via the marketplace,
although we strongly encourage them to follow the same approach.
