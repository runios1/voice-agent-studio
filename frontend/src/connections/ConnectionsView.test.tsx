import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConnectionsView } from "./ConnectionsView";
import type { ConnectionInfo, ConnectionsApi } from "./connectionsApi";
import { ConnectionsFailure } from "./connectionsApi";

function fakeApi(initial: ConnectionInfo[] = []): {
  api: ConnectionsApi;
  authorizeCalls: string[];
  disconnectCalls: string[];
} {
  let connections = initial;
  const authorizeCalls: string[] = [];
  const disconnectCalls: string[] = [];
  const api: ConnectionsApi = {
    list: async () => connections.map((c) => ({ ...c })),
    authorize: async (provider) => {
      authorizeCalls.push(provider);
      connections = [
        ...connections.filter((c) => c.provider !== provider),
        { provider, connected: true, scopes: [], connection_ref: "conn-1" },
      ];
      return `https://provider.example/oauth?p=${provider}`;
    },
    disconnect: async (provider) => {
      disconnectCalls.push(provider);
      connections = connections.filter((c) => c.provider !== provider);
      return connections.map((c) => ({ ...c }));
    },
  };
  return { api, authorizeCalls, disconnectCalls };
}

describe("ConnectionsView", () => {
  it("shows every catalog provider, connected or not", async () => {
    const { api } = fakeApi([
      { provider: "google_calendar", connected: true, scopes: [], connection_ref: "c1" },
    ]);
    render(<ConnectionsView api={api} />);
    await screen.findByTestId("connection-row-google_calendar");
    expect(screen.getByTestId("connection-status-google_calendar")).toHaveTextContent(
      "Connected",
    );
    expect(screen.getByTestId("connection-status-gmail")).toHaveTextContent(
      "Not connected",
    );
  });

  it("connect begins OAuth and redirects the browser", async () => {
    const { api, authorizeCalls } = fakeApi([]);
    const navigate = vi.fn();
    render(<ConnectionsView api={api} navigate={navigate} />);
    await screen.findByTestId("connect-google_calendar");
    await userEvent.click(screen.getByTestId("connect-google_calendar"));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(
      "https://provider.example/oauth?p=google_calendar",
    ));
    expect(authorizeCalls).toEqual(["google_calendar"]);
  });

  it("disconnect requires a second, explicit confirm click", async () => {
    const { api, disconnectCalls } = fakeApi([
      { provider: "google_calendar", connected: true, scopes: [], connection_ref: "c1" },
    ]);
    render(<ConnectionsView api={api} />);
    await screen.findByTestId("disconnect-google_calendar");
    await userEvent.click(screen.getByTestId("disconnect-google_calendar"));
    // Not yet disconnected — awaiting confirmation.
    expect(disconnectCalls).toEqual([]);
    await screen.findByTestId("confirm-disconnect-google_calendar");
    await userEvent.click(screen.getByTestId("confirm-disconnect-google_calendar"));
    await waitFor(() => expect(disconnectCalls).toEqual(["google_calendar"]));
    await waitFor(() =>
      expect(screen.getByTestId("connection-status-google_calendar")).toHaveTextContent(
        "Not connected",
      ),
    );
  });

  it("surfaces a failed authorize without crashing", async () => {
    const api: ConnectionsApi = {
      list: async () => [],
      authorize: async () => {
        throw new ConnectionsFailure("Google rejected the request.", 400);
      },
      disconnect: async () => [],
    };
    render(<ConnectionsView api={api} />);
    await screen.findByTestId("connect-google_calendar");
    await userEvent.click(screen.getByTestId("connect-google_calendar"));
    await screen.findByText("Google rejected the request.");
  });
});
