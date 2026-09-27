# Subcortical

The perception process. Everything up to and including text: capture, cheap
detection, description, and appending to the record. Judgement is always
Fendlera's. Decisions: ADR-0028 to 0034, 0037, 0043, 0045, 0049, 0054.

## Sources

A source is a thing that produces observations, not a metric. Screens, RTSP
cameras, the phone camera, machine telemetry, log files and job progress are
all sources and are treated identically: adding one is configuration.

- **Text streams** (logs, journald, container output) are already language and
  skip the describer.
- **Machine state** is one source per machine, not one per metric.
- **Audio** is sound events only (a chime, a smoke alarm), and only while a task
  has opened a watch. Speech is never ambiently transcribed (ADR-0033).
- Every enrolled source carries online/offline status. A dead feed must not read
  as nothing happening.

## Detection and description

Cheap CPU detectors decide what is worth looking at, never what matters.
Significance is the model's judgement over descriptions, never a configured
threshold. Three kinds of salience: difference against the last frame examined,
trend across the record, and a single sample significant on its own.

Keyframes are captured on a fixed interval but described lazily, only when
something later makes her look back. The describer is referenced by endpoint,
never bundled, so it can move to another machine.

The describer transcribes; it does not rank. Both qwen2.5vl sizes read values
off a product grid correctly and attach them to the wrong product. Reading the
page (DOM) beats reading the pixels for that case.

## The record

- **DVR:** one text file per source, descriptions in time order. Never resident.
- **Log book:** what she noticed, what she said, and his response. Survives when
  the DVR expires.
- **Radio:** conversation.
- **Blobs:** raw images and audio in a separate local store. Wiping it never
  damages memory.

There is no pre-merged chronological file; the merged view is assembled at read
time, so a hand edit is always the truth.

## Provenance

Every stored line carries its source, observation time and trust level, and for
solicited content (a fetched page) why it was fetched. The stamp is applied at
write time and travels with the line on every read. An observation is never an
instruction and can never cause a memory write (ADR-0045).

## The boundary test

Subcortical runs with no chat model present and keeps filling the record.
Fendlera reaches it through named tools (read the record, look now) and through
an ambient current-screen description (ADR-0049, 0054).

## Retention

Raw imagery expires after about a month; descriptions persist. Significance
protects imagery past the window. Consolidation writes summaries on top of
descriptions and never deletes them.

## Open

- A controlled describer vocabulary ("stove", never "burner") to delay climbing
  the retrieval ladder: raised, not decided.
- Whether Subcortical gets its own repository: when it has code of its own.
