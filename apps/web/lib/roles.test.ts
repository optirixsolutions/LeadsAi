import { describe, expect, it } from "vitest";

import { pickCurrentOrg } from "./org-selection";
import { assignableRoles, canManage } from "./roles";

describe("role rules mirror the API", () => {
  it("lets owners manage every role", () => {
    expect(assignableRoles("owner")).toEqual(["owner", "admin", "manager", "sales_rep", "analyst"]);
  });

  it("stops admins from creating or touching peers and owners", () => {
    expect(canManage("admin", "owner")).toBe(false);
    expect(canManage("admin", "admin")).toBe(false);
    expect(canManage("admin", "sales_rep")).toBe(true);
  });

  it("gives non-admin roles no assignment rights", () => {
    for (const role of ["manager", "sales_rep", "analyst"] as const) {
      expect(assignableRoles(role)).toEqual([]);
    }
  });
});

describe("pickCurrentOrg", () => {
  const orgs = [{ organization_id: "a" }, { organization_id: "b" }];

  it("honors a preference the user belongs to", () => {
    expect(pickCurrentOrg(orgs, "b")?.organization_id).toBe("b");
  });

  it("ignores a preference for an org the user is not in", () => {
    expect(pickCurrentOrg(orgs, "zzz")?.organization_id).toBe("a");
  });

  it("returns null when the user has no orgs", () => {
    expect(pickCurrentOrg([], "a")).toBeNull();
  });
});
