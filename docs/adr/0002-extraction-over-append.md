# ADR-0002 - Write-time extraction, not append-only transcript

**Status:** accepted

**Context**
POC 2 stored an append-only markdown transcript and loaded the whole file into
context each turn. It scored 17, 17 and 19 out of 20 against a bar of 18.

**Decision**
A second pass reads each finished turn and decides what is durable, writing a
fact line that supersedes rather than appends. The transcript is still kept,
but is never loaded into context.

**Alternatives rejected**
- Bigger context window. Does not address the cause and lost-in-the-middle
  worsens with length.
- Retrieval over the raw transcript. Correct eventually, but it would have
  been built for a failure that had not been diagnosed.

**Evidence**
Every quiz failure traced to seven facts whose memory line was immediately
followed by the assistant replying "I don't know" - because during seeding the
fact was not yet in the file, and SYSTEM told it never to guess. That denial
was then filed with the same authority as the user's own statement and, being
more recent, outranked it. Zero failures came from the other thirteen facts.

**Consequences**
Conflicts resolve once, at write time, by a process with nothing else to do -
rather than being re-derived on every read while the model is also answering.
The assistant's output is a claim; the user's statement is an observation;
append-only storage collapsed that distinction and this restores it.