# ADR-0062 - Routing: context first, the model chooses, it never creates

**Status:** Accepted

**Date:** 2026-09-28

**Amends:** ADR-0059. Subject files become areas and entities, with no fixed
attribute list.

**Context**
ADR-0059 split memory into an index and subject files, and left the model to
pick which file each statement belongs in. Two problems with that:

- **Routing that depends on a model's training is not reproducible.** Swap or
  upgrade the model and the same sentence files somewhere else. Embeddings have
  the same flaw.
- **A fixed list of subjects or attributes is too narrow.** Home, work, car and
  pets cover facts about people. They do not cover most of what he actually
  talks about: architecture decisions, a new machine, a design discussion.

Deciding what a sentence is *about* is language understanding. No
deterministic process does that reliably, so routing cannot be made perfect.
The design instead makes a routing mistake cost convenience, never
correctness.

**Decision**

1. **The truth is outside routing.** The verbatim log (ADR-0063) holds every
   utterance. Areas and entity files are indexes into it. A misfiled statement
   is still in the log and still findable.
2. **Deterministic signals route first, with no model:**

   | Signal | Routes to |
   |---|---|
   | Speaker (channel, voiceprint) | `me/`, `people/<name>/`, `observations/` (ADR-0060) |
   | Time | the day |
   | The session | `sessions/<date>-<slug>`: one conversation, one record |
   | The session's active area | set when he names it ("let's work on X"), held until he changes topic or the session ends |
   | A name in the alias table | that entity's or area's file, by plain lookup |

3. **Entities are routed by who or what, never by attribute.** Everything
   about Pepper goes to Pepper's file, whatever the fact is. Attributes are free
   text inside the file. The path is computed by code from the entity's
   canonical name.
4. **Where a model is needed, it chooses from what exists.** If the signals
   leave it ambiguous, the model picks from the current list of areas and
   entities: an enumerable choice, validated by code (ADR-0046). It can never
   create an area or entity. A statement that fits nothing goes to `inbox/`,
   not to a guess.
5. **New areas come from him.** "Let's make a memory area for Sakura's
   successor" is a named tool call, `create_area(name)`. Code then:
   - turns the name into a folder (`areas/sakuras-successor/`);
   - checks the alias table and flags a clash ("Sakura" already exists as a
     separate thing) instead of merging;
   - writes `area.md` with the name, aliases, date, creator and a pointer to the
     log line where he asked;
   - adds the name to the alias table and makes it the session's active area.

   She reads it back (ADR-0057), so a misheard name is caught on the spot, and
   he can add aliases ("also call it the new machine"). Creating an area is
   harmless and reversible; the worst failure is an empty folder.
6. **Several ways in.** Every item is reachable by entity, area, session, date,
   and full-text search over the log (SQLite FTS: deterministic, and it scales to
   years of speech). No single route has to be right.
7. **Mistakes are repaired, not prevented.** The looking-back pass (ADR-0031)
   reviews the inbox and recent filings and proposes refiling. He confirms.

**Rejected**

- **Embeddings for routing.** The result changes with the model, and cannot be
  replayed or explained.
- **A fixed attribute or subject list.** Too narrow for real speech, and it
  quietly pushes everything that doesn't fit into the wrong place.
- **Letting the model create subjects.** Every model would grow a different
  filing system from the same speech.

**Consequences**
Swapping models changes extraction quality, not the filing system, and the
eval measures that quality directly. The eval also records every routing
decision with its reason (signal, alias match, or model choice), so a miss can
be traced to "wrong file" or "right file, wrong answer". Routing accuracy is
its own number.

**Open**

- Whether new areas may also come from a bridge question she raises ("this
  sounds like a new topic, keep it separately?"), confirmed by him.
- Whether what is focused on his screen is a routing signal. It is the
  strongest deterministic signal available, but it means Subcortical's view of
  his screen shapes where memory goes.
