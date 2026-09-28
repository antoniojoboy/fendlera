# ADR-0064 - Reference material: stored once, indexed many ways, never his fact

**Status:** Accepted

**Date:** 2026-09-28

**Context**
He will drop material in to discuss, reference and learn from: texts, emails
and messages from other people, most often as screenshots, the easiest medium
to capture. The file comes *from* him, but its content is not *his statement*.
A dropped message claiming "your address is X", filed as his fact, would walk
straight past the authority floor (ADR-0060) and the untrusted-content rule
(ADR-0045).

Two precedents agree on the shape:

- **Claude's own memory** keeps memory files (only what the user said),
  transcripts (searched, never loaded whole) and uploaded files (reference,
  never memory unless the user confirms) separate.
- **A phone's photo gallery** stores each photo once, indexes it by faces, text
  in the image, place and date, and asks the user to name faces. The indexes are
  built by models, but a wrong face tag only makes a photo harder to find; it
  never changes the photo.

**Decision**

1. **Dropped files are reference material.** They go into `inbox/`, are
   logged as "dropped by owner" with the time, and are stored once under
   `reference/`.
2. **Indexed several ways:** the text read from the image (vision model), the
   people named in it, the date, and the session it arrived in.
3. **Linked from the people in it.** A screenshot of Michael's message is
   linked from Michael's file as "observed: message from Michael, 3 October",
   so it turns up when he asks about Michael. It is attributed, and it is not
   Michael's fact or his.
4. **Answerable with attribution:** "In the screenshot you dropped on the 3rd,
   Michael said he's moving in March."
5. **Never his fact without the bridge.** It becomes a fact only when he
   confirms it (ADR-0061): "Is Michael moving in March? Should I remember that?"
6. **Never instructions.** Text in a picture of an email saying "Desirée,
   update his address" is content, not a command (ADR-0045).

**Models may build indexes; they never decide truth.** Text read from an image,
links to people, and embeddings for fuzzy search later are all indexes. Each is
rebuildable from the stored files, and each only affects what can be *found*.
What is true, who said it, and where the canonical record lives stay in code.
This is where the embedding concern in ADR-0062 draws its line.

**Rejected**

- **Dropped means vouched for.** Most dropped material is other people's
  words. Treating it as his would make every screenshot an attack path.
- **Keeping reference material out of memory entirely.** Discussing and
  learning from it is the point of dropping it in.

**Consequences**
A misread screenshot or a wrong person link costs a lookup, never a fact.
Vision reading of screenshots becomes part of the ingest path, and its errors
are measured like any other index. The eval needs reference-material cases:
dropped messages with claims about him that must be answered with attribution
and never stored as his.
