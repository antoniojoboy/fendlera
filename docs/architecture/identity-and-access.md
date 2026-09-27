# Identity and access

Decisions: ADR-0021, 0035.

## Principals

A principal is an opaque UUID generated at enrolment, never a name.
`principal_id` is in the event envelope from build step one. Presses are
attributed by device enrolment; speech by voiceprint. An unmatched voice is
`null`: a guest, helped but unprivileged.

Speaker verification sits after voice activity detection and before
transcription. Enrolment is passive: unmatched embeddings cluster over days and
are labelled afterwards. A voiceprint is weak against a recording, so it gates
capability, not everything.

## Stores

- **Desirée's store** holds what sources observed. Access is granted, never
  assumed; it defaults to the owner alone.
- **Each person's private store** holds what they said to her. Stores are
  mutually closed.

Nothing is classified at write time. The camera describes what it saw; the gate
is at retrieval and is about who is asking. What a source observed belongs to
Desirée; what someone said is private to whoever said it.

## Tiers

| Tier | Who | Reaches |
|---|---|---|
| household | owner and anyone they grant | own store, plus Desirée's store if granted |
| enrolled | a trusted person, enrolled by voice | own store, general tools |
| guest | anyone unrecognised | general help, no stores |

Enrolment is a grant at a level, set by the owner, never inferred.

## Two checks, both required

The tool declares its required tier (may you call this). The grant list decides
which stores your identity reaches (on what). Identity comes from the session;
the agent cannot pass a principal as an argument.

## Guards for a borrowed headset

Voiceprint as a second factor; presence contradiction (a headset in use while
the owner's phone sits locked and still); confirmation on a channel the borrower
is not on. An unverified voice never gets memory read access.

## Open

Whether genuinely sensitive reads need a second factor beyond voiceprint, such
as a press from an enrolled device.
