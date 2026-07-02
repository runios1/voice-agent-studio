# events/ — event schema (Phase 2, FROZEN)

The single append-only stream every component emits to (P2-D5). `EventType` is a
**closed enum**; `payload` is a **generic dict** validated per-type by P2-5. Four
consumers bind here: dashboard, auto-pause, audit log, analytics. Append-only —
the immutable log is the compliance record. Never mutate/delete.
