import { describe, expect, it } from "vitest";

import { componentFill, parseList, parseOptionalInt } from "./intelligence";

describe("parseList", () => {
  it("splits on commas and new lines, trims, and drops blanks", () => {
    expect(parseList(" Fintech, SaaS\n,,  Retail ")).toEqual(["Fintech", "SaaS", "Retail"]);
  });

  it("keeps the first spelling of a repeated term", () => {
    expect(parseList("Fintech, fintech, FINTECH")).toEqual(["Fintech"]);
  });

  it("returns nothing for blank input", () => {
    expect(parseList("   ")).toEqual([]);
  });
});

describe("parseOptionalInt", () => {
  it("treats blank as not set", () => {
    expect(parseOptionalInt("  ")).toBeNull();
  });

  it("accepts whole numbers and rejects anything else", () => {
    expect(parseOptionalInt("250")).toBe(250);
    expect(parseOptionalInt("2.5")).toBeUndefined();
    expect(parseOptionalInt("-1")).toBeUndefined();
    expect(parseOptionalInt("ten")).toBeUndefined();
  });
});

describe("componentFill", () => {
  it("shows unconfigured components as empty and clamps to the bar", () => {
    expect(componentFill(null)).toBe(0);
    expect(componentFill(0.5)).toBe(50);
    expect(componentFill(1.4)).toBe(100);
  });
});
