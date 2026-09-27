# ADR-0056 - Every action reports an outcome

**Status:** Accepted

**Date:** 2026-09-28

**Context**
Actions fail in ways that look like success. `pactl set-card-profile` returns
in milliseconds while the Bluetooth link takes 2.8s to come back. A copy
command in a development session "ran" and saved nothing, because the shell
rejected the whole line on a syntax error; the error was visible and was
reported as done anyway. An agent that can say "done" when an action failed is
the failure people distrust agents for.

Raw error output cannot go straight into her context: stack traces and error
text can carry attacker-influenced content (a filename, a URL, a page title).
But hiding it loses the information she needs to explain or recover.

**Decision**
Every action, whether a named tool in Fendlera or a sink in Subtend, returns two
things.

1. **An outcome, immediately.** `ok` or `failed`, plus a reason from a fixed
   list (`device_unreachable`, `timed_out`, `rejected`, `unconfirmed`, ...).
   The sink confirms the *effect*, not that the command was accepted: a profile
   switch is `ok` when the device opens, a write is `ok` when it reads back.
2. **The full trace, as an observation.** Error output is a text stream, an
   existing Subcortical source class. It is stamped with provenance, appended
   to the record, and reaches her in the labelled block that describes the
   world and never commands (ADR-0045).

She may not report success unless the outcome is `ok`. That check is
deterministic, not her judgement.

**Reruns:**

- Actions that are harmless to repeat (reads, checks, re-opening a device) she
  may retry herself.
- Actions that may already have taken effect (sending a message, an
  announcement, a Home Assistant change) she does not retry on an ambiguous
  failure. She proposes the retry and a person confirms, the same shape as
  ADR-0044.
- Each tool records whether it is safe to repeat, alongside whether its
  arguments are enumerable (ADR-0046).
- "Fixed" is out of her reach. With no shell (ADR-0001) she cannot patch code
  or config. She calls the failure out, says what she thinks went wrong, and
  retries where allowed. The fix is the owner's.

**Consequences**
Failures enter the same loop as every other observation. The looking-back pass
sees them; an unresolved failure she reported is raised again until it
resolves, like any other unresolved item (ADR-0031). "Did that work?" always
has an answer. The full trace is kept for the owner even when she only acts on
the reason code.
