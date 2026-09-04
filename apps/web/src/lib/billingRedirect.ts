import { redirect } from "next/navigation";

/**
 * WHERE THE FOUR RETIRED BILLING ROUTES GO (D-525).
 *
 * `/c/{slug}/credits`, `/usage`, `/spend` and `/invoice` were four sidebar entries and are
 * now four TABS on `/c/{slug}/billing`. Their `page.tsx` files still exist and do exactly
 * one thing: send the reader to the tab that answers them.
 *
 * ## Why redirects and not deletions
 *
 * Because we do not control every link. A bookmark, an email we have already sent, a
 * screenshot in a support thread, a blocker's copy — all of them point at the old paths,
 * and a client whose campaigns have stopped meeting a 404 on the screen that would let
 * them fix it is the worst possible moment for a tidy-up. The redirect is four lines and
 * it never expires; deleting the routes buys nothing but four fewer files.
 *
 * ## Why a server redirect and not a `useEffect`
 *
 * No flash. A client component that navigates on mount renders SOMETHING first — an empty
 * shell, usually — and on a slow phone that is a screen that looks broken. `redirect()`
 * in a server component answers the request with the redirect itself.
 *
 * ## THE QUERY STRING IS CARRIED, AND THAT IS NOT COSMETIC
 *
 * `?view_as=admin` is how an operator's "view as client" session survives an in-realm
 * click (`lib/api/session.tsx`). A redirect that dropped it would silently hand the
 * operator a CLIENT session on the destination — which either fails to authenticate or,
 * worse, quietly answers for the wrong realm. Every other parameter rides along for the
 * same reason: we did not put it there and we do not know who needs it.
 *
 * `tab` is the one exception: it is SET, not carried, because the whole point of the
 * redirect is to choose the tab.
 */
export async function redirectToBillingTab(
  params: Promise<{ slug: string }>,
  searchParams: Promise<Record<string, string | string[] | undefined>>,
  tab: "overview" | "credits" | "transactions" | "usage",
): Promise<never> {
  const { slug } = await params;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (key === "tab" || value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item);
  }
  query.set("tab", tab);
  redirect(`/c/${slug}/billing?${query.toString()}`);
}
