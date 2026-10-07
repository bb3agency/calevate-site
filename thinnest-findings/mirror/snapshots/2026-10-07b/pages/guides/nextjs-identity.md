> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Recognise signed-in customers on a Next.js site

> A complete, copy-able implementation — server component, App Router, no secret in the browser.

Twenty minutes, and your logged-in customers stop introducing themselves to your
agent every time.

<Steps>
  <Step title="Store the secret">
    From the agent's **Channels** page, under *Recognise signed-in customers*.

    ```bash .env.local theme={null}
    NEXT_PUBLIC_THINNEST_KEY=pk_your_public_key
    THINNEST_IDENTITY_SECRET=your_identity_secret
    ```

    <Warning>
      Note which one has `NEXT_PUBLIC_`. The public key is meant to reach the
      browser. **The identity secret must never.** Prefixing it would publish the
      one thing that stops any visitor forging any customer's identity.
    </Warning>
  </Step>

  <Step title="Write a server component">
    It renders the tag, and signs on the server.

    ```tsx app/_components/agent-widget.tsx theme={null}
    import { createHmac } from "node:crypto";

    import { getSession } from "@/lib/auth";

    export async function AgentWidget() {
      const publicKey = process.env.NEXT_PUBLIC_THINNEST_KEY;
      if (!publicKey) return null;

      const session = await getSession();
      const secret = process.env.THINNEST_IDENTITY_SECRET;

      // Anonymous is a perfectly good state: the widget works, the visitor is
      // just not recognised. Never emit an id without its signature — the
      // server treats an unsigned id as unverified and binds nothing to it, so
      // it would do nothing while looking exactly like a working feature.
      const identity =
        session?.user && secret
          ? {
              id: String(session.user.id),
              hmac: createHmac("sha256", secret).update(String(session.user.id)).digest("hex"),
              email: session.user.email ?? undefined,
              name: session.user.name ?? undefined,
              phone: session.user.phone ?? undefined,
            }
          : null;

      return (
        <script
          src="https://thinnest.ai/widget.js"
          data-key={publicKey}
          data-user-id={identity?.id}
          data-user-hmac={identity?.hmac}
          data-user-email={identity?.email}
          data-user-name={identity?.name}
          data-user-phone={identity?.phone}
          async
        />
      );
    }
    ```

    <Note>
      The digest is over the **id alone**. Not the id plus the email, not a JSON
      blob — just the id, as a string, exactly as it is rendered into
      `data-user-id`. A mismatch here is the most common reason signing silently
      does nothing.
    </Note>
  </Step>

  <Step title="Mount it in the layout">
    ```tsx app/layout.tsx theme={null}
    import { AgentWidget } from "./_components/agent-widget";

    export default function RootLayout({ children }: { children: React.ReactNode }) {
      return (
        <html lang="en">
          <body>
            {children}
            <AgentWidget />
          </body>
        </html>
      );
    }
    ```

    Because it is a server component it re-renders per request, so signing in
    and out is picked up without any client-side work.
  </Step>

  <Step title="Check it actually worked">
    Sign in, open the page, and view source. You should see `data-user-id` and
    `data-user-hmac`.

    Then check the important thing: **search the page source for your secret.**
    It must not be there. If it is, you prefixed it with `NEXT_PUBLIC_`.

    Finally, open the agent's **Contacts** page. Your test user should appear as
    a named contact rather than an anonymous visitor.
  </Step>
</Steps>

## Single-page apps

If you sign in without a page load, call `identify` afterwards instead:

```ts theme={null}
// The HMAC still comes from your server — fetch it, never compute it here.
const { userId, hmac } = await fetch("/api/agent-identity").then((r) => r.json());

window.ThinnestAgents?.identify({ userId, hmac, email, name });
```

```ts app/api/agent-identity/route.ts theme={null}
import { createHmac } from "node:crypto";
import { NextResponse } from "next/server";

import { getSession } from "@/lib/auth";

export async function GET() {
  const session = await getSession();
  if (!session?.user) return NextResponse.json({}, { status: 401 });

  const userId = String(session.user.id);

  return NextResponse.json({
    userId,
    hmac: createHmac("sha256", process.env.THINNEST_IDENTITY_SECRET!).update(userId).digest("hex"),
    email: session.user.email,
    name: session.user.name,
  });
}
```

<Warning>
  This route signs whoever is in the **session**. Never let it sign an id taken
  from a query string or a request body — that would hand any visitor a valid
  signature for any customer, which is precisely what the HMAC exists to
  prevent.
</Warning>

## What you get from it

* The agent greets them by name and does not ask who they are.
* Their website chat and their WhatsApp messages become **one** customer with
  one history.
* Your actions can trust the customer id, so ["where is my
  order"](/guides/order-status) needs no interrogation.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.