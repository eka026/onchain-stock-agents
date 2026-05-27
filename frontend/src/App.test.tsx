import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import App from "./App";
import { filterEvents, formatAmount, shortenAddress } from "./format";
import type { Session, TimelineEvent } from "./types";

const events: TimelineEvent[] = [
  {
    id: "event-1",
    kind: "transaction",
    agentId: "trader:0xabc",
    agentType: "trader",
    poolId: "TECH-USD",
    action: "SWAP",
    status: "confirmed",
    summary: "Confirmed swap",
  },
  {
    id: "event-2",
    kind: "validation",
    agentId: "trader:0xdef",
    agentType: "trader",
    poolId: "FIN-USD",
    action: "SWAP",
    status: "rejected",
    summary: "Rejected swap",
  },
];

describe("dashboard helpers", () => {
  it("formats wei-style token amounts compactly", () => {
    expect(formatAmount("1000000000000000000")).toBe("1.0000");
    expect(formatAmount("-5000000000000000000")).toBe("-5.0000");
    expect(formatAmount("4935790171985306494")).toBe("4.9358");
  });

  it("falls back to raw values for invalid amounts", () => {
    expect(formatAmount("not-a-number")).toBe("not-a-number");
  });

  it("shortens addresses without hiding short labels", () => {
    expect(shortenAddress("0x1111111111111111111111111111111111111111")).toBe("0x1111...1111");
    expect(shortenAddress("Trader 0")).toBe("Trader 0");
  });

  it("filters events by status, pool, agent, and kind", () => {
    expect(filterEvents(events, { status: "confirmed" }).map((event) => event.id)).toEqual(["event-1"]);
    expect(filterEvents(events, { poolId: "FIN-USD" }).map((event) => event.id)).toEqual(["event-2"]);
    expect(filterEvents(events, { agentId: "trader:0xabc" }).map((event) => event.id)).toEqual(["event-1"]);
    expect(filterEvents(events, { kind: "validation" }).map((event) => event.id)).toEqual(["event-2"]);
  });
});

const sampleSession: Session = {
  id: "sample-session",
  name: "Sample Agent Run",
  source: "sample",
  scenarioPath: "data/scenarios/demo.json",
  network: "sample",
  createdAt: "2026-05-26T10:00:00Z",
  updatedAt: "2026-05-26T10:00:00Z",
  summary: {
    agentCount: 3,
    eventCount: 2,
    confirmedTxCount: 1,
    rejectedCount: 1,
  },
  agents: [
    {
      id: "trader:0x1111111111111111111111111111111111111111",
      type: "trader",
      label: "Trader 0",
      address: "0x1111111111111111111111111111111111111111",
      balances: { USD: "995000000000000000000", TECH: "4935790171985306494" },
    },
  ],
  pools: [
    {
      id: "TECH-USD",
      baseSymbol: "TECH",
      quoteSymbol: "USD",
      spotPrice: "1013025000000000000",
      reserveA: "1010000000000000000000",
      reserveB: "1023155250000000000000",
      feeBps: 30,
    },
  ],
  events: [
    {
      id: "event-confirmed",
      tick: 3,
      kind: "portfolio_update",
      agentId: "trader:0x1111111111111111111111111111111111111111",
      agentType: "trader",
      poolId: "TECH-USD",
      action: "SWAP",
      status: "confirmed",
      summary: "Trader 0 swaps USD into TECH.",
      txHash: "0xabc0000000000000000000000000000000000000000000000000000000000002",
      portfolioDelta: { USD: "-5000000000000000000", TECH: "4935790171985306494" },
    },
    {
      id: "event-rejected",
      tick: 5,
      kind: "validation",
      agentId: "trader:0x1111111111111111111111111111111111111111",
      agentType: "trader",
      poolId: "TECH-USD",
      action: "SWAP",
      status: "rejected",
      summary: "Swap rejected by local policy validation.",
      validationReason: "swap exceeds spending limit",
    },
    {
      id: "event-live",
      tick: null,
      kind: "transaction",
      agentId: "trader:0x1111111111111111111111111111111111111111",
      agentType: "trader",
      poolId: "TECH-USD",
      action: "SWAP",
      status: "confirmed",
      summary: "Live swap imported from chain.",
    } as TimelineEvent,
  ],
};

function mockFetchSequence(session: Session | null) {
  const responses = session
    ? [
        [],
        session,
        [{ id: session.id, name: session.name, source: session.source, createdAt: session.createdAt, updatedAt: session.updatedAt, summary: session.summary }],
        session,
      ]
    : [[]];
  let index = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => responses[Math.min(index++, responses.length - 1)],
    })),
  );
}

describe("dashboard app", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders an empty state when no sessions exist", async () => {
    mockFetchSequence(null);

    render(<App />);

    expect(await screen.findByText("No sessions loaded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /load sample session/i })).toBeInTheDocument();
  });

  it("imports a sample session and displays timeline details", async () => {
    mockFetchSequence(sampleSession);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /load sample session/i }));

    expect(await screen.findAllByText("Trader 0 swaps USD into TECH.")).not.toHaveLength(0);
    expect(screen.getAllByText("TECH-USD")).not.toHaveLength(0);
    expect(screen.getAllByText("0xabc0...0002")).not.toHaveLength(0);
    expect(screen.getByText("995.0000")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "rejected" } });

    await waitFor(() => {
      expect(screen.queryByText("Trader 0 swaps USD into TECH.")).not.toBeInTheDocument();
    });
    expect(screen.getAllByText("Swap rejected by local policy validation.")).not.toHaveLength(0);

    fireEvent.click(screen.getAllByText("Swap rejected by local policy validation.")[0]);

    expect(screen.getByText("swap exceeds spending limit")).toBeInTheDocument();
  });

  it("renders live imported events without a null tick label", async () => {
    mockFetchSequence(sampleSession);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /sample session/i }));

    expect(await screen.findByText("Live swap imported from chain.")).toBeInTheDocument();
    expect(screen.queryByText("Tnull")).not.toBeInTheDocument();
    expect(screen.getByText("--")).toBeInTheDocument();
  });
});
