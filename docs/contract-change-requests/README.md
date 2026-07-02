# Contract change requests

Contracts (`contracts/`) are frozen and read-only during fan-out. A workstream that
believes a contract is wrong or insufficient must NOT edit or work around it — it
files a request here and surfaces it to the integrator. This keeps the frozen seams
frozen; a silent contract edit breaks every other stream.

## How to file
Create `ws<N>-<short-slug>.md` in this folder using the template below. Then stop
and surface it — do not proceed as if the change is approved.

## Template
```markdown
# CR: <short title>
- **Workstream:** WS<N> — <name>
- **Contract affected:** <contracts/... path>
- **Status:** proposed | approved | rejected

## Problem
What in the current contract blocks or misfits your work? Be concrete.

## Proposed change
The minimal edit that fixes it. Show the before/after if possible.

## Blast radius
Which other workstreams does this touch? Can they absorb it without rework?

## Workaround while pending
What you'll do in the meantime (e.g. mock, stub) so you're not blocked.
```
