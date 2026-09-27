# ADR-0011 - Device config is data; enrolment mode; closed vocabulary

**Status:** Accepted

**Date:** 2026-09-07

**Context**
Linux already normalises Bluetooth HID to `/dev/input/eventN`. Speech transcription mangles freeform labels.

**Decision**
One generic evdev adapter; a profile file maps raw signatures to symbols. Enrolment: pair, grab exclusively, press each control in turn, record, name from a closed spoken set (next, back, select, dismiss). Freeform names remain available in config.

**Consequences**
A new HID device takes about 90 seconds and no code. Vendor-protocol devices (Tier 4) cannot be enrolled this way.
