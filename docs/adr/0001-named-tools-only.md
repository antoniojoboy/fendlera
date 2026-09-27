# ADR-0001 - Named tools only, no shell

**Status:** accepted

**Context**
The agent needs to read GPU stats, list models and inspect the machine. The
obvious implementation is a `bash` tool with an allowlist of safe commands.

**Decision**
No shell tool. Every capability is a named tool with a fixed command, no
user-controlled arguments, and structured output: `get_gpu_stats()`,
`get_memory()`, `list_models()`.

**Alternatives rejected**
- Shell with a command allowlist. Allowlists are bypassed by argument
  injection, shell metacharacters and chained commands.
- An LLM judging whether a command is safe. Six guardrail systems including
  Azure Prompt Shield and Meta Prompt Guard were evaded at rates up to 100%
  (arXiv 2504.11168). HiddenLayer bypassed OpenAI Guardrails in Oct 2025 -
  the same model class generating and judging means both are compromised
  together. OWASP places guardrail models alongside deterministic controls,
  never instead of them.

**Consequences**
"Is `rm -rf` safe?" is a question that only exists if there is a shell. With
named tools it is unrepresentable rather than filtered. The cost is that every
new capability needs a deliberate code change, which is the point.
