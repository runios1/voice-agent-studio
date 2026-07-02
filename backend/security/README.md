# Workstream 5 — Security / screening layer

**Depends on:** `contracts/model_wrapper`.

## Responsibility — the OUTER layer of defense in depth (D-security)
Three layers, inner→outer. This workstream owns the outer one; the inner two are
structural and owned by config_gate + runtime_loop:

1. **Can't-do-it** (structural, config_gate + runtime): least-privilege function
   params, allowlisted URLs — no `offer_discount`, no free-composed links.
2. **Can't-know-it** (structural, config_gate + builder): least context, server-side
   tenant isolation — secrets/infra/other tenants never in a model's window.
3. **Screening (this workstream, probabilistic):** wrap EVERY model in/out via the
   `ModelWrapper` boundary with an off-the-shelf screener — **Google Model Armor**
   (v1 pick: provider-agnostic REST, prompt-injection/jailbreak + malicious-URL in
   *and* out + PII/sensitive-data). Alternative: **Lakera Guard**.

## The rule
Screening is **the layer you are allowed to have fail** — never the one you rely
on. It's probabilistic and bypassable (OWASP LLM01; evasion research). It reduces
residual risk on top of the two structural layers that remove whole classes of risk.

## Screening decisions (D-security)
- Free-text touching a locked-guardrail domain (disclosure/DNC/claims): **hard-block**.
- Merely-odd-but-not-dangerous content: **accept-but-flag**, don't police creativity.
- Malicious-URL scan on all outbound automation content before send.
