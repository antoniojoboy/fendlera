# ADR-0059 - An index and subject files, not one resident facts file

**Status:** Accepted

**Date:** 2026-09-28

**Supersedes:** the single resident facts file of ADR-0002, in part. Write-time
extraction stands; loading all facts into every prompt does not.

**Context**
The POC sends the entire facts file with every extraction and every answer.
The scale eval (harness v2, 0 truncations, 28 Sep 2026) measured the result:

| Context | Where it stopped | Evidence |
|---|---|---|
| 8k | about 530 facts | 107 extractions refused by size 500, 607 by 1,000 |
| 16k | about 1,100 facts | 84 refused at 1,000; answers 1.2s typical, 1.9s worst |

Refusals hit the newest statements first, because they come last, when the
prompt is biggest. So corrections ("Pepper's five now") are the first thing
lost: the opposite of what memory should do.

Before the explicit context and loud-failure fixes, the same overflow
happened silently. Ollama cut 874 prompts from the front, dropping the
instructions, and nothing noticed (ADR-0056 applied to the model itself).

With enough context, recall itself held: 16k stayed at 72.7% from 0 to 500
statements. The problem is fitting memory into the prompt, not finding facts
in it.

**Decision**
Memory is an **index plus subject files**, the design Claude's own memory
uses.

- **One file per subject:** `me/home`, `me/work`, `me/car`, `people/noor`,
  `people/theo` and so on. Each file is small, and capped. Near the cap it is
  consolidated, not grown.
- **An index is always in context:** each subject's name, a one-line
  description and its aliases. Nothing else is resident except `me/profile`.
- **Writing:** the extractor reads the index, picks the subject, opens only
  that file, and updates it in place, keeping history ("Dunmore, previously
  Carrow").
- **Reading:** a question goes to the index, then the one or two relevant
  files, then the answer. The verbatim log search stays as the safety net
  when the index points the wrong way.
- **A fact that spans subjects** lives in one home file, with links from the
  others.

The prompt is sized to the question, not to how much memory exists.

**Rejected**

- **A bigger context window.** It moves the ceiling (530 to about 1,100
  facts) without removing it, and every answer gets slower.
- **Embeddings first.** Word-overlap and subject selection are cheaper,
  inspectable and deterministic. Embeddings wait until measured recall
  failures justify them (ADR-0030's ladder).

**Consequences**
The model now chooses which file to open, and a wrong choice is a miss. The
eval measures subject-selection accuracy as its own number. The index grows by
subject, not by fact: a household might have 50 to 200 subjects against
thousands of facts.

Every request states its context size explicitly, and a prompt that will not
fit fails loudly (`ContextOverflow`). It is never silently cut.

**Amended by:** ADR-0062. Subjects become areas and entities routed by code;
there is no fixed attribute list, and the model chooses only from what exists.
