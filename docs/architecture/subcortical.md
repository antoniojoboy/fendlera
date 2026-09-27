# Subcortical architecture

**Version 3, 28 Sep 2026.** Supersedes `subcortical-architecture-v2.pdf`
(13 Sep 2026), which was written before the output-routing, timer and time
decisions and read them as open. Decisions: ADR-0025, 0028 to 0034, 0037, 0038,
0043, 0045, 0049, 0054.

## 1. What it is

Subcortical is the perception process. It does everything up to and including
text: capture, cheap detection, description, and appending to the record.
Judgement is always Fendlera's.

The name: beneath the cortex, the structures that process before conscious
thought. Like Fendlera and Subtend, it was chosen for sound and availability,
with the meaning mapped on afterwards.

Three processes, whole apart, better together:

| Process | Knows |
|---|---|
| Fendlera | judges |
| Subtend | what he did (intent) |
| Subcortical | what is happening (observation) |

**Boundary test:** Subcortical runs with no chat model present and keeps filling
the record.

## 2. Design stance

- Design perception the way a person works. The model is a control room, not a
  screen watcher.
- She is not reactive. A perception loop runs whether or not anyone asks, and
  the current view is always present too. "What colour is this" answers from
  now; "what was that place" answers from the record. No router picks between
  them.
- Perception runs as its own process. It meets the conversation only at the
  record.
- Cheap detectors decide what is worth looking at, never what matters.
  Significance is the model's judgement over descriptions, never a configured
  threshold.

## 3. Sources

A source is a thing that produces observations, not a metric. Every source is a
labelled instance, and adding one is configuration, not a new component.

| Class | Examples | Notes |
|---|---|---|
| Visual | screen, RTSP cameras, phone camera | described by a VLM |
| Text | log files, journald, container output | already language, skips the describer |
| Machine state | CPU, GPU, RAM per machine | one source per machine, sampled, time-stamped |
| Audio | sound events only (chime, alarm, glass) | only while a task opens a watch |
| Solicited | fetched web pages | quarantined; provenance records why it was fetched |

A screen is one source, not one per window. A camera carrying audio and video is
one source and one file.

Every enrolled source carries online/offline status. A dead feed must never read
as nothing happening.

## 4. The body model

The core (harness, memory, persona, a terminal) is complete on its own. Senses
are attached on top and discovered, not assumed. She holds a live register of
available senses; a sense dropping or reattaching is a salient event that enters
the loop like any other and is logged alongside what that source saw.

Desirée is one instance and does not fork. Other machines run extensions of her
reach: limbs, not second people. One brain means one place where judgement
happens.

- Cheap detection runs locally on each machine and stays CPU-bound, because a
  GPU is not guaranteed. A small report ships instead of raw frames.
- Enrolment probes a host and reports what it can do locally, the same pattern
  as Subtend's device enrolment.
- The describer is referenced by endpoint, never bundled, so it can move to a
  dedicated machine. The frames-in, text-out boundary keeps it uncoupled.
- Splitting one model across machines is rejected: no too-big-for-one-box
  problem, and it adds network latency to every token.

## 5. Detection and description

**Three kinds of salience:** difference against the last frame properly
examined; trend across the record; a single sample significant on its own (a
stack trace).

**Two cadences:**

- **Fast path:** reactive only. Things a cheap detector actually flagged.
- **Keyframes:** each source is captured on an interval regardless of change,
  but described lazily, only when something later makes her look back. This is
  what makes the retrospective case work (a fridge magnet moved) without
  thousands of descriptions a day. An on-demand "look now" exists too.

**Describers** are separate models by mechanical necessity (frames or audio in,
text out), not design choice. Speech-to-text is a describer in exactly the way
the VLM is. One judging mind, many describers: a second judging model would mean
two minds forming impressions with no way to reconcile them.

The describer transcribes; it does not rank. Both qwen2.5vl sizes read values
off a product grid correctly and then attach them to the wrong product; the grid
structure is what is lost. Reading the page (DOM) beats reading the pixels for
that case.

The screen is ambient (ADR-0049): one current description, refreshed only when
a perceptual hash changes, handed to every turn. A static screen costs nothing.

## 6. The record: control-room memory

Desirée is a control-room operator with three things:

| Store | Holds | Lifetime |
|---|---|---|
| DVR | descriptions per source, in time order | expires with imagery policy |
| Log book | what she noticed, what she said, his response | survives |
| Radio | conversation | per the memory design |

Raw images and audio go to a separate local blob store.

- **One file per source, holding text, in time order.** Source is part of the
  meaning: a stove left on at home is a different memory from a stove seen
  elsewhere.
- **No pre-merged chronological file.** The merged view is assembled at read
  time, so a hand edit is always the truth.
- **"One memory" means one retrieval, not one store.** She reaches for whichever
  store the question needs.
- **The DVR is never resident.** A description is the model's own output; ADR-0002
  exists because model output filed with the authority of the user's word
  corrupted recall.
- **Her own utterances and his responses go in the log book, marked as hers.**
  "Did I already mention this" becomes a lookup.
- **The log book survives; the DVR expires.** "How many times has the garage
  been left open" is a count in the log book. The count is "times I flagged
  this", not "times it happened", and needs no caveat.
- **Blob retention is a disk policy; description retention is a memory policy.**
  Wiping blobs never damages memory. Accepted cost: a better describer cannot
  re-describe old frames.
- A daily report is a named tool she calls when asked, not a scheduled job. It
  reads the DVR for what happened and the log book for what is pending.

## 7. The looking-back pass

A pass reads a window of the record and asks two things: what has not been
said, and what is still unresolved.

- A stalled download fires no detector because nothing changed. Absence of
  change is the signal, and only looking back sees it.
- Trend detection is the same operation. The GPU climbing and the stove left on
  are one mechanism.
- **No open-threads store.** The pattern lives in the sequence ("stove on at
  four, still on at four-thirty, nobody in the room"). A list flattens that and
  goes stale; re-reading cannot.
- Most passes are silent. There is no scheduled-announcement path.
- It runs as a recurring row on the ticker (ADR-0038).

**Consolidation** is judgement, not a rule. What survives: things touched on
more than once, things he responded to, things that recur, things he marked as
important. What decays after about a month: the routine. Significance accrues
after the fact, which is why consolidation looks back rather than stamping at
write time. Consolidation writes summaries on top and never deletes
descriptions.

**Two decay mechanisms.** Mundane observations decay on age. Commitments decay
only on resolution: a bill due in two months is more urgent at day fifty.

## 8. Proactive speech

- **First sighting is immediate** for things that cannot wait: an unattended
  flame, an open door. Being told something he already knew is an accepted cost.
- **A dismissal quietens, it does not close.** If still true later, she raises
  it again, more lightly. The interval is her judgement.
- **Ignoring is not an answer.** Only resolution closes an item. Something
  raised and ignored stops interrupting and waits for a shift boundary.
- **Two shifts, morning and evening.** Morning looks forward; evening closes
  things out. Delivered when asked. Completeness beats brevity: she orders by
  priority by default, and nothing is dropped.

Deciding what is worth saying is Fendlera's job. Reaching him is Subtend's
(ADR-0036): she emits once, and Subtend picks the carrier.

## 9. Microphone and ambient speech

- Subcortical owns the interfaces: cameras, microphones, screens.
- **No ambient speech transcription** (ADR-0033). Everything is transcribed for
  the name match and discarded unless the name appears. Opt-in transcription
  sessions exist for "transcribe this conversation".
- **Being named is not being addressed** (ADR-0034). The string match still
  gates what reaches the model; she then judges whether she was addressed or
  mentioned. A mention is written down.
- **An overheard intention is a note, never an instruction.** She raises it as a
  question. It is not a timer: a timer carries his word; this is her judgement.
- **Ambient audio as a record-writing source is off** unless a task opens it
  ("tell me when the laundry finishes"), and it closes when the task resolves.

## 10. Time, telemetry and wakes

- **Only the current time is resident.** Everything else is read on demand or
  surfaced by the looking-back pass (ADR-0037).
- **Telemetry is a source.** A GPU at 81°C means nothing; climbing for forty
  minutes means something, and a snapshot has no trend.
- **Time-based wakes** come from the ticker, the one background process
  (ADR-0038).
- **Condition-based wakes** come from detection. A chime is a transient that
  polling misses, so capture runs continuously while a watch is open and a
  detection raises her immediately. Without an open watch, the same chime sits
  in the DVR for the next pass.

## 11. Liveness

Hub-and-spoke: the central node polls; devices never self-report (ADR-0043).

| State | Detected by |
|---|---|
| reachable and producing | normal |
| unreachable | ping |
| reachable but silent | comparing against the source's expected interval; logged and raised |
| healthy, wrong view | only the describer; she says what she cannot see rather than guessing |

## 12. Trust and provenance

Everything Subcortical produces is untrusted content (ADR-0045).

- Every line carries its source, observation time and trust level, plus why it
  was fetched for solicited content. Stamped at write time.
- On retrieval it arrives in a labelled block that describes the world and
  never commands.
- **An observation is never an instruction** and can never cause a memory write.
  Only a principal speaking through a session can. Subcortical describes; it
  never extracts facts.
- Perception is ingress; named tools govern egress (ADR-0054). The control room
  reads every camera and cannot open the doors.

Observations belong to Desirée's own store, not to any person. Access is decided
at retrieval by who is asking (see `identity-and-access.md`).

## 13. Retrieval

grep, then FTS5 only when grep measurably fails, then hybrid keyword-plus-vector
only when FTS measurably fails (ADR-0030). Each index is derived from the
markdown and rebuildable.

grep fails silently and empty; FTS5 misses synonyms silently; vectors always
return something and fail loudly and wrong. "Not in sources" is preferred to a
fabrication. The record is full of exact identifiers (filenames, machine names,
error strings), where vectors are weakest, so keyword search is added alongside
vectors, never replaced.

## 14. Accepted limits

Occlusion; cold start with no history; describer phrasing variance; cluttered
scenes (keys on a blank table are in scope).

## 15. The three motivating incidents

1. **The laundry.** A load finished and sat for hours. The condition-based watch.
2. **The GPU climbing.** Nobody watching. The trend case.
3. **Parts research.** Comparing components, wanting someone present who
   remembers the last few minutes. No alert, no threshold.

Only two are watchdog cases, and none yields a number. The third is not an
alerting problem at all; it needs her present and remembering. That is the
evidence for perception-first ordering and against building an alerting
system.

## 16. Open

- A controlled describer vocabulary ("stove", never "burner") to delay climbing
  the retrieval ladder: raised, not decided.
- Cross-machine frame shipping cost on the LAN: unmeasured. A 4GB GPU is too
  small for the larger describer, so description stays on the main host.
- A page-reading tool for the parts-research case.
- Subcortical gets its own repository when it has code of its own.
