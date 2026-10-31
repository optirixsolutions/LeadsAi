import { describe, expect, it } from "vitest";

import { DRAFT_STATUS_LABELS, DRAFT_STATUS_TONES, nextStep } from "./outreach";

describe("nextStep", () => {
  it("tells a person to edit first when the checks require it", () => {
    expect(nextStep("draft", true)).toContain("Edit");
    expect(nextStep("draft", false)).toContain("ask for approval");
  });

  it("says who has to act on a waiting draft", () => {
    expect(nextStep("pending_approval", false)).toContain("manager or admin");
  });

  it("has nothing to suggest once a draft is finished", () => {
    expect(nextStep("sent", false)).toBe("");
    expect(nextStep("discarded", false)).toBe("");
  });
});

describe("draft statuses", () => {
  it("never calls a handed-off email delivered", () => {
    expect(DRAFT_STATUS_LABELS.sent).not.toMatch(/deliver/i);
  });

  it("gives every status a label and a tone", () => {
    expect(Object.keys(DRAFT_STATUS_TONES).sort()).toEqual(Object.keys(DRAFT_STATUS_LABELS).sort());
  });
});
