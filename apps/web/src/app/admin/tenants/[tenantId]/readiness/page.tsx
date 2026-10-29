"use client";

import { use } from "react";

import { ReadinessScreen, type RuleScreen } from "./ReadinessScreen";

/**
 * Where a readiness rule is cleared in this console.
 *
 * A `Record<string, …>` read through a miss-tolerant lookup rather than a map over a
 * union: the rule vocabulary grows whenever a gate does, and a console that only knew some
 * names would drop the rows it did not recognise — hiding a live blocker. A rule with no
 * entry renders its reason and next step with no link.
 *
 * It lives in the route module, not beside the screen, because
 * `tests/admin_account_management_test.py` reads this file to check every key is a rule the
 * gates really emit. A route module may export only `default` (D-196), so it is passed down.
 */
const RULE_SCREENS: Record<string, RuleScreen> = {
  kyc_missing: { href: (id) => `/admin/tenants/${id}/kyc`, cta: "Record verification" },
  kyc_not_verified: { href: (id) => `/admin/tenants/${id}/kyc`, cta: "Record verification" },
  national_dnd_scrub_missing: {
    href: (id) => `/admin/tenants/${id}/dnd-scrub`,
    cta: "Record the scrub",
  },
  // The cap is raised by `SpendCapPanel`, which lives on the Spend page.
  spend_cap: { href: (id) => `/admin/tenants/${id}/spend`, cta: "Open the cap" },
  no_credits: { href: (id) => `/admin/tenants/${id}/credits`, cta: "Open credits" },
  account_closed: { href: (id) => `/admin/tenants/${id}/closure`, cta: "Open closure" },
  account_suspended: { href: (id) => `/admin/tenants/${id}/lifecycle`, cta: "Open account state" },
  // The fee is recorded or waived by `PlatformFeePanel`, on the Commercials page.
  platform_fee_overdue: {
    href: (id) => `/admin/tenants/${id}/commercials`,
    cta: "Open the platform fee",
  },
  // D-692's outbound conditions beside KYC: DigiLocker when an admin required it, and the
  // pledge, both shown on the KYC page. The DLT entity chain is no longer a rule.
  kyc_digilocker_required: { href: (id) => `/admin/tenants/${id}/kyc`, cta: "Open verification" },
  outbound_pledge_missing: { href: (id) => `/admin/tenants/${id}/kyc`, cta: "Open verification" },
  outbound_pledge_outdated: { href: (id) => `/admin/tenants/${id}/kyc`, cta: "Open verification" },
  big_red_switch: { href: () => "/admin/ops", cta: "Open the ops switchboard" },
  // DELIBERATELY ABSENT: `agreements_not_accepted`. Accepting is the account owner's own
  // act and there is no admin path to it — `VIEW_AS_WITHHELD_ACTS` withholds it from a
  // view-as session for the same reason. A button here would be a door around that.
  //
  // DELIBERATELY ABSENT too: the `a2p_*` calling-number rules (D-941). The declaration is
  // the business's own statement about its numbers, the server refuses it from a view-as
  // session, and no admin screen records it; the row's next step says what to ask for.
};

export default function TenantReadinessPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <ReadinessScreen tenantId={tenantId} ruleScreens={RULE_SCREENS} />;
}
