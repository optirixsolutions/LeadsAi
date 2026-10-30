import { describe, expect, it } from "vitest";

import { agentFailure, tokenState } from "./agents";

const NOW = new Date("2026-10-30T12:00:00Z");

describe("tokenState", () => {
  it("reports a revoked token as revoked, even if it has also expired", () => {
    expect(tokenState({ revoked_at: "2026-10-01T00:00:00Z", expires_at: "2026-10-02T00:00:00Z" }, NOW)).toBe("revoked");
  });

  it("separates expired tokens from active ones", () => {
    expect(tokenState({ revoked_at: null, expires_at: "2026-10-30T11:59:00Z" }, NOW)).toBe("expired");
    expect(tokenState({ revoked_at: null, expires_at: "2026-11-30T00:00:00Z" }, NOW)).toBe("active");
  });
});

describe("agentFailure", () => {
  it("explains known failures and has an answer for unknown ones", () => {
    expect(agentFailure("model_not_found")).toContain("not installed");
    expect(agentFailure("something_new")).toContain("could not finish");
    expect(agentFailure(null)).toContain("could not finish");
  });
});
