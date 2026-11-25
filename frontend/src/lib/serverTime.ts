/**
 * Tracks the offset between the server clock and the browser clock.
 *
 * Auction countdowns must follow the server's notion of "now" (the server decides
 * when bidding closes). Every API response carrying `server_time` updates the offset;
 * the UI then renders countdowns from `serverNow()` instead of `Date.now()`.
 */
let offsetMs = 0;

export function syncServerTime(serverTimeIso: string, receivedAtMs: number = Date.now()): void {
  const serverMs = Date.parse(serverTimeIso);
  if (!Number.isNaN(serverMs)) {
    offsetMs = serverMs - receivedAtMs;
  }
}

export function serverNow(): number {
  return Date.now() + offsetMs;
}
