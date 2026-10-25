// Memory-only UI protection. The server remains authoritative; expiry never retries.
export function createAuthCooldown(now = Date.now) {
  let until = 0;
  return {
    remaining: () => Math.max(0, Math.ceil((until - now()) / 1000)),
    record(error) {
      if (error?.status !== 429) return;
      const delay = error.retryAfterSeconds;
      // Without a usable Retry-After, pause for a minute, not a claimed quota reset.
      const seconds = Number.isInteger(delay) && delay >= 1 && delay <= 86400 ? delay : 60;
      until = Math.max(until, now() + seconds * 1000);
    },
  };
}
