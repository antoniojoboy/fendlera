# ADR-0053 - Per-utterance headset profile switching

**Status:** Experimental, off (MODE_SWITCH=0)

**Date:** 2026-09-14

**Context**
A Bluetooth headset cannot give microphone and high-quality output at once.

**Decision**
Switch between HFP and A2DP per utterance.

**Consequences**
Each switch into A2DP re-establishes the link at about 2.8s; a tool turn made four. Not viable per utterance. Per-conversation switching is untested.
