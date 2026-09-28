# ADR-0061 - The bridge: an observation becomes his fact only when he confirms it

**Status:** Accepted

**Date:** 2026-09-28

**Context**
Observations often contain true things about him. His screen shows "Dentist,
Friday 10am". A person sitting beside him would remember it as something they
saw, not as certain fact: it might be his partner's, an old reminder, or an
ad. A good friend would ask.

This fits the control-room model. Things stream in constantly; she processes
them and calls out what is worth it.

**Decision**

1. **Observations never silently become facts about him.**
2. **She proposes, and he confirms.** "I saw a dentist appointment on your
   screen for Friday. Is that yours?" His yes writes it into `me/` with his
   authority. His no, or no answer, leaves it an observation.
3. **Bridge questions are conversation openers.** Salience decides which
   observations are worth raising and when, the same as any other call-out
   from the control room. They never interrupt; they wait for a natural
   opening or a quiet moment.
4. **Observations fade by retention policy; his facts do not.** A person
   forgets most of what they passively saw. Guests never agreed to being
   recorded forever, and camera and ambient audio fill a disk fast. Retention
   and salience rules from Subcortical govern the observation store.
   Confirmed facts are kept until he changes them.

**Rejected**

- **Auto-promoting observations that look like facts about him.** That is the
  screen-overwrites-his-address failure, by design.
- **Never promoting observations.** It wastes the most useful thing an
  ambient observer can do: notice what he didn't think to tell her.

**Consequences**
Confirmation is his authority, applied: the same shape as ADR-0044 (a
proposal, then his decision), and the same backstop as read-back (ADR-0057).
Asking too often becomes nagging, so how often bridge questions are raised is
itself a salience setting, tuned by how he responds.
