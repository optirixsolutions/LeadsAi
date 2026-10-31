import { describe, expect, it } from "vitest";

import { connectionError, usedShare } from "./integrations";

describe("usedShare", () => {
  it("has no meter without a limit", () => {
    expect(usedShare({ used: 5, limit: null })).toBeNull();
  });

  it("never passes full, even when a run went over its budget", () => {
    expect(usedShare({ used: 150, limit: 100 })).toBe(1);
    expect(usedShare({ used: 25, limit: 100 })).toBe(0.25);
  });
});

describe("connectionError", () => {
  it("explains known failures and has an answer for unknown ones", () => {
    expect(connectionError("login_refused")).toContain("username or password");
    expect(connectionError("something_new")).toContain("not working");
    expect(connectionError(null)).toBe("");
  });
});
