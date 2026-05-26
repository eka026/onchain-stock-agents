import type { EventFilters, TimelineEvent } from "./types";

const TOKEN_DECIMALS = 18n;
const TOKEN_SCALE = 10n ** TOKEN_DECIMALS;
const DISPLAY_SCALE = 10_000n;

export function formatAmount(value: string): string {
  try {
    const amount = BigInt(value);
    const sign = amount < 0n ? "-" : "";
    const absolute = amount < 0n ? -amount : amount;
    const rounded = (absolute * DISPLAY_SCALE + TOKEN_SCALE / 2n) / TOKEN_SCALE;
    const whole = rounded / DISPLAY_SCALE;
    const fraction = rounded % DISPLAY_SCALE;
    const fixedFraction = fraction.toString().padStart(4, "0");
    return `${sign}${whole.toString()}.${fixedFraction}`;
  } catch {
    return value;
  }
}

export function shortenAddress(value: string): string {
  if (!value.startsWith("0x") || value.length < 14) {
    return value;
  }
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

export function filterEvents(events: TimelineEvent[], filters: EventFilters): TimelineEvent[] {
  return events.filter((event) => {
    if (filters.kind && filters.kind !== "all" && event.kind !== filters.kind) {
      return false;
    }
    if (filters.status && filters.status !== "all" && event.status !== filters.status) {
      return false;
    }
    if (filters.poolId && filters.poolId !== "all" && event.poolId !== filters.poolId) {
      return false;
    }
    if (filters.agentId && filters.agentId !== "all" && event.agentId !== filters.agentId) {
      return false;
    }
    return true;
  });
}
