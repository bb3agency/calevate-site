> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Console Login & Signup - Sign In or Create Your Voice Infrastructure Account

> Sign in to console.vobiz.ai or create a new Vobiz account. Step-by-step walkthrough of email + password, Google SSO, password reset, and the 3-step signup flow. New accounts include ₹25 free credit.

The **Vobiz Console** at `console.vobiz.ai` is your control panel for the Vobiz voice platform - buying phone numbers, configuring SIP trunks, building XML applications, running outbound campaigns, and monitoring every call your account makes. This page covers both **signing in** to an existing account and **creating a new account** from scratch.

<CardGroup cols={2}>
  <Card title="Already have an account?" icon="right-to-bracket" href="#sign-in">
    Sign in with email + password or Google SSO.
  </Card>

  <Card title="New to Vobiz?" icon="user-plus" href="#create-an-account">
    3‑step signup with ₹25 free credit to make your first call.
  </Card>
</CardGroup>

## Sign in

```text Login URL theme={null}
https://console.vobiz.ai/auth/login
```

<Tip>
  Already have a Vobiz account? Open the URL above and sign in with the email + password you used at signup, or jump straight to **[Continue with Google](#sign-in-with-google)** if you registered through Google SSO.
</Tip>

### The login screen at a glance

The Vobiz login page is split into two halves: a branded marketing panel on the left and the sign‑in form on the right.

<Frame caption="Vobiz Console - login page (console.vobiz.ai/auth/login)">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/auth/login-page.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=e87bb9e3f0e1aba9b2a6637151e48956" alt="Vobiz Console login screen featuring email and password fields, Continue with Google SSO button, and the AI-First Voice Infrastructure Platform marketing panel on the left side" style={{maxWidth: '760px', margin: '0 auto', display: 'block'}} width="2000" height="1111" data-path="images/platform/auth/login-page.png" />
</Frame>

* **Left panel** - branding and the *AI‑First Voice Infrastructure Platform* tagline. Decorative; nothing to click.
* **Right panel** - the live sign‑in form. Everything below documents this side.
* **Top‑right link** - *Don't have an Account? **Create an Account*** jumps to the [signup flow](#create-an-account) below.

### Sign in with email + password

The default sign‑in method. Use the email and password you set when you signed up for Vobiz.

<Frame caption="Email + password form">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/auth/login-form_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=b0a6440d71d12486ff32f4526fb1e393" alt="Vobiz login form filled in with piyush@vobiz.ai and masked password, with the orange Login button enabled" style={{maxWidth: '420px', margin: '0 auto', display: 'block'}} width="2168" height="2052" data-path="images/platform/auth/login-form_blur.png" />
</Frame>

<Steps>
  <Step title="Enter your Vobiz email">
    Type the email address linked to your Vobiz account (e.g. `name@yourcompany.com`). The field validates the format inline - fix any red‑bordered typos before continuing.

    <Note>
      Email is case‑insensitive. `Name@Vobiz.ai` and `name@vobiz.ai` resolve to the same Vobiz Console account.
    </Note>
  </Step>

  <Step title="Enter your password">
    Type your password into the masked field. Click the eye icon (👁) on the right to reveal what you typed - useful if you're not sure you typed the right characters or you're recovering from a paste.

    The **Login** button stays disabled (light orange) until both fields contain valid values. Once both are valid, it turns solid orange and is ready to submit.
  </Step>

  <Step title="Click Login">
    On success, Vobiz redirects you to the [Dashboard](/docs/platform/dashboard) for your account. On failure, the form shows an inline error message:

    | Error | What it means | Fix |
    | - | - | - |
    | *Invalid credentials* | Email or password is wrong. | Retype both. If you're sure the email is right, use [Forgot Password?](#forgot-your-password) |
    | *Account not verified* | You haven't clicked the verification link from signup. | Check your inbox (and spam) for the verification email from `no-reply@vobiz.ai`. |
    | *Too many attempts* | You hit the brute‑force rate limit. | Wait 15 minutes or reset your password via the link below. |
  </Step>
</Steps>

### Sign in with Google

If you registered with Google Workspace or want to skip managing a Vobiz‑specific password, use Google single sign‑on.

* Click **Continue with Google** below the password form to open the Google OAuth popup.
* Pick the Google account that matches your Vobiz email and approve the consent prompt.
* If a Vobiz account already exists for that email, you're signed straight in. If not, you're redirected to the [signup flow](#create-an-account) with the email pre‑filled.
* If your Vobiz account was originally created with email + password, Google SSO will **link to the same account** the first time you use it - same data, new sign‑in method.

<Tip>
  Google SSO is the fastest path if your team already lives in Google Workspace - no separate password to rotate, and Google's 2FA carries over.
</Tip>

### Forgot your password?

The **Forgot Password?** link sits on the right side of the *Password* label.

<Steps>
  <Step title="Enter your email">
    The password reset page asks for the Vobiz‑registered email address.
  </Step>

  <Step title="Check your inbox">
    Vobiz sends a one‑time password reset link to that address. The link expires after **30 minutes**.

    <Warning>
      If the email doesn't arrive within a minute, check your spam folder. The sender is `no-reply@vobiz.ai`. Add it to your safe senders to avoid the same problem next time.
    </Warning>
  </Step>

  <Step title="Set a new password">
    Click the link, type a new password twice, and submit. You're returned to the login screen - sign in with the new password.
  </Step>
</Steps>

## Create an account

```text Sign-up URL theme={null}
https://console.vobiz.ai/auth/signup
```

Creating a Vobiz account is a 3‑step flow: basic credentials, business details, and email verification. New accounts include **₹25 free credit** so you can place a real call without adding a payment method.

<Tip>
  Already have an account? Jump back up to the [Sign in](#sign-in) section.
</Tip>

### The signup screen at a glance

Every step shows the same left‑side panel - *"Scale your business communications globally"* - plus a 3‑step progress indicator at the top right (Account → Details → Verify) and a *"Already have an account? Log in"* link in the top‑right corner.

### Step 1 · Create Your Account

<Frame caption="Step 1 - Create Your Account">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/auth/signup-step1-account.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=a8921d1b511753b3387376e187faa28d" alt="Vobiz signup step 1 Create Your Account screen with Full name, Email address, Referral code (optional), Password, and Confirm Password fields, plus the 3-step progress indicator Account/Details/Verify across the top" style={{maxWidth: '760px', margin: '0 auto', display: 'block'}} width="2000" height="1151" data-path="images/platform/auth/signup-step1-account.png" />
</Frame>

| Field | Required | Notes |
| - | - | - |
| **Full name** | ✅ | The person who owns this account. Editable later under **Profile menu**. |
| **Email address** | ✅ | The address Vobiz sends the verification code to in Step 3. Becomes your sign‑in email. |
| **Referral code (optional)** | – | Got a promo code? Type it here to apply a one‑time credit on top of the default ₹25 starter. |
| **Password** | ✅ | Minimum 8 characters. Click the eye icon (👁) to reveal what you typed. |
| **Confirm Password** | ✅ | Must match the password above. |

Click **Next** (bottom‑right) to advance. The button stays disabled (light orange) until every required field is filled.

<Note>
  The email is case‑insensitive - `Name@Company.com` and `name@company.com` resolve to the same Vobiz account. Pick the casing that matches your inbox.
</Note>

### Step 2 · Additional Information

<Frame caption="Step 2 - Additional Information">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/auth/signup-step2-details.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=52ce2b327dccdb5585ad53ebd31d6486" alt="Vobiz signup step 2 Additional Information screen with Company name, Phone number with country code dropdown (+91 IN), Country dropdown (India), State/Province dropdown, City, ZIP/Postal code, Street Address, and About your account (optional) textarea" style={{maxWidth: '760px', margin: '0 auto', display: 'block'}} width="2000" height="1152" data-path="images/platform/auth/signup-step2-details.png" />
</Frame>

This is the business‑details step. Used for billing, regulatory compliance (especially Indian DLT rules), and invoicing.

| Field | Required | Notes |
| - | - | - |
| **Company name** | ✅ | The legal business entity (e.g. *XYZ Pvt. Ltd.*). Used on invoices. |
| **Phone number** | ✅ | Country dial code (`+91 IN` default) + local number. This is your contact number, not a Vobiz DID. |
| **Country** | ✅ | Drives the available State/Province list below. Defaults to India. |
| **State/Province** | ✅ | Drop‑down dependent on Country. |
| **City** | ✅ | Free‑text city name. |
| **ZIP/Postal code** | ✅ | Numeric postal code. India = 6 digits. |
| **Street Address** | ✅ | Full street address - used on invoices and KYC. |
| **About your account (optional)** | – | One‑liner about your use case. Helps Vobiz support tailor onboarding (e.g. *"AI voice agent for healthcare appointments"*). |

<Warning>
  These details are reused for **DLT registration** and **KYC** if you operate in India. Mismatched info between the signup form and KYC docs delays compliance approval - get them right the first time.
</Warning>

Click **Next** to advance to verification. Use **Back** if you need to fix anything in Step 1.

### Step 3 · Verify Your Email

<Frame caption="Step 3 - Verify Your Email">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/auth/signup-step3-verify.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=d68c97d199f6a134e1c961f784e3bdc0" alt="Vobiz signup step 3 Verify Your Email screen with envelope icon, message We've sent a 6-digit verification code to the email address from step 1, a six-digit code input field showing 000000 placeholder, Didn't receive code Resend link, Back button, and disabled Verify Email button at the bottom" style={{maxWidth: '760px', margin: '0 auto', display: 'block'}} width="2000" height="1157" data-path="images/platform/auth/signup-step3-verify.png" />
</Frame>

Vobiz emails a **6‑digit verification code** to the address you entered in Step 1. The screen shows the destination email below the message so you can confirm you didn't typo it.

<Steps>
  <Step title="Open your inbox">
    Look for an email from `no-reply@vobiz.ai` with the subject *"Your Vobiz verification code"*. Check spam if it's not in your inbox after \~30 seconds.
  </Step>

  <Step title="Type the 6-digit code">
    Enter the code in the input field. The **Verify Email** button enables once all 6 digits are filled.
  </Step>

  <Step title="Click Verify Email">
    On success, you're redirected to the [Dashboard](/docs/platform/dashboard) and your **₹25 free credit** is loaded automatically.
  </Step>
</Steps>

#### If the code doesn't arrive

Click **Didn't receive code? Resend** below the input.

* The link triggers a fresh email after a brief cooldown (typically 30–60 seconds).
* If three resends fail, the email address is likely blocking `vobiz.ai` - add `no-reply@vobiz.ai` to your safe senders or contact your IT admin.
* Wrong email entered in Step 1? Click **Back** twice to return to Step 1 and fix it.

<Note>
  The verification code expires after **30 minutes**. If yours has expired, click **Resend** for a new one - the old code is invalidated immediately.
</Note>

### What you get on day one

| Perk | Detail |
| - | - |
| **₹25 starter credit** | Enough for \~50 minutes of domestic India outbound or \~20 minutes of premium outbound. |
| **Test phone numbers** | Buy a DID from the [Phone Numbers](/docs/account-phone-number) section - purchase fee deducted from your starter credit. |
| **Full API access** | Auth ID and Auth Token live and ready in the [Dashboard](/docs/platform/dashboard) - no waiting for activation. |
| **Sandbox‑equivalent** | Vobiz doesn't have a separate sandbox - your live account *is* the sandbox until you're ready to scale. |

## What's next

<CardGroup cols={2}>
  <Card title="Dashboard tour" icon="gauge" href="/docs/platform/dashboard">
    Every tile, chart, and credential on the Vobiz Console home screen.
  </Card>

  <Card title="Make your first call" icon="rocket" href="/docs/quick-start">
    Buy a number, set up a SIP trunk or XML app, and place a real call in under 5 minutes.
  </Card>
</CardGroup>

## Troubleshooting

### Sign-in problems

* **Login button stays greyed out.** One of the fields is empty or invalid. Both email and password must have values; the email needs an `@`.
* **Google SSO popup is blocked.** Allow popups for `console.vobiz.ai` in your browser settings and click **Continue with Google** again.
* **Reset email never arrives.** Confirm the email matches the one on your Vobiz account. If you signed up with Google SSO there is *no* password - use **Continue with Google** instead of trying to reset.
* **Account is locked.** Five failed sign‑in attempts triggers a 15‑minute lockout. Use **Forgot Password?** during the lockout window or just wait it out.

### Signup problems

* **"Email already in use" on Step 1** → that email already has a Vobiz account. Use the [Sign in](#sign-in) section above, or click **Forgot Password?** to recover.
* **Verification email never arrives** → check spam, then add `no-reply@vobiz.ai` to safe senders. Still nothing? Email [support@vobiz.ai](mailto:support@vobiz.ai) from the same address you tried to sign up with.
* **Stuck on Step 2 with "State/Province" not loading** → reload the page and re‑enter Step 1. Some browser extensions block country‑state dropdown fetches.
* **₹25 credit not showing on Dashboard** → it lands within a minute of verification. If it's still missing after 5 minutes, ping support - they can apply it manually with your account email.

**Still stuck?** Email [support@vobiz.ai](mailto:support@vobiz.ai) with the email address you're trying to use - include a screenshot of the error if you can.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.