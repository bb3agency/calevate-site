# Login and sign up

> Sign in and sign up pages, from a compact code card to full screen split and immersive layouts.

- Type: Block with 5 variants
- Page: https://uiarc.dev/components/blocks/login
- Markdown: https://uiarc.dev/components/blocks/login/markdown

Open a specific variant with `?variant=<id>`: `sign-in`, `login-centered`, `login-split`, `login-immersive`, `signup-form`

## Variant: Email code

A sign in card that morphs from email to a six digit code to your account.

- Access: Free, open source
- Registry id: `sign-in`
- Source file: `registry/blocks/sign-in/sign-in.tsx`
- Built from: Input, OTP input, Button, Avatar
- Keywords: react sign in, passwordless login, email code login, magic code sign in, passkey login, sso buttons, otp login

Use this as the entry to your app. Send and check codes through your auth provider, connect the passkey button to WebAuthn and the single sign-on buttons to OAuth; everything in the preview is simulated.

### When to use

- The entry screen of an app with email code sign in.
- Sign in cards that also offer passkeys and single sign-on.
- Passwordless flows that should confirm the account before continuing.

### When not to use

- Use login-centered, login-split, or login-immersive for password based layouts.
- Use signup-form to create an account.
- Use otp-input on its own when the code step lives in your own form.

### Installation

#### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/sign-in
pnpm dlx shadcn@latest add @uiarc/sign-in
yarn dlx shadcn@latest add @uiarc/sign-in
bunx --bun shadcn@latest add @uiarc/sign-in
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/sign-in.json
```

#### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/blocks/sign-in/sign-in.tsx`

   The source is in the registry item: https://uiarc.dev/r/sign-in.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

### Usage

```tsx
import { SignIn } from "@/components/arc/blocks/sign-in/sign-in";
import { useRouter } from "next/navigation";

export function SignInPage() {
  const router = useRouter();

  return <SignIn onSignIn={() => router.push("/dashboard")} />;
}
```

### API reference

#### SignIn

A sign in card that moves from email to a six digit code to a signed in account, with passkey and single sign-on buttons. Sending and checking codes is simulated.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `demoCode` | `string` | `"123456"` | The code the simulated email contains. |
| `onSignIn` | `(account: SignInAccount, method: SignInMethod) => void` | – | Called once sign in succeeds. SignInAccount is { name, email, photo? }; SignInMethod is "Email code", "Passkey", "Google", "Apple", or "GitHub". |

### Accessibility

- Single sign-on providers are a labelled group of buttons with visible names.
- Step changes and errors are announced through a visually hidden role="status" region.
- Provider marks are aria-hidden SVGs next to text labels.

### Motion

- The card morphs its height between the email, code, and done steps, sliding content in the direction of travel.
- Reduced motion swaps the slide for a plain fade.

### Responsive behavior

- The card is a container; below 380px its padding and heading shrink, and the provider buttons tighten.
- Below a 480px viewport the card corners soften to the panel radius.

### Performance

- A ResizeObserver drives the height morph between steps.
- The signed in avatar reuses the same image through a layoutId, so the morph does not wait on a second image.

### Notes for AI

- Use as the entry screen of an app.
- Send and verify codes through your auth provider instead of demoCode, connect the passkey button to WebAuthn, and the provider buttons to OAuth.
- Composes Arc input, otp-input, button, and avatar; exports SignInAccount and SignInMethod types.

### Related

- [OTP input](https://uiarc.dev/components/blocks/otp-input/markdown): A six digit verification flow with paste support and keyboard navigation.
- [Login and sign up: Centered](https://uiarc.dev/components/blocks/login/markdown): A passkey-first login card on a quiet ring backdrop that morphs through email and code.
- [Login and sign up: Split](https://uiarc.dev/components/blocks/login/markdown): A full screen split login: an email-first form that morphs into a password step beside a photo.
- [Login and sign up: Sign up](https://uiarc.dev/components/blocks/login/markdown): An account creation flow with field validation, password strength, and a clear completion state.
- [Password field](https://uiarc.dev/components/password-field/markdown): Capture sensitive text with a visible reveal control.

## Variant: Centered

A passkey-first login card on a quiet ring backdrop that morphs through email and code.

- Access: Free, open source
- Registry id: `login-centered`
- Source file: `registry/blocks/login-centered/login-centered.tsx`
- Built from: Button, Input, OTP input
- Keywords: react login page, passkey login, sign in page, otp email login, webauthn sign in ui, sign up page, auth card

Use this as a full screen sign in page (pass fullScreen). Connect the passkey button to WebAuthn, the email step to your magic code sender, the code step to verification, and the SSO buttons to your OAuth routes; onSignIn receives the email, method and mode.

### When to use

- A full screen sign in or sign up page where passkeys are the main method.
- Auth flows that fall back to a six digit email code.
- Products that want one card for both sign in and sign up.

### When not to use

- Use login-split for password sign in beside a brand photo.
- Use login-immersive for magic link auth over a full-bleed photo.
- Use sign-in for a simpler embedded sign in form.

### Installation

#### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/login-centered
pnpm dlx shadcn@latest add @uiarc/login-centered
yarn dlx shadcn@latest add @uiarc/login-centered
bunx --bun shadcn@latest add @uiarc/login-centered
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/login-centered.json
```

#### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/blocks/login-centered/login-centered.tsx`

   The source is in the registry item: https://uiarc.dev/r/login-centered.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

### Usage

```tsx
import { LoginCentered } from "@/components/arc/blocks/login-centered/login-centered";
import { useRouter } from "next/navigation";

export default function SignInPage() {
  const router = useRouter();
  return (
    <LoginCentered
      fullScreen
      termsHref="/terms"
      privacyHref="/privacy"
      onSignIn={() => router.push("/app")}
    />
  );
}
```

### Examples

#### Route sign ups to onboarding

```tsx
<LoginCentered
  fullScreen
  onSignIn={(email, method, mode) =>
    router.push(mode === "sign-up" ? "/welcome" : "/app")
  }
/>
```

### API reference

#### LoginCentered

A passkey-first sign in and sign up card on a ring backdrop that morphs through email and a six digit code. Passkey, email delivery and SSO are simulated.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `fullScreen` | `boolean` | `false` | Fill the viewport (100dvh, no frame) when the block is the whole page. |
| `onSignIn` | `(email: string, method: LoginMethod, mode: "sign-in" \| "sign-up") => void` | – | Called once the simulated sign in or sign up succeeds. LoginMethod is "Passkey" \| "Email code" \| "Google" \| "Apple" \| "GitHub". |
| `demoCode` | `string` | `"482913"` | The code the simulated email contains. |
| `demoEmail` | `string` | `"maya@northwind.studio"` | The account a simulated passkey or single sign-on resolves to. |
| `termsHref` | `string` | `"#terms"` | Terms link in the footer. |
| `privacyHref` | `string` | `"#privacy"` | Privacy link in the footer. |
| `className` | `string` | – | Appended to the root element. |

### Accessibility

- The email field uses autoComplete="email" and the code step uses the OTP input group.
- Busy buttons use aria-busy and aria-disabled so focus stays put during simulated requests.
- A polite role="status" region announces step changes and errors.

### Motion

- Steps slide and blur between passkey, email, code and done while the card height follows; the resend label rolls.
- Reduced motion swaps slides for fades and shows the passkey check without drawing its stroke.

### Responsive behavior

- Below a 520px container the stage and card padding shrink, and below 400px the SSO buttons tighten to small text.
- Pass fullScreen to fill 100dvh; without it the block sits in a framed card.
- The ring backdrop drifts with the pointer only while it moves over the screen, and stays still on touch and under reduced motion.

### Performance

- The backdrop is a light SVG ring set moved by CSS variables from motion values, with no re-render per pointer move.
- Only the active step is mounted; the card height animates as steps change.

### Notes for AI

- Use as a full screen sign in page (pass fullScreen) when passkeys are the primary method.
- Connect the passkey button to WebAuthn, the email step to your code sender, the code step to verification and SSO buttons to OAuth routes; demoCode and demoEmail exist only for the simulation.
- onSignIn receives the email, method and mode; redirect from there.
- Composes Arc Button, Input and OTP input.

### Related

- [Login and sign up: Email code](https://uiarc.dev/components/blocks/login/markdown): A sign in card that morphs from email to a six digit code to your account.
- [Login and sign up: Split](https://uiarc.dev/components/blocks/login/markdown): A full screen split login: an email-first form that morphs into a password step beside a photo.
- [Login and sign up: Immersive](https://uiarc.dev/components/blocks/login/markdown): A glass magic link card over dusk photography that folds its envelope shut once sent.
- [Login and sign up: Sign up](https://uiarc.dev/components/blocks/login/markdown): An account creation flow with field validation, password strength, and a clear completion state.
- [OTP input](https://uiarc.dev/components/blocks/otp-input/markdown): A six digit verification flow with paste support and keyboard navigation.

## Variant: Split

A full screen split login: an email-first form that morphs into a password step beside a photo.

- Access: Arc Pro
- Registry id: `login-split`
- Source file: `registry/blocks/login-split/login-split.tsx`
- Built from: Button, Input, Password field, Avatar
- Keywords: react split login page, login with image, email first login, password sign in page, two column login, sign in screen

Use this as your sign in page with fullScreen. Connect Continue to your account lookup, Sign in and the SSO buttons to your auth provider, Forgot password to your reset email, and pass links for sign up, terms and privacy.

### When to use

- Password-based sign in with an email-first step beside a brand photo.
- Sign in pages that should show the recognised account before asking for a password.

### When not to use

- Use login-centered for passkey-first auth.
- Use login-immersive for magic link auth.
- Use signup-form for account creation.

### Installation

Variant: Split is part of Arc Pro. The live preview is public; the source and install command need Pro.

#### CLI with a Pro token

1. Create a token in your account and set it in the environment (or `.env.local`). Never commit it.

```bash
export ARC_PRO_TOKEN=arc_pro_...
```

2. Add the Pro registry to `components.json`:

```json
{
  "registries": {
    "@uiarc": "https://uiarc.dev/r/{name}.json",
    "@uiarc-pro": {
      "url": "https://uiarc.dev/r/pro/{name}.json",
      "headers": {
        "Authorization": "Bearer ${ARC_PRO_TOKEN}"
      }
    }
  }
}
```

3. Install:

```bash
npx shadcn@latest add @uiarc-pro/login-split
```

#### Manual

Signed-in Pro members can copy the source from the Manual tab on the docs page.

- Plans: https://uiarc.dev/pricing
- Create a Pro token: https://uiarc.dev/account#pro-access
- Setup guide: https://uiarc.dev/docs/ai#pro-access

### Usage

```tsx
import { LoginSplit } from "@/components/arc/blocks/login-split/login-split";

export default function SignInPage() {
  return (
    <LoginSplit
      fullScreen
      links={{ signUp: "/sign-up", terms: "/terms", privacy: "/privacy" }}
      onSignIn={(account, method) => console.log(account.email, method)}
    />
  );
}
```

### Examples

#### Real links

```tsx
<LoginSplit
  fullScreen
  links={{ signUp: "/sign-up", terms: "/terms", privacy: "/privacy" }}
  onSignIn={account => router.push("/app")}
/>
```

### API reference

#### LoginSplit

A split sign in screen: an email-first form that morphs into a password step beside a photo. Accounts are the sample people list in login-split.tsx with portraits from public/media/people, and the photo is imported from public/media/photos/concert-hall.jpg.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `fullScreen` | `boolean` | `false` | Fill the viewport (100dvh, no frame) when the screen is used as a page. |
| `onSignIn` | `(account: LoginSplitAccount, method: LoginSplitMethod) => void` | – | Called once the simulated sign in finishes. LoginSplitAccount is { name, email, photo? }; LoginSplitMethod is "Password" \| "Google" \| "Apple" \| "GitHub". |
| `demoPassword` | `string` | `"arc-demo"` | The password the simulated account accepts. |
| `links` | `Partial<Record<"signUp" \| "terms" \| "privacy", string>>` | – | Real destinations for the small links. Without them each link announces a simulated action. |

### Accessibility

- Fields use autoComplete="username" and "current-password"; errors render in a role="alert" tied with aria-describedby and aria-invalid.
- SSO buttons sit in a labelled role="group".
- A polite role="status" region announces step changes and simulated link actions.

### Motion

- Continue morphs the email form into the password step with the account avatar, and labels roll between states.
- Reduced motion uses fades and shortens the simulated delays.

### Responsive behavior

- Below a 760px container the photo stacks under the form at a 460px minimum height; from 760px they sit side by side.
- From 1100px the columns split 5 to 6 and the quote moves to the photo's lower left.
- The photo uses sizes that request 100vw below 760px and 50vw above.

### Performance

- The photo drifts on a 36 second CSS animation that people can pause, and it is off under reduced motion.
- The photo loads through next/image with a blur placeholder; there are no scripts running while idle.

### Notes for AI

- Use as a password-based sign in page with fullScreen.
- Connect Continue to your account lookup, Sign in and SSO to your auth provider, and Forgot password to your reset email; replace the sample people list and the imported photo.
- Pass links for sign up, terms and privacy; onSignIn receives the account and method.
- Uses next/image; composes Arc Button, Input, Password field and Avatar.

### Related

- [Login and sign up: Centered](https://uiarc.dev/components/blocks/login/markdown): A passkey-first login card on a quiet ring backdrop that morphs through email and code.
- [Login and sign up: Immersive](https://uiarc.dev/components/blocks/login/markdown): A glass magic link card over dusk photography that folds its envelope shut once sent.
- [Login and sign up: Email code](https://uiarc.dev/components/blocks/login/markdown): A sign in card that morphs from email to a six digit code to your account.
- [Login and sign up: Sign up](https://uiarc.dev/components/blocks/login/markdown): An account creation flow with field validation, password strength, and a clear completion state.
- [Password field](https://uiarc.dev/components/password-field/markdown): Capture sensitive text with a visible reveal control.

## Variant: Immersive

A glass magic link card over dusk photography that folds its envelope shut once sent.

- Access: Arc Pro
- Registry id: `login-immersive`
- Source file: `registry/blocks/login-immersive/login-immersive.tsx`
- Built from: Button, Input
- Keywords: react magic link login, passwordless sign in, login page with background image, glass login card, email link sign in, full screen login

Use this as a full screen sign in or sign up page (pass fullScreen). Connect the email form to your magic link sender, Open mail app to a mailto or deep link, and the SSO buttons to your OAuth routes; onSignIn receives the email and method.

### When to use

- A magic link sign in page with a strong brand photo behind a glass card.
- Consumer or creative products where the sign in screen carries the brand mood.

### When not to use

- Use login-centered for passkey-first auth with an email code.
- Use login-split for password sign in with a quieter layout.
- Use sign-in when the form sits inside an existing page.

### Installation

Variant: Immersive is part of Arc Pro. The live preview is public; the source and install command need Pro.

#### CLI with a Pro token

1. Create a token in your account and set it in the environment (or `.env.local`). Never commit it.

```bash
export ARC_PRO_TOKEN=arc_pro_...
```

2. Add the Pro registry to `components.json`:

```json
{
  "registries": {
    "@uiarc": "https://uiarc.dev/r/{name}.json",
    "@uiarc-pro": {
      "url": "https://uiarc.dev/r/pro/{name}.json",
      "headers": {
        "Authorization": "Bearer ${ARC_PRO_TOKEN}"
      }
    }
  }
}
```

3. Install:

```bash
npx shadcn@latest add @uiarc-pro/login-immersive
```

#### Manual

Signed-in Pro members can copy the source from the Manual tab on the docs page.

- Plans: https://uiarc.dev/pricing
- Create a Pro token: https://uiarc.dev/account#pro-access
- Setup guide: https://uiarc.dev/docs/ai#pro-access

### Usage

```tsx
import { LoginImmersive } from "@/components/arc/blocks/login-immersive/login-immersive";

export default function SignInPage() {
  return (
    <LoginImmersive
      fullScreen
      termsHref="/terms"
      privacyHref="/privacy"
      onSignIn={(email, method) => console.log(email, method)}
    />
  );
}
```

### API reference

#### LoginImmersive

A glass magic link card over a full-bleed photo whose envelope folds shut once the link is sent. The photo is imported from public/media/photos/mountain-ridges.jpg; sending and SSO are simulated.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `fullScreen` | `boolean` | `false` | Fill the viewport (100dvh, square corners) when the block is the whole page. |
| `onSignIn` | `(email: string, method: LoginImmersiveMethod) => void` | – | Called once the simulated sign in succeeds. LoginImmersiveMethod is "Magic link" \| "Google" \| "Apple" \| "GitHub". |
| `resendSeconds` | `number` | `30` | Seconds before another link can be sent. |
| `termsHref` | `string` | – | Terms link. Without it the preview explains where the link would go. |
| `privacyHref` | `string` | – | Privacy link. Without it the preview explains where the link would go. |

### Accessibility

- The email field uses autoComplete="email" and SSO buttons sit in a labelled role="group".
- Busy actions use aria-disabled rather than disabled so focus is kept.
- A polite role="status" region announces when the link is sent and resend availability.

### Motion

- After sending, the form gives way to an envelope that folds shut and the resend countdown rolls.
- Reduced motion replaces the fold and slides with fades.

### Responsive behavior

- The card is min(100%, 420px) wide; below a 380px card width its padding and heading shrink and the SSO buttons tighten.
- Below a 520px container the top bar and footer padding shrink.
- The photo uses next/image with fill and sizes 100vw, so it covers any viewport.

### Performance

- The photo loads eagerly with a blur placeholder; use a well compressed image since it is the largest asset.
- The card uses backdrop blur, which falls back to a solid surface where backdrop-filter is not supported.

### Notes for AI

- Use as a full screen sign in or sign up page for magic link auth with a strong brand photo.
- Replace the imported photo with your own, connect the email form to your magic link sender, Open mail app to a mailto or deep link, and SSO to OAuth routes.
- Uses next/image; composes Arc Button and Input.

### Related

- [Login and sign up: Centered](https://uiarc.dev/components/blocks/login/markdown): A passkey-first login card on a quiet ring backdrop that morphs through email and code.
- [Login and sign up: Split](https://uiarc.dev/components/blocks/login/markdown): A full screen split login: an email-first form that morphs into a password step beside a photo.
- [Login and sign up: Email code](https://uiarc.dev/components/blocks/login/markdown): A sign in card that morphs from email to a six digit code to your account.
- [Login and sign up: Sign up](https://uiarc.dev/components/blocks/login/markdown): An account creation flow with field validation, password strength, and a clear completion state.

## Variant: Sign up

An account creation flow with field validation, password strength, and a clear completion state.

- Access: Free, open source
- Registry id: `signup-form`
- Source file: `registry/blocks/signup-form/signup-form.tsx`
- Built from: Input, Password field, Checkbox, Button
- Keywords: react signup form, sign up page, registration form, create account form, password strength form, email password signup

Use this as the client side of an account flow. Supply an onSubmit handler that creates the account and handles server errors.

### When to use

- The client side of an email and password sign-up.
- Sign-up pages that should show password strength and a product updates opt-in.
- Flows that want an in-place success panel after the account is created.

### When not to use

- Use sign-in or login-split for returning users.
- Use password-field alone when the form is already built.
- Use otp-input for passwordless or code-based sign-up.

### Installation

#### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/signup-form
pnpm dlx shadcn@latest add @uiarc/signup-form
yarn dlx shadcn@latest add @uiarc/signup-form
bunx --bun shadcn@latest add @uiarc/signup-form
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/signup-form.json
```

#### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/blocks/signup-form/signup-form.tsx`

   The source is in the registry item: https://uiarc.dev/r/signup-form.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

### Usage

```tsx
import { SignupForm, type SignupDetails } from "@/components/arc/blocks/signup-form/signup-form";

export function SignUpPage() {
  const [error, setError] = useState<string | null>(null);
  async function create(details: SignupDetails) {
    const res = await fetch("/api/sign-up", { method: "POST", body: JSON.stringify(details) });
    if (!res.ok) setError("That email is already registered.");
  }
  return <SignupForm onSubmit={create} serverError={error} onProvider={provider => signIn(provider.toLowerCase())} />;
}
```

### API reference

#### SignupForm

An account creation card: Google, Apple, and GitHub buttons, then name, email, password with strength, a product updates opt-in, and a completion state whose check draws itself in.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `onSubmit` | `(details: SignupDetails) => void \| Promise<void>` | – | Called with valid details. Awaited; a thrown error shows a submit error. |
| `serverError` | `string \| null` | – | External error message shown under the form, for example from your auth API. |
| `onProvider` | `(provider: "Google" \| "Apple" \| "GitHub") => void` | – | Called when a provider button is pressed. Start your OAuth redirect here. Without a redirect, the block simulates the provider and shows the completion state after 900ms. |

#### SignupDetails

Type passed to onSubmit.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `name` (required) | `string` | – | Full name, at least 2 characters. |
| `email` (required) | `string` | – | Email that passed a basic format check. |
| `password` (required) | `string` | – | Password of 8 or more characters. |
| `productUpdates` (required) | `boolean` | – | Opt-in checkbox state. |

### Accessibility

- Invalid fields set aria-invalid and point aria-describedby at their message.
- Field and submit errors use role="alert"; the success panel uses role="status".
- Provider buttons have labels like "Sign up with Google"; while one is busy the others are aria-disabled.
- Password strength is shown as text, not only color.

### Motion

- The card height springs between the form and the completion panel, which slides in while the form exits.
- The completion ring and check draw themselves in with pathLength.
- Reduced motion drops the offsets and blur and uses zero durations.

### Responsive behavior

- Container query: below 380px of card width the padding, heading, and provider button text shrink so fields keep their width.
- Below 480px viewport width the card uses the smaller panel radius.

### Performance

- Validation is local and synchronous; the card height is a motion value measured with a layout effect, so swapping steps does not reflow the page.
- Strength bars animate with CSS transitions, turned off under reduced motion.

### Notes for AI

- Use as the client side of an email and password sign-up with optional social providers.
- Wire onProvider to your auth library's OAuth sign-in; the built-in provider flow is a simulation.
- Validation is local; keep server checks in onSubmit and pass their message through serverError.
- Composes Arc Button, Checkbox, Input, and PasswordField.

### Related

- [Login and sign up: Email code](https://uiarc.dev/components/blocks/login/markdown): A sign in card that morphs from email to a six digit code to your account.
- [Login and sign up: Split](https://uiarc.dev/components/blocks/login/markdown): A full screen split login: an email-first form that morphs into a password step beside a photo.
- [Password field](https://uiarc.dev/components/password-field/markdown): Capture sensitive text with a visible reveal control.
- [Password strength](https://uiarc.dev/components/password-strength/markdown): Show how strong a new password is while it is typed.
- [OTP input](https://uiarc.dev/components/blocks/otp-input/markdown): A six digit verification flow with paste support and keyboard navigation.

## Guidance for AI tools

Blocks are complete, self-contained screens with sample data. Replace the sample data and connect the callbacks described above. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
