"use client";

/**
 * `app.calevate.tech/invite?token=…` — where a colleague's invite link lands.
 *
 * ## The hole this fills
 *
 * `POST /v1/invitations/accept` shipped on 2026-08-11 and nothing called it. The team
 * screen has been minting `${origin}/invite?token=…` and showing it to owners with
 * "send this to them yourself"; there was no `/invite` route, no rewrite and no
 * middleware, so every one of those links was a 404 — served to somebody holding a
 * live, single-use credential to a client's account, with the account's owner watching
 * them fail to use it. The API half and the web half of one flow, eight days apart.
 *
 * ## The decision: signing in is a STEP HERE, never a redirect and never automatic
 *
 * This is the one screen in the product a stranger reaches on purpose, and the only one
 * where they arrive already holding a credential. Two obvious designs were rejected.
 *
 * **Wrapping the route in `<ClientRealmClerkProvider protect>`** — the shape `/c/<slug>`
 * and `/admin` use — would bounce a signed-out invitee straight to Clerk. Rejected on
 * three counts: the person being bounced has no idea yet what they were sent or by
 * whom, so the sign-in card is a demand with no context; the account they need is the
 * one matching a specific address (the API binds the invitation to its recipient), and
 * a redirect cannot say so before they pick one; and `protect` is for surfaces where
 * being signed out is an ERROR, whereas here it is the expected state of a first-time
 * visitor. So the signed-out branch is a panel that explains, with the two doors on it.
 *
 * **Accepting automatically once a session exists** was rejected outright. The burn is
 * a CAS on `used_at IS NULL` and the token works exactly once, so an effect that POSTs
 * on mount spends it on a page load — including the second one React's StrictMode
 * performs in development, whose reward would be the screen telling an invitee their
 * brand-new invitation "has already been used". Acceptance is a button, pressed by the
 * person whose name the audit row (`invitation.accepted`) is about to carry.
 *
 * The sign-in and sign-up links carry `?redirect_url=/invite?token=…`, which is Clerk's
 * own mechanism rather than one invented here: `redirect_url` is in
 * `PRESERVED_QUERYSTRING_PARAMS` (`@clerk/shared/dist/router.mjs`, read from
 * node_modules at 4.28.1) and `signInFallbackRedirectUrl`'s own docstring defines the
 * fallback as applying only "if there's no `redirect_url` in the path already". That
 * precedence is what this depends on and is why the parameter is worth passing: the
 * client realm's provider sets `signUpFallbackRedirectUrl` to `/signup`, the
 * WORKSPACE-creation form, so an invitee who created an account without it would be
 * delivered to a screen inviting them to found a second, empty organization instead of
 * joining the one that asked for them.
 *
 * Putting the token in that parameter adds no meaningful exposure: it never leaves our
 * origin (`/sign-in` mounts Clerk's component path-routed), the owner sent the same
 * string over their own chat app, and the token alone is not enough — redemption still
 * requires proving control of the invited mailbox, which is the whole point of the
 * binding check.
 *
 * ## §52, which cuts harder here than anywhere
 *
 * "This invitation is invalid" is reserved for the ONE code that means it. A 500, a
 * dropped connection, an unprovisioned account, a 422 — none of those are facts about
 * the invitation, and answering any of them with the invalid panel tells somebody
 * holding a working single-use credential to throw it away and ask for another. They
 * get one. Everything unrecognised is a refusal that says the request failed, keeps the
 * button, and claims nothing about the token's state — including that it survived,
 * which a failed request cannot promise either.
 *
 * ## What this page cannot show, and does not invent
 *
 * There is no endpoint that reads an invitation by token — deliberately, since one
 * would let a stranger enumerate tenants — so this screen cannot name the business, the
 * inviter or the role BEFORE acceptance. It says so rather than filling the gap with a
 * plausible sentence. Afterwards every word comes from `AcceptInviteOut`: the slug and
 * the role, both the server's.
 */

import { Suspense } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowRight, CircleAlert, MailQuestion, ShieldCheck, UserRoundX } from "lucide-react";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import type { ApiProblem } from "@/lib/api/client";
import {
  Card,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import {
  CLIENT_SIGN_IN_PATH,
  CLIENT_SIGN_UP_PATH,
  ClientRealmClerkProvider,
  ClientRealmSignedIn,
  ClientRealmSignedOut,
} from "@/lib/auth/clientRealm";
import { lookup } from "@/lib/lookup";
import {
  ROLE_COPY,
  isInvitationForSomeoneElse,
  isInvitationUnusable,
  useAcceptInvitation,
  type AcceptedInvitation,
} from "@/lib/api/members";

/**
 * This route's own path and the parameter the token rides in.
 *
 * NOT exported: Next type-checks a route file's export surface and rejects anything that
 * is not a page field, so a route module cannot also be a constants module. They stay
 * local, and the duplicate is stated rather than hidden — `settings/team/page.tsx` builds
 * `${origin}/invite?token=…` inline, and the two spellings disagreeing is this defect
 * again. THE FOLLOW-UP: lift both into `src/lib/` and have the team screen build its link
 * from there. That file is outside this change's slice, so the pointer is left attached
 * instead of the two quietly drifting.
 */
const INVITE_PATH = "/invite";
const INVITE_TOKEN_PARAM = "token";

/** Where Clerk should send this person back to once they have an identity. */
function returnHere(token: string): string {
  return `${INVITE_PATH}?${INVITE_TOKEN_PARAM}=${encodeURIComponent(token)}`;
}

export default function InvitePage() {
  return (
    // The CLIENT Clerk application, mounted here because `/invite` is outside the
    // `/c/<slug>` shell — and NOT `protect`ed, for the reason at the top of this file.
    // In a local build it mounts nothing at all, so the identity gates below fall
    // through and the screen renders against `dev:client:` exactly as the console does.
    <ClientRealmClerkProvider>
      <Providers>
        <AuthPageFrame realmLabel="Client console">
          {/* `useSearchParams` opts this route out of static rendering and Next wants
              the bailout to have a boundary — the same reason `ClientRealmProvider`
              carries one. A skeleton rather than null: the fallback is a real loading
              state on a slow connection, and BUILD-LOG §52's rule applies to it too. */}
          <Suspense fallback={<Skeleton rows={4} />}>
            <InvitationFromLink />
          </Suspense>
        </AuthPageFrame>
      </Providers>
    </ClientRealmClerkProvider>
  );
}

/**
 * Reads the link, then hands over to identity.
 *
 * The token check comes FIRST, above the sign-in gate: a link with nothing to redeem
 * must not send anyone off to create an account they were never going to be able to use
 * it with. Same ordering, and the same reason, as `/signup`'s kill switch.
 */
function InvitationFromLink() {
  const token = (useSearchParams().get(INVITE_TOKEN_PARAM) ?? "").trim();

  if (!token) return <NoTokenInTheLink />;

  return (
    <>
      <ClientRealmSignedIn>
        <AcceptPanel token={token} />
      </ClientRealmSignedIn>
      <ClientRealmSignedOut>
        <NeedsAnIdentity token={token} />
      </ClientRealmSignedOut>
    </>
  );
}

/**
 * The link arrived without its code.
 *
 * Not "this invitation is invalid" — we have not looked at any invitation, and there is
 * no evidence one is broken. The likeliest cause is a link cut short by a chat app or a
 * mail client wrapping it, so the remedy is about the LINK, and it is one the reader can
 * act on without involving us.
 */
function NoTokenInTheLink() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">
        This link is missing its invitation code
      </h1>
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <NoticeBox
            tone="warn"
            icon={<MailQuestion aria-hidden className="h-4 w-4" />}
            title="Nothing to accept yet"
          >
            <p className="mt-1">
              An invite link ends with a long code. This one arrived without it, so there
              is nothing here to open — it does not mean the invitation is gone.
            </p>
          </NoticeBox>
          <p>
            Open the link from the original message rather than retyping it, and copy all
            of it: messaging apps often break a long link across two lines and only the
            first half becomes clickable.
          </p>
          <p>
            If that does not work, ask whoever invited you to send a fresh link — they can
            create one from Settings → Team.
          </p>
        </div>
      </Card>
    </div>
  );
}

/**
 * The stranger's panel: what they are holding, and the two doors.
 *
 * It states the address rule BEFORE they pick a door, because that is the moment the
 * warning is worth anything — after the account exists, the only remedy for choosing
 * the wrong address is asking an owner for another invitation.
 */
function NeedsAnIdentity({ token }: { token: string }) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">
        You have been invited to a Calevate account
      </h1>
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <p>
            Sign in first — the invitation is then accepted with one click on this page.
            Nothing is accepted until you press the button, and nothing here places a
            call.
          </p>
          <NoticeBox
            tone="neutral"
            icon={<ShieldCheck aria-hidden className="h-4 w-4" />}
            title="Use the address the invitation was sent to"
          >
            <p className="mt-1">
              An invitation only works for the person it was addressed to, so sign in (or
              sign up) with that email address. A different one will be refused even
              though the link itself is fine.
            </p>
          </NoticeBox>
          <div className="flex flex-wrap gap-2">
            <Link href={`${CLIENT_SIGN_IN_PATH}?redirect_url=${encodeURIComponent(returnHere(token))}`} className={PRIMARY_BUTTON}>
              Sign in to accept
              <ArrowRight aria-hidden className="h-4 w-4" />
            </Link>
            <Link href={`${CLIENT_SIGN_UP_PATH}?redirect_url=${encodeURIComponent(returnHere(token))}`} className={SECONDARY_BUTTON}>
              I do not have an account yet
            </Link>
          </div>
          <p className="text-xs text-ink-faint">
            Both doors come back to this page, so you will not need the link again.
          </p>
        </div>
      </Card>
    </div>
  );
}

/**
 * The signed-in invitee: one button, and every outcome it can have.
 *
 * The branch order is the point. `accept.data` first — a success that has already
 * happened outranks any stale error. Then the two refusals the API makes DELIBERATELY,
 * each with its own remedy. Everything else falls to the bottom, where the copy is
 * about the REQUEST and never about the invitation.
 */
function AcceptPanel({ token }: { token: string }) {
  const accept = useAcceptInvitation();

  if (accept.data) return <Joined result={accept.data} />;
  if (isInvitationUnusable(accept.error)) return <Unusable problem={accept.error} />;
  if (isInvitationForSomeoneElse(accept.error)) return <WrongRecipient problem={accept.error} />;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">
        Accept your invitation
      </h1>
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <p>
            Accepting adds you to the account that invited you. We can only tell you which
            one after you accept — an invitation names its account to the person it was
            sent to and to nobody else.
          </p>
          {/* Failure that is NOT one of the two named refusals. It says the request
              failed and stops there: this page has no way to know whether the token
              survived, and both "it is invalid" and "it is still good" would be claims
              nobody made. No `onRetry` — the button below IS the retry, and two controls
              for one action is how a person ends up pressing both. */}
          {accept.error && <ProblemNotice error={accept.error} />}
          {accept.error && (
            <p>
              Nothing was confirmed, so it is worth pressing the button again. If it keeps
              failing, ask whoever invited you for a fresh link rather than this one.
            </p>
          )}
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={accept.isPending}
            onClick={() => accept.mutate(token)}
          >
            {accept.isPending ? "Accepting…" : accept.error ? "Try again" : "Accept invitation"}
          </button>
          <p className="text-xs text-ink-faint">
            The link works once and expires 72 hours after it was created.
          </p>
        </div>
      </Card>
    </div>
  );
}

/**
 * Done — and every word of it is the server's.
 *
 * `accept.data` is set by TanStack Query only after a 2xx that parsed, so there is no
 * state this component can reach where it welcomes somebody into an account the API
 * never put them in. The role is read through `lookup` and falls back to printing the
 * raw value: `role` is a bare `string` on the wire, and a role we have no copy for is
 * exactly the one worth showing rather than hiding (src/lib/lookup.ts).
 */
function Joined({ result }: { result: AcceptedInvitation }) {
  const role = lookup(ROLE_COPY, result.role);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">You are in</h1>
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <NoticeBox
            tone="ok"
            icon={<ShieldCheck aria-hidden className="h-4 w-4" />}
            title={`You joined ${result.slug} as ${role?.label ?? result.role}`}
          >
            {role && <p className="mt-1">{role.can}</p>}
          </NoticeBox>
          <Link href={`/c/${result.slug}`} className={PRIMARY_BUTTON}>
            Open the dashboard
            <ArrowRight aria-hidden className="h-4 w-4" />
          </Link>
          <p className="text-xs text-ink-faint">
            The link you followed has been used up. Bookmark the dashboard instead — it is
            where you sign in from now on.
          </p>
        </div>
      </Card>
    </div>
  );
}

/**
 * Used, or expired — and the screen cannot tell you which, on purpose.
 *
 * The API answers one `invitation_invalid` for both states and says why in its own
 * docstring: an attacker guessing tokens must learn nothing from the difference. So the
 * copy covers both rather than picking the likelier one, and the remedy — a fresh link
 * — is the same either way. The server's own sentence leads, because it is the one
 * written against this rule.
 */
function Unusable({ problem }: { problem: ApiProblem }) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">
        This invitation cannot be used
      </h1>
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <NoticeBox
            tone="stop"
            icon={<CircleAlert aria-hidden className="h-4 w-4" />}
            title={problem.message}
          >
            <p className="mt-1">
              Invite links work once and expire 72 hours after they are created, so this
              one has either been accepted already or run out of time.
            </p>
          </NoticeBox>
          <p>{problem.remediation ?? "Ask whoever invited you to send a fresh link."}</p>
          <p className="text-xs text-ink-faint">
            Already accepted it once? Then you are a member: go to your account&apos;s
            dashboard and sign in instead of following the link again.
          </p>
          <Link href={CLIENT_SIGN_IN_PATH} className={SECONDARY_BUTTON}>
            Go to sign-in
          </Link>
        </div>
      </Card>
    </div>
  );
}

/**
 * The right link, the wrong account — the one refusal with a remedy the reader owns.
 *
 * `/sign-in` is where a signed-in visitor gets the sign-out control (that page's own
 * docstring: one URL a person can always reach to end a session), which makes it the
 * honest destination for "switch to the other address" rather than a dead sentence.
 */
function WrongRecipient({ problem }: { problem: ApiProblem }) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">
        This invitation is for a different address
      </h1>
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <NoticeBox
            tone="warn"
            icon={<UserRoundX aria-hidden className="h-4 w-4" />}
            title={problem.message}
          >
            <p className="mt-1">
              The link is fine and has not been used up — it is the account you are
              signed in with that does not match.
            </p>
          </NoticeBox>
          <p>
            {problem.remediation ??
              "Sign in with the address the invitation was sent to, or ask an owner of the account to invite the address you use."}
          </p>
          <Link href={CLIENT_SIGN_IN_PATH} className={SECONDARY_BUTTON}>
            Switch account
          </Link>
        </div>
      </Card>
    </div>
  );
}
