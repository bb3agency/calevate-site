import type { AdminAccess } from "@/app/admin/access";
import type { PlatformState } from "@/lib/api/admin";

/**
 * What a control on this screen needs to know: whether to enable, and what to say.
 *
 * `AdminAccess` is assignable to it — same two fields, plus a `refused` no control reads
 * — so the panels that depend on the platform ROW take `opsAccess`'s verdict and the two
 * that depend on nothing but the permission take the hook's directly. One shape, two
 * preconditions, and the difference is visible at the call site.
 */
export interface OpsAccess {
  allowed: boolean;
  /** Rendered BESIDE the dead control. Null while we do not yet know. */
  reason: string | null;
}

/**
 * May this session move a platform switch? — two conditions, and they are not the same
 * kind of thing.
 *
 * **The permission** comes from the admin realm's identity read (`useAdminAccess`), which
 * is the console's one answer to "may I" everywhere. It names `ops:manage`, and it can say
 * so before any request on this screen has failed.
 *
 * **The state** is this screen's own precondition and has nothing to do with authority:
 * never `allowed: true` without a platform response in hand, because a control that can
 * move a state we cannot read is how a halt gets lifted twice, or lifted by someone who
 * thought they were applying it. "You may not do this" and "we could not find out what
 * the switch is set to" are different sentences and only one of them is about the
 * operator, so the two conditions keep their own words.
 */
// Asserted through the DOM (tests/ops.test.tsx) rather than called directly: it used to
// live inside the route module, which may export only `default` (D-196), and the tests
// written against it that way are the ones that matter — they exercise the control.
export function opsAccess(
  access: AdminAccess,
  query: {
    data: PlatformState | undefined;
    error: unknown;
    isLoading: boolean;
  },
): OpsAccess {
  // Permission first: it is the only half that is about the OPERATOR, and while the
  // identity read is in flight it already answers `allowed: false` with no sentence, so
  // nothing here flashes an explanation it is about to withdraw.
  if (!access.allowed) return { allowed: false, reason: access.reason };
  if (query.error) {
    return {
      allowed: false,
      reason:
        "These controls are disabled because the current state could not be read. Moving a " +
        "switch we cannot see the position of is how a halt gets applied twice, or lifted " +
        "by someone who meant to apply it.",
    };
  }
  if (query.isLoading || !query.data) return { allowed: false, reason: null };
  return { allowed: true, reason: null };
}
