import { describe, expect, it } from "vitest";

import { attentionItems, categoryLabel, percent } from "./analytics";

const NOTHING = {
  approvals_waiting: 0,
  drafts_ready_to_send: 0,
  outcomes_unknown: 0,
  workflows_waiting: 0,
  workflows_failed_7d: 0,
  integrations_failing: 0,
};

describe("attentionItems", () => {
  it("shows nothing when nothing is waiting", () => {
    expect(attentionItems(NOTHING)).toEqual([]);
  });

  it("puts an unknown send first, because it could become a duplicate", () => {
    const items = attentionItems({ ...NOTHING, approvals_waiting: 2, outcomes_unknown: 1 });
    expect(items.map((i) => i.key)).toEqual(["unknown", "approvals"]);
    expect(items[0]?.href).toContain("send_unknown");
    expect(items[0]?.label).toBe("email with an unknown outcome");
    expect(items[1]?.label).toBe("drafts waiting for approval");
  });
});

describe("labels", () => {
  it("rounds a rate to a whole percent", () => {
    expect(percent(0.667)).toBe("67%");
    expect(percent(0)).toBe("0%");
  });

  it("makes a stored category readable", () => {
    expect(categoryLabel("waiting_approval")).toBe("Waiting approval");
  });
});
