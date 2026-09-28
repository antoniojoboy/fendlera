# ADR-0062 - Routing: context first, the model chooses, it never invents

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
2. **A fixed top-level layout, owned by code:** `me/`, `people/`, `areas/`,
   `sessions/`, `reference/`, `observations/`, `inbox/`. The model never adds a
   folder.
3. **Deterministic signals route first, with no model:**

   | Signal | Routes to |
   |---|---|
   | Speaker (channel, voiceprint) | `me/`, `people/<name>/`, `observations/` (ADR-0060) |
   | Time | the day |
   | The session | `sessions/<date>-<slug>`: one conversation, one record |
   | The session's active area | set when he names it ("let's work on X"), held until he changes topic or the session ends |
   | A name in the alias table | that entity's or area's file, by plain lookup |
   | Continuity | at the start of a session she proposes the last active area ("carrying on with X?"); his yes sets it |

4. **Entities are routed by who or what, never by attribute.** Everything
   about Pepper goes to Pepper's file, whatever the fact is. Attributes are free
   text inside the file.
5. **Where a model is needed, it chooses from what exists.** If the signals
   leave it ambiguous, the model picks from the current list of areas and
   entities: an enumerable choice, validated by code (ADR-0046). A statement
   that fits nothing goes to `inbox/`, not to a guess.
6. **Identity is an id, never a name.**
   - Every person and area has a permanent id (`person-0007`, `area-0012`),
     fixed at creation and used by every link. File names are for reading and
     can be renamed without breaking anything.
   - Names, relationships and descriptors from his words ("Sam", "my brother",
     "from work") are aliases. One alias may point to several entities.
7. **Ambiguity is detected by code and resolved by him, never guessed.** When a
   name is looked up:
   1. One match: that entity.
   2. Several matches, but his words include a distinguishing alias ("my
      brother Sam"): that one.
   3. Several matches, and exactly one is already in this session: that one.
   4. Otherwise she asks ("Sam your brother, or Sam from work?"). Nothing about
      that entity is written until he answers. Outside a conversation, the
      statement goes to `inbox/` with every candidate attached.
8. **People are created automatically.** When he names someone new ("my brother
   Sam"), code creates the entity: the file name comes from the name in his
   words, and the alias table is checked first. If an alias matches but his
   qualifier does not ("my friend Sam" when only brother Sam exists), she asks
   whether this is a different person before creating one. When two share a
   name, both files take descriptive names (`people/sam-brother`,
   `people/sam-friend`). She reads every new person back ("New person, Sam,
   your brother?"), and silence keeps it.
9. **Areas are created automatically, with three extra guards.** A person has
   a natural boundary; a topic does not, and different models draw topic
   boundaries differently. So:
   - **The name must come from his words.** "Planning a trip to Japan" can
     create `areas/japan-trip`. A label the model invented ("travel logistics")
     cannot.
   - **New areas start provisional.** An area becomes permanent when it is used
     again in a later session. A provisional area never used again is folded
     back into `inbox/` by the looking-back pass (ADR-0031), and she tells him.
   - **Always read back:** "Started a new area, *Japan trip*." Silence keeps it;
     "that's part of the holiday plans" merges it on the spot.

   He can also create one explicitly ("let's make a memory area for Sakura's
   successor"), which is permanent immediately. Every area has an `area.md`
   with its id, name, aliases, date, creator, state (provisional or permanent)
   and a pointer to the log line it came from.
10. **Several ways in.** Every item is reachable by entity, area, session,
    date, and full-text search over the log (SQLite FTS: deterministic, and it
    scales to years of speech). No single route has to be right.
11. **Mistakes are repaired, not prevented.** The looking-back pass reviews
    the inbox and recent filings and proposes refiling and merges. He confirms.

**Rejected**

- **Embeddings for routing.** The result changes with the model, and cannot be
  replayed or explained.
- **A fixed attribute or subject list.** Too narrow for real speech, and it
  quietly pushes everything that doesn't fit into the wrong place.
- **Letting the model invent names for subjects.** Every model would grow a
  different filing system from the same speech.
- **Areas only on his explicit request.** Too much friction; he would stop
  doing it. The provisional state bounds the sprawl instead.
- **The focused screen as a routing signal.** It guesses meaning from what
  happens to be on screen, which is unpredictable. The screen stays ambient
  (ADR-0049).
- **Identifying people by name.** Two people called Sam would share a file.

**Consequences**
Swapping models changes extraction quality, not the filing system, and the
eval measures that quality directly. The eval records every routing decision
with its reason (signal, alias match, session, model choice, or asked), so a
miss can be traced to "wrong file" or "right file, wrong answer". Routing
accuracy is its own number. The eval needs new cases: two people sharing a
name, a bare ambiguous name, and a topic mentioned once and never again.
