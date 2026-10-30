import { describe, expect, it } from "vitest";

import { isActive, parseUrls, shouldPoll, statusWord } from "./workflows";

describe("run states", () => {
  it("treats a paused run as active but not worth polling", () => {
    expect(isActive("waiting_approval")).toBe(true);
    expect(shouldPoll("waiting_approval")).toBe(false);
  });

  it("stops polling once a run has ended", () => {
    for (const status of ["succeeded", "failed", "cancelled"]) {
      expect(isActive(status)).toBe(false);
      expect(shouldPoll(status)).toBe(false);
    }
  });
});

describe("parseUrls", () => {
  it("reads one address per line and ignores blanks", () => {
    expect(parseUrls(" https://a.example \n\n https://b.example/x\n")).toEqual([
      "https://a.example",
      "https://b.example/x",
    ]);
  });
});

describe("statusWord", () => {
  it("capitalizes a lead status and survives a missing value", () => {
    expect(statusWord("qualified")).toBe("Qualified");
    expect(statusWord(undefined)).toBe("");
  });
});
