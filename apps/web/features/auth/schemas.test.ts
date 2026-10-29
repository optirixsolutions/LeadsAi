import { describe, expect, it } from "vitest";

import { registerSchema, resetSchema, safeNext } from "./schemas";

describe("safeNext", () => {
  it.each([
    ["/settings/team", "/settings/team"],
    ["/invite?token=abc", "/invite?token=abc"],
    [null, "/"],
    ["https://evil.example", "/"],
    ["//evil.example", "/"],
    ["/\\evil.example", "/"],
    ["javascript:alert(1)", "/"],
  ])("%s -> %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });
});

describe("form schemas", () => {
  it("rejects short passwords", () => {
    const r = registerSchema.safeParse({ display_name: "", email: "a@example.com", password: "short" });
    expect(r.success).toBe(false);
  });

  it("requires matching confirmation", () => {
    const r = resetSchema.safeParse({ new_password: "x".repeat(12), confirm: "y".repeat(12) });
    expect(r.success).toBe(false);
  });
});
