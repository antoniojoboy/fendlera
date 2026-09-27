# ADR-0004 - No wake-word model

**Status:** Accepted

**Date:** 2026-09-06

**Context**
openWakeWord's pre-trained models and its standard training feature set are both CC-BY-NC-SA 4.0, which conflicts with an MIT platform. Porcupine needs an access key and online activation. Speech-to-text runs in about 0.02s on the target GPU, so the constraint wake-word models exist to work around does not apply.

**Decision**
Transcribe continuously. The conversation opens on a deterministic fuzzy match of the assistant's name in the text. No model decides whether to respond.

**Consequences**
Any name works, including ones no pre-trained model covers. A string match cannot be argued into opening and costs nothing. Accepted false positive: "desire" is a variant, so "I desire a coffee" opens the conversation. Idle speech is transcribed and discarded: not sent to the model, not logged, not remembered.
