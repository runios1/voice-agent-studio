import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuditView, exportJson } from "./AuditView";
import { useDashboardStore } from "./store";
import { makeEvent, mountStore, resetStore } from "./testMocks";

beforeEach(resetStore);

describe("AuditView", () => {
  it("renders event rows from the server query", async () => {
    await mountStore({
      auditResults: [
        makeEvent({ event_id: "a", type: "disclosure.spoken", campaign_id: "c1" }),
        makeEvent({ event_id: "b", type: "guardrail.tripped", severity: "warning" }),
      ],
    });
    await useDashboardStore.getState().openAudit();
    render(<AuditView />);
    await waitFor(() =>
      expect(within(screen.getByTestId("audit-rows")).getAllByRole("row")).toHaveLength(2),
    );
    expect(screen.getByTestId("audit-count")).toHaveTextContent("2 events");
  });

  it("changing the type filter re-queries the server", async () => {
    const { calls } = await mountStore({ auditResults: [] });
    await useDashboardStore.getState().openAudit();
    const before = calls.audit;
    render(<AuditView />);
    await userEvent.selectOptions(screen.getByTestId("filter-type"), "slot.booked");
    await waitFor(() => expect(calls.audit).toBeGreaterThan(before));
    expect(useDashboardStore.getState().auditFilter.types).toEqual(["slot.booked"]);
  });

  it("exportJson serializes the events to a downloaded blob", () => {
    // jsdom doesn't implement the object-URL APIs — install stubs to observe them.
    const createUrl = vi.fn().mockReturnValue("blob:mock");
    const revokeUrl = vi.fn();
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = createUrl;
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = revokeUrl;
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    exportJson([makeEvent({ event_id: "a" })]);

    expect(createUrl).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeUrl).toHaveBeenCalledOnce();
    click.mockRestore();
  });
});
