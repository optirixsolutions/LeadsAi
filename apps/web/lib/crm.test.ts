import { describe, expect, it } from "vitest";

import { describeActivity, formatTotals, leadName, memberName, type Activity, type Member } from "./crm";

const members = [
  { id: "m1", user_id: "u1", email: "rep@example.com", display_name: "Riley", role: "sales_rep", joined_at: "" },
] as Member[];

function activity(type: string, data: Record<string, unknown> = {}, body: string | null = null): Activity {
  return { id: "a", type, data, body, actor_user_id: null, opportunity_id: null, created_at: "" } as Activity;
}

describe("crm formatting", () => {
  it("names leads by name, then email", () => {
    expect(leadName({ first_name: "Ada", last_name: "L", email: "a@x.com" })).toBe("Ada L");
    expect(leadName({ first_name: null, last_name: null, email: "a@x.com" })).toBe("a@x.com");
    expect(leadName({ first_name: null, last_name: null, email: null })).toBe("Unnamed lead");
  });

  it("keeps currencies separate and shows a dash when empty", () => {
    expect(formatTotals({})).toBe("—");
    const text = formatTotals({ USD: "1500.00", EUR: "20.00" });
    expect(text).toContain("·");
    expect(text).toMatch(/1,500/);
  });

  it("resolves members and flags departed ones", () => {
    expect(memberName(members, "u1")).toBe("Riley");
    expect(memberName(members, null)).toBe("Unassigned");
    expect(memberName(members, "gone")).toBe("Former member");
  });

  it("describes timeline entries", () => {
    expect(describeActivity(activity("status_changed", { from: "new", to: "qualified" }), members).detail).toBe(
      "New → Qualified",
    );
    expect(describeActivity(activity("assigned", { to: "u1" }), members).detail).toBe("Riley");
    expect(describeActivity(activity("updated", { fields: ["first_name", "title"] }), members).detail).toBe(
      "first name, title",
    );
    expect(describeActivity(activity("note", {}, "Called"), members).detail).toBe("Called");
  });
});
