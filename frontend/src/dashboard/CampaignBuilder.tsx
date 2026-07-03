/**
 * Campaign builder: pick a built (deploy-ready) agent, name the campaign, add
 * leads (manual rows + CSV/paste import), then authorize — which, per the
 * existing `/api/campaigns` seam, both CREATES and immediately AUTHORIZES the
 * campaign (bounded autonomy, P2-D1: authorizing starts the dispatch loop).
 * That's a one-way, consequential action, so the last step is a deliberate,
 * two-part confirm (a checkbox + a distinct button) rather than a single click.
 */
import { useEffect, useState } from "react";
import clsx from "clsx";
import { useDashboardStore } from "./store";
import { ControlFailure } from "./dashboardApi";
import { normalizePhone, parseLeadsCsv, type InvalidLeadRow } from "./leadImport";
import type { AgentSummary, GuardrailEnvelope, NewLead } from "./types";

const DEFAULT_ENVELOPE: GuardrailEnvelope = {
  max_concurrent_calls: 5,
  calls_per_minute: 10,
  max_attempts_per_lead: 3,
  calling_start_hour_local: 8,
  calling_end_hour_local: 20,
};

type Step = "setup" | "leads" | "review";

export function CampaignBuilder() {
  const api = useDashboardStore((s) => s.api);
  const openFleet = useDashboardStore((s) => s.openFleet);
  const loadFleet = useDashboardStore((s) => s.loadFleet);
  const openCampaign = useDashboardStore((s) => s.openCampaign);

  const [step, setStep] = useState<Step>("setup");
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [agentsError, setAgentsError] = useState<string | null>(null);
  const [agentId, setAgentId] = useState("");
  const [name, setName] = useState("");

  const [leads, setLeads] = useState<NewLead[]>([]);
  const [phoneInput, setPhoneInput] = useState("");
  const [nameInput, setNameInput] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [csvText, setCsvText] = useState("");
  const [invalidRows, setInvalidRows] = useState<InvalidLeadRow[]>([]);

  const [envelope, setEnvelope] = useState(DEFAULT_ENVELOPE);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [authorizeChecked, setAuthorizeChecked] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!api) return;
    api
      .listAgents()
      .then((a) => {
        setAgents(a);
        const firstReady = a.find((x) => x.status === "ready");
        if (firstReady) setAgentId(firstReady.id);
      })
      .catch(() => setAgentsError("Couldn't load your agents. Is the backend running?"));
  }, [api]);

  const selectedAgent = agents?.find((a) => a.id === agentId) ?? null;
  const canProceedSetup = Boolean(selectedAgent && selectedAgent.status === "ready" && name.trim());

  function addLead() {
    const phone = normalizePhone(phoneInput);
    if (!phone) {
      setAddError("That doesn't look like a valid phone number.");
      return;
    }
    if (leads.some((l) => l.phone === phone)) {
      setAddError("That phone number is already in the list.");
      return;
    }
    setLeads((prev) => [...prev, { phone, display_name: nameInput.trim() || undefined }]);
    setPhoneInput("");
    setNameInput("");
    setAddError(null);
  }

  function removeLead(phone: string) {
    setLeads((prev) => prev.filter((l) => l.phone !== phone));
  }

  function importCsv() {
    const { valid, invalid } = parseLeadsCsv(csvText, leads);
    setLeads((prev) => [...prev, ...valid]);
    setInvalidRows(invalid);
    setCsvText("");
  }

  async function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setCsvText(await file.text());
  }

  async function authorize() {
    if (!api || !selectedAgent) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const campaign = await api.createCampaign({
        agent_id: selectedAgent.id,
        name: name.trim(),
        leads,
        envelope,
      });
      await loadFleet();
      await openCampaign(campaign.id);
    } catch (err) {
      setSubmitError(
        err instanceof ControlFailure ? err.message : "Couldn't authorize that campaign.",
      );
      setSubmitting(false);
    }
  }

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold">New campaign</h2>
          <StepIndicator step={step} />
        </div>
        <button
          data-testid="cancel-builder"
          onClick={openFleet}
          className="text-sm text-muted hover:text-ink"
        >
          Cancel
        </button>
      </div>

      {agentsError && <p className="px-5 pt-3 text-sm text-red-700">{agentsError}</p>}

      {step === "setup" && (
        <section className="space-y-4 px-5 py-4">
          <div>
            <label className="mb-1 block text-xs font-medium uppercase text-muted">
              Agent
            </label>
            {!agents ? (
              <p className="text-sm text-muted">Loading agents…</p>
            ) : agents.length === 0 ? (
              <p className="text-sm text-muted">
                No agents yet — build one in the studio first.
              </p>
            ) : (
              <select
                data-testid="agent-select"
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="w-full rounded-md border border-line bg-canvas px-3 py-2 text-sm"
              >
                <option value="" disabled>
                  Choose an agent…
                </option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} {a.status !== "ready" ? "(not deploy-ready)" : ""}
                  </option>
                ))}
              </select>
            )}
            {selectedAgent && selectedAgent.status !== "ready" && (
              <p className="mt-1 text-xs text-amber-700">
                This agent isn't deploy-ready yet — finish building it in the studio
                first.
              </p>
            )}
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium uppercase text-muted">
              Campaign name
            </label>
            <input
              data-testid="campaign-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. West-coast SaaS Q3"
              className="w-full rounded-md border border-line bg-canvas px-3 py-2 text-sm"
            />
          </div>

          <button
            data-testid="next-to-leads"
            disabled={!canProceedSetup}
            onClick={() => setStep("leads")}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Next: add leads
          </button>
        </section>
      )}

      {step === "leads" && (
        <section className="space-y-5 px-5 py-4">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted">
              Add a lead
            </h3>
            <div className="flex flex-wrap items-end gap-2">
              <div>
                <label className="mb-1 block text-xs text-muted">Phone</label>
                <input
                  data-testid="lead-phone"
                  value={phoneInput}
                  onChange={(e) => setPhoneInput(e.target.value)}
                  placeholder="+1 555 000 1234"
                  className="rounded-md border border-line bg-canvas px-3 py-1.5 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-muted">Name (optional)</label>
                <input
                  data-testid="lead-name"
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  placeholder="Ada Lovelace"
                  className="rounded-md border border-line bg-canvas px-3 py-1.5 text-sm"
                />
              </div>
              <button
                data-testid="add-lead"
                onClick={addLead}
                className="rounded-md border border-line bg-canvas px-3 py-1.5 text-sm font-medium hover:bg-panel"
              >
                + Add
              </button>
            </div>
            {addError && <p className="mt-1 text-xs text-red-700">{addError}</p>}
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted">
              Or import a CSV
            </h3>
            <p className="mb-1 text-xs text-muted">
              One lead per line: phone, then an optional name. Upload a file or
              paste it below.
            </p>
            <input
              data-testid="csv-file"
              type="file"
              accept=".csv,text/csv,text/plain"
              onChange={onFileChange}
              className="mb-2 block text-xs"
            />
            <textarea
              data-testid="csv-text"
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
              placeholder={"+15550001234, Ada Lovelace\n+15550005678, Grace Hopper"}
              rows={4}
              className="w-full rounded-md border border-line bg-canvas px-3 py-2 font-mono text-xs"
            />
            <button
              data-testid="import-csv"
              disabled={!csvText.trim()}
              onClick={importCsv}
              className="mt-2 rounded-md border border-line bg-canvas px-3 py-1.5 text-sm font-medium hover:bg-panel disabled:opacity-50"
            >
              Parse &amp; add
            </button>
            {invalidRows.length > 0 && (
              <div
                data-testid="invalid-rows"
                className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800"
              >
                {invalidRows.length} row{invalidRows.length === 1 ? "" : "s"} skipped:
                <ul className="mt-1 list-disc pl-4">
                  {invalidRows.map((r, i) => (
                    <li key={i}>
                      <span className="font-mono">{r.raw}</span> — {r.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted">
              Leads ({leads.length})
            </h3>
            {leads.length === 0 ? (
              <p className="text-sm text-muted">No leads added yet.</p>
            ) : (
              <ul data-testid="lead-list" className="max-h-64 space-y-1 overflow-auto">
                {leads.map((l) => (
                  <li
                    key={l.phone}
                    className="flex items-center justify-between rounded-md bg-panel px-3 py-1.5 text-sm"
                  >
                    <span>
                      <span className="font-mono">{l.phone}</span>
                      {l.display_name ? ` — ${l.display_name}` : ""}
                    </span>
                    <button
                      data-testid={`remove-lead-${l.phone}`}
                      onClick={() => removeLead(l.phone)}
                      className="text-xs text-muted hover:text-red-700"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => setStep("setup")}
              className="rounded-md border border-line bg-canvas px-4 py-2 text-sm font-medium hover:bg-panel"
            >
              Back
            </button>
            <button
              data-testid="next-to-review"
              disabled={leads.length === 0}
              onClick={() => setStep("review")}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Next: review &amp; authorize
            </button>
          </div>
        </section>
      )}

      {step === "review" && selectedAgent && (
        <section className="space-y-4 px-5 py-4">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase text-muted">Agent</dt>
              <dd>{selectedAgent.name}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-muted">Campaign name</dt>
              <dd>{name}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-muted">Leads</dt>
              <dd data-testid="review-lead-count">{leads.length}</dd>
            </div>
          </dl>

          <div>
            <button
              onClick={() => setAdvancedOpen((v) => !v)}
              className="text-xs text-muted underline hover:text-ink"
            >
              {advancedOpen ? "Hide" : "Show"} guardrail envelope (advanced)
            </button>
            {advancedOpen && (
              <div className="mt-2 grid grid-cols-2 gap-3 rounded-md bg-panel p-3 text-sm">
                <EnvelopeField
                  label="Max concurrent calls"
                  value={envelope.max_concurrent_calls}
                  onChange={(v) => setEnvelope((e) => ({ ...e, max_concurrent_calls: v }))}
                />
                <EnvelopeField
                  label="Calls per minute"
                  value={envelope.calls_per_minute}
                  onChange={(v) => setEnvelope((e) => ({ ...e, calls_per_minute: v }))}
                />
                <EnvelopeField
                  label="Max attempts per lead"
                  value={envelope.max_attempts_per_lead}
                  onChange={(v) => setEnvelope((e) => ({ ...e, max_attempts_per_lead: v }))}
                />
                <EnvelopeField
                  label="Calling window start (local hr)"
                  value={envelope.calling_start_hour_local}
                  onChange={(v) => setEnvelope((e) => ({ ...e, calling_start_hour_local: v }))}
                />
                <EnvelopeField
                  label="Calling window end (local hr)"
                  value={envelope.calling_end_hour_local}
                  onChange={(v) => setEnvelope((e) => ({ ...e, calling_end_hour_local: v }))}
                />
              </div>
            )}
          </div>

          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            Authorizing starts calling these {leads.length} leads right away, within
            the guardrails above and the platform's locked compliance rules — the
            agent then runs unsupervised until paused.
            <label className="mt-2 flex items-center gap-2 text-xs">
              <input
                data-testid="authorize-checkbox"
                type="checkbox"
                checked={authorizeChecked}
                onChange={(e) => setAuthorizeChecked(e.target.checked)}
              />
              I understand this authorizes the agent to call these leads
              unsupervised.
            </label>
          </div>

          {submitError && <p className="text-sm text-red-700">{submitError}</p>}

          <div className="flex gap-2">
            <button
              onClick={() => setStep("leads")}
              disabled={submitting}
              className="rounded-md border border-line bg-canvas px-4 py-2 text-sm font-medium hover:bg-panel disabled:opacity-50"
            >
              Back
            </button>
            <button
              data-testid="authorize-campaign"
              disabled={!authorizeChecked || submitting}
              onClick={authorize}
              className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {submitting ? "Authorizing…" : "Authorize campaign"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

function StepIndicator({ step }: { step: Step }) {
  const steps: { key: Step; label: string }[] = [
    { key: "setup", label: "1. Agent & name" },
    { key: "leads", label: "2. Leads" },
    { key: "review", label: "3. Review & authorize" },
  ];
  return (
    <p className="mt-0.5 text-xs text-muted">
      {steps.map((s, i) => (
        <span key={s.key} className={clsx(s.key === step && "font-medium text-ink")}>
          {s.label}
          {i < steps.length - 1 ? " → " : ""}
        </span>
      ))}
    </p>
  );
}

function EnvelopeField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="text-xs text-muted">
      {label}
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink"
      />
    </label>
  );
}
