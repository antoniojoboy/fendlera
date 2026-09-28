# ADR-0063 - A sharded log, derived stores, and files he can edit

**Status:** Accepted

**Date:** 2026-09-28

**Context**
Every earlier memory POC kept its log as one growing file. One bad write, a
crash mid-append or a bug in her own code could corrupt or lose all of it.

He also needs to change memory by hand: fix names Whisper got wrong ("nor" for
Noor), strike background noise and accidental speech, create files, and edit
anything in Obsidian (ADR-0005). That conflicts with memory being rebuilt from
the log: a rebuild would wipe his edits unless they are captured.

**Decision**

1. **The log is sharded by day and source:** `log/2026/09/28.jsonl`. A bad
   write can only touch today's file.
2. **One self-contained line per record,** with id, time, speaker, session,
   text and its own checksum. A corrupt line loses that line only. A
   half-written last line after a crash is detected and set aside, never trusted.
3. **Everything else is derived and can be rebuilt:** entity and area files,
   the index, the alias table, the search database. If any of them is damaged,
   replaying the log regenerates it. The log is the only thing that cannot be
   recreated.
4. **Derived files are written atomically:** write a temporary copy, then
   rename it into place. A crash leaves the old version, never half a file.
5. **Every fact records the log lines it came from.** That makes corrections
   precise.
6. **He can edit any file.** She detects the change by its hash, records the
   diff in the log as `source: owner, channel: file edit`, and carries on. His
   edits are part of history at owner authority, and a rebuild replays them.
7. **Transcript corrections keep the original.**
   - A fix ("nor" to "Noor") is stored as a correction beside the original line.
     Answers and the quote check use the corrected text.
   - Noise and accidental speech are **struck**, not deleted: marked void,
     excluded from facts and answers, still visible in history.
   - He can do both by voice ("that was the TV, ignore it" strikes the last
     line) or by editing the day's file.
   - Facts built from a corrected or struck line are re-extracted. Only those;
     nothing else is touched.
8. **The memory folder is versioned with git.** She commits her own writes.
   His edits are committed and labelled "owner edit" when detected. Nothing is
   ever unrecoverable.

**Rejected**

- **One log file.** A single corruption or miswrite can lose everything.
- **A hash-chained, sealed log.** It makes any edit break the chain, which is
  the opposite of what he needs. On one machine an edit cannot be proven to be
  his anyway: his hand, her buggy code and a malicious process look the same to
  the filesystem. What can be guaranteed is that every change is recorded and
  reversible, and git does that.
- **Read-only memory files.** Hand-editing is a requirement, not a loophole.

**Consequences**
Backups need to cover only the log, since everything else is rebuildable.
Backups themselves are deferred. Change detection runs at startup and on file
events, so an edit made while she is off is still picked up and logged.
