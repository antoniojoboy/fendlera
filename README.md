# fendlera

Fendlera is a harness for building capable agents that run entirely on
hardware you own. Models are pluggable, the tool layer is yours to extend,
and it runs headless — drive it from a script, a service, or whatever
interface you build on top.

## Why

Most agent frameworks assume a cloud endpoint and a chat window. That rules
them out anywhere inference can't leave the building: air-gapped networks,
sites with no reliable link, and any environment where sending context to a
third party isn't a decision you're allowed to make.

Fendlera assumes the opposite. Local inference, local memory, local tools.

## Design

**The model is the swappable part.** Backends sit behind an interface, so
today's model isn't a commitment. The framework doesn't care which one you
run.

**The memory layer is the product.** What gets remembered, what gets loaded
into context, and how conflicts between them resolve — that's where the
work is, and it's what survives a model upgrade.

**Tools are named and explicit.** Capabilities are registered rather than
discovered. Adding one is a deliberate act, which keeps the surface area
something you can reason about.

**Headless by default.** No GUI to boot, nothing to keep open. Compose it
into whatever you're already running.

## Status

Early. Interfaces will change.

## The name

*Fendlera rupicola* is a freely branching shrub that grows out of dry rock
in the mountains of the American south-west. No rich soil, no shelter — it
puts out new growth from bare stone, and keeps its seed capsules long after
everything else has dropped.
