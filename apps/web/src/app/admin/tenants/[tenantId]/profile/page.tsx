"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft, CheckCircle2, Lock } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  TypedConfirmation,
  confirmationMatches,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import {
  EDIT_FIELD_COPY,
  useEditTenant,
  useTenantProfile,
  type EditTenantIn,
} from "@/lib/api/tenantProfile";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { useAdminAccess } from "@/app/admin/access";

/**
 * Correcting a client's business record — everything about it except the slug (D-546).
 *
 * `PATCH /v1/admin/tenants/{id}` shipped with D-538 and had no caller: an operator who
 * mistyped a client's name at signup, or whose client changed their contact address, had
 * no way to fix either. The route, its per-field audit rows and its notice to the replaced
 * address were all reachable by curl and by nothing on a screen.
 *
 * ## WHAT IS EDITABLE, AND WHY IT IS THREE FIELDS AND NOT FIVE
 *
 * The founder's decision was "everything except the slug", taken to the COLUMN LIST rather
 * than to a wish-list: `service.EDITABLE_TENANT_FIELDS` records what walking
 * `Organization` found. There is no `phone` and no `language` column on `organizations` —
 * the business's numbers live in the intake answer sheet and in `campaign_numbers`, and
 * the language a client is served in is per-AGENT (`agents.language_primary`), because a
 * clinic may answer in Telugu and call out in English. Everything else on the row already
 * has its own screen and its own permission.
 *
 * ## THE SLUG IS SHOWN AND CANNOT BE CHANGED
 *
 * Rendered, greyed, with the reason beside it. A field an operator cannot find is a field
 * they will ring somebody about; "it is in every URL your client has bookmarked" is the
 * answer, and a database trigger enforces it regardless of what this screen offers.
 *
 * ## THE ADDRESS TAKES A CONFIRMATION AND THE OTHER TWO DO NOT
 *
 * `billing_email` is not a sign-in identity — nobody gains access by moving it — but it IS
 * the channel every notice this account is owed is addressed from, and an unattended
 * console redirecting a business's mail is what the ceremony is for. A name or a vertical
 * redirects nothing and is corrected by typing the right value again.
 */
export default function TenantProfilePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const profile = useTenantProfile(tenantId);
  const edit = useEditTenant(tenantId);
  const write = useAdminAccess("admin:tenants", "correct a client's business record");

  /*
   * ONE CLIENT'S OWN RECORD, DECLARED TO THE SCREEN ASSISTANT.
   *
   * NO FIELDS AND NO ADDRESS. The assistant can say what the vertical decides and why the
   * slug is frozen; it may not put a value into a form whose Save re-points where a
   * business's invoices and closure notice are delivered. The billing address is not
   * declared as a FACT either — it is this client's own contact detail, it is redacted out
   * of the audit summary for the same reason, and the operator is looking straight at it.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/profile",
    title: "Business details",
    realm: "admin",
    fields: [],
    facts: profile.data
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          { key: "client", label: "Client", value: profile.data.name },
          { key: "slug", label: "Slug (frozen — it is in the client's URLs)", value: profile.data.slug },
          { key: "status", label: "Account status", value: profile.data.status },
          {
            key: "vertical_template",
            label: "Vertical template",
            value: profile.data.vertical_template ?? "none",
          },
          {
            key: "has_notice_address",
            label: "Is a notice address on file (the address itself is not sent)",
            value: profile.data.billing_email ? "yes" : "no",
          },
          {
            key: "may_edit",
            label: "May this operator correct the record",
            value: write.allowed ? "yes" : "no",
          },
        ]
      : [
          {
            key: "client",
            label: "This client",
            value: profile.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  if (profile.isLoading) return <Skeleton rows={5} />;
  // §52: a form pre-filled from a read that failed is a form that saves a guess over a
  // real value. A refusal, never a blank field that looks like an empty one.
  if (profile.error)
    return <ProblemNotice error={profile.error} onRetry={() => profile.refetch()} />;
  if (!profile.data) return <EmptyState title="Client not found" />;

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {profile.data.name}
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">Business details</h1>
        <p className="text-sm text-ink-muted">
          The client&apos;s own record. Every field you change is audited on its own, naming
          the value it replaced. Their plan, credits, phone numbers, knowledge, account
          state and closure each have their own screen; this one deliberately cannot reach
          them.
        </p>
      </div>

      <EditForm
        key={`${profile.data.name}|${profile.data.billing_email ?? ""}|${profile.data.vertical_template ?? ""}`}
        profile={profile.data}
        edit={edit}
        write={write}
      />
    </div>
  );
}

/**
 * Is this dropdown value one the server said it would accept?
 *
 * A type predicate rather than a cast: the empty string is the "Not set" sentinel for an
 * account that has no vertical yet, and every other value has to be a member of
 * `profile.verticals` — which `TenantProfileOut` derives from the PATCH's own `Literal`.
 */
function isOfferedVertical(
  value: string,
  offered: string[],
): value is NonNullable<EditTenantIn["vertical_template"]> {
  return value !== "" && offered.includes(value);
}

function EditForm({
  profile,
  edit,
  write,
}: {
  profile: NonNullable<ReturnType<typeof useTenantProfile>["data"]>;
  edit: ReturnType<typeof useEditTenant>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [name, setName] = useState(profile.name);
  const [email, setEmail] = useState(profile.billing_email ?? "");
  const [vertical, setVertical] = useState(profile.vertical_template ?? "");
  const [typed, setTyped] = useState("");

  const nameChanged = name.trim() !== profile.name;
  // Compared TRIMMED against the stored value, so re-saving the same address with a stray
  // space is not treated as a channel change and does not demand a confirmation.
  const emailChanged = email.trim() !== (profile.billing_email ?? "");
  const verticalChanged = vertical !== (profile.vertical_template ?? "");
  const changed = nameChanged || emailChanged || verticalChanged;

  // The API refuses these before it writes; the screen refuses first so an operator is told
  // before the click rather than after. The server is still the enforcement in both cases.
  const nameTooShort = nameChanged && name.trim().length < 2;
  // Deliberately the loosest possible shape check rather than a re-implementation of
  // RFC 5322: `EmailStr` on the server is the authority, and a browser-side regex that is
  // stricter than the server's parser refuses addresses that are perfectly valid.
  const emailMalformed = emailChanged && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  // An address can be CORRECTED but not REMOVED here: clearing it would leave the account
  // with no channel of record, and `notify_account_closed` then alerts
  // `account_notice_no_channel` when it has a closure notice to deliver and nowhere to
  // send it. Removing the last channel is not a correction and has no screen.
  const emailCleared = emailChanged && email.trim() === "";
  const confirmMissing = emailChanged && !confirmationMatches(typed, "CHANGE ADDRESS");
  const blocked =
    !changed || nameTooShort || emailMalformed || emailCleared || confirmMissing;

  const refusal = !changed
    ? "Nothing has changed yet."
    : nameTooShort
      ? "A business name needs at least two characters."
      : emailCleared
        ? "This account would be left with nowhere to send its notices. Correct the address rather than clearing it."
        : emailMalformed
          ? "That does not look like an email address."
          : confirmMissing
            ? "Type CHANGE ADDRESS above to confirm before this can be applied."
            : null;

  return (
    <Card title="Correct this record">
      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          // ONLY the fields that MOVED. The server compares again and returns what it
          // actually changed, but sending an unchanged address would demand a confirmation
          // header for a change nobody made.
          const body: EditTenantIn = {};
          if (nameChanged) body.name = name.trim();
          if (emailChanged) body.billing_email = email.trim();
          // NARROWED BY A PREDICATE, never asserted. `isOfferedVertical` checks the value
          // against the list the SERVER sent, which the API derives from the same `Literal`
          // the PATCH validates against — so the type and the check are the same fact. An
          // `as` here would be an instruction to stop checking exactly that.
          if (verticalChanged && isOfferedVertical(vertical, profile.verticals)) {
            body.vertical_template = vertical;
          }
          edit.mutate(body);
        }}
      >
        <RestrictionNote reason={write.reason} />

        <div>
          <label htmlFor="tenant-name" className={FIELD_LABEL}>
            {EDIT_FIELD_COPY.name.label}
          </label>
          <input
            id="tenant-name"
            value={name}
            maxLength={200}
            disabled={!write.allowed}
            onChange={(event) => {
              setName(event.target.value);
              edit.reset();
            }}
            className={FIELD}
          />
          <span className={FIELD_HINT}>{EDIT_FIELD_COPY.name.hint}</span>
        </div>

        <div>
          <span className={FIELD_LABEL}>Web address</span>
          <p className="mt-1 flex items-center gap-2 text-sm text-ink">
            <Lock className="h-3.5 w-3.5 text-ink-faint" aria-hidden />
            <MonoValue>{`/c/${profile.slug}`}</MonoValue>
          </p>
          <span className={FIELD_HINT}>
            Frozen, and not because nobody built the form: this is in every link the client
            has bookmarked and in every URL their staff use, and the database refuses to
            change it. A client who needs a different one needs a new account.
          </span>
        </div>

        <div>
          <label htmlFor="tenant-billing-email" className={FIELD_LABEL}>
            {EDIT_FIELD_COPY.billing_email.label}
          </label>
          <input
            id="tenant-billing-email"
            type="email"
            value={email}
            maxLength={254}
            disabled={!write.allowed}
            onChange={(event) => {
              setEmail(event.target.value);
              edit.reset();
            }}
            className={FIELD}
          />
          <span className={FIELD_HINT}>{EDIT_FIELD_COPY.billing_email.hint}</span>
        </div>

        <div>
          <label htmlFor="tenant-vertical" className={FIELD_LABEL}>
            {EDIT_FIELD_COPY.vertical_template.label}
          </label>
          <select
            id="tenant-vertical"
            value={vertical}
            disabled={!write.allowed}
            onChange={(event) => {
              setVertical(event.target.value);
              edit.reset();
            }}
            className={FIELD}
          >
            {/* The options come from the API, not from a list retyped here: a vertical
                added to the server's `Literal` appears in this dropdown without an edit,
                and one removed stops being offered. */}
            {profile.vertical_template == null && <option value="">Not set</option>}
            {profile.verticals.map((choice) => (
              <option key={choice} value={choice}>
                {choice.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          <span className={FIELD_HINT}>{EDIT_FIELD_COPY.vertical_template.hint}</span>
        </div>

        {emailChanged && (
          <TypedConfirmation
            phrase="CHANGE ADDRESS"
            binding={`Bound to ${profile.name}. Every notice this account is owed — the invoice, the hot-lead alert, the closure notice and its erasure date — is addressed from this field, and the address being replaced is told that it changed.`}
            value={typed}
            onChange={(value) => {
              setTyped(value);
              edit.reset();
            }}
            disabled={!write.allowed}
          />
        )}

        <div className="flex flex-wrap items-center gap-3">
          <ActionButton
            type="submit"
            loading={edit.isPending}
            disabled={blocked || !write.allowed}
          >
            Save changes
          </ActionButton>
          {refusal != null && (
            <span className="text-xs text-amber-700 dark:text-amber-400">{refusal}</span>
          )}
        </div>
      </form>

      {edit.error != null && <ProblemNotice error={edit.error} />}
      {edit.data != null && (
        <NoticeBox
          tone={edit.data.changed.length > 0 ? "ok" : "neutral"}
          icon={<CheckCircle2 className="h-5 w-5" />}
        >
          <p className="text-xs">
            {edit.data.changed.length === 0
              ? "Nothing moved — the values sent were the ones already on file, so no audit row was written."
              : `Saved: ${edit.data.changed
                  .map((field) => EDIT_FIELD_COPY[field as keyof EditTenantIn]?.label ?? field)
                  .join(", ")}. Each change is audited on its own, naming the value it replaced.`}
          </p>
          {edit.data.changed.includes("billing_email") && (
            <p className="mt-1 text-xs">
              The previous address has been told that this account&apos;s notices now go
              elsewhere, and given a way to object.
            </p>
          )}
          {edit.data.pending_notices_retargeted > 0 && (
            /* SAID, NOT SWALLOWED. The worker resolves a notice's recipients when it
               delivers, so notices already queued now go to the new address. That is kept
               on purpose — the alternative mails a client's closure notice to the dead
               mailbox an operator just replaced — but it must never happen silently. */
            <p className="mt-1 text-xs font-medium">
              {edit.data.pending_notices_retargeted} notice
              {edit.data.pending_notices_retargeted === 1 ? " was" : "s were"} already queued
              for this account and had not been sent. {edit.data.pending_notices_retargeted === 1 ? "It" : "They"}{" "}
              will be delivered to the new address.
            </p>
          )}
        </NoticeBox>
      )}
    </Card>
  );
}
