/**
 * Meta's Embedded Signup window, as Meta documents it for v4 (D-784).
 *
 * Read on Meta's page `embedded-signup/implementation.md` on 15 Oct 2026: the SDK is loaded
 * from `https://connect.facebook.net/en_US/sdk.js`, `FB.init({appId, autoLogAppEvents,
 * xfbml, version})`, then `FB.login(cb, {config_id, response_type: "code",
 * override_default_response_type: true, extras})`. The login callback carries the code
 * (`authResponse.code`); the account ids arrive separately as a `message` event whose data is
 * JSON with `type: "WA_EMBEDDED_SIGNUP"` and `event` FINISH, FINISH_ONLY_WABA,
 * FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING, FINISH_GRANT_ONLY_API_ACCESS, CANCEL or ERROR.
 *
 * Meta's sample accepts any origin that `endsWith("facebook.com")`, which also admits a
 * page on `evilfacebook.com`; we accept `facebook.com` and its subdomains only.
 *
 * The SDK is loaded only when the owner presses Connect, exactly like `googlePicker.ts`, and
 * `lib/security/csp.ts` admits it by path.
 */

export const FACEBOOK_SDK_SRC = "https://connect.facebook.net/en_US/sdk.js";
/** How long to wait for Meta's account ids after the code arrives. The code lives 30 s. */
const SESSION_INFO_WAIT_MS = 8000;

export type SignupFinish = {
  code: string;
  event: string;
  waba_id: string;
  phone_number_id: string | null;
  business_id: string | null;
};

export type SignupOutcome =
  | { kind: "finished"; result: SignupFinish }
  | { kind: "cancelled"; step: string | null }
  | { kind: "failed"; message: string };

type LoginResponse = { authResponse?: { code?: string } | null };

type FacebookSdk = {
  init(options: { appId: string; autoLogAppEvents: boolean; xfbml: boolean; version: string }): void;
  login(callback: (response: LoginResponse) => void, options: Record<string, unknown>): void;
};

declare global {
  interface Window {
    FB?: FacebookSdk;
    fbAsyncInit?: () => void;
  }
}

/** Is this message from Meta? `facebook.com` or a subdomain of it, over HTTPS. */
export function isMetaOrigin(origin: string): boolean {
  try {
    const url = new URL(origin);
    return (
      url.protocol === "https:" &&
      (url.hostname === "facebook.com" || url.hostname.endsWith(".facebook.com"))
    );
  } catch {
    return false;
  }
}

type SessionEvent = {
  event: string;
  waba_id?: string;
  phone_number_id?: string;
  business_id?: string;
  current_step?: string;
  error_message?: string;
};

/** Meta's session-logging message, or null when the message is not one. */
export function readSessionMessage(origin: string, raw: unknown): SessionEvent | null {
  if (!isMetaOrigin(origin)) return null;
  let data: unknown = raw;
  if (typeof raw === "string") {
    try {
      data = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!data || typeof data !== "object") return null;
  const message = data as { type?: unknown; event?: unknown; data?: unknown };
  if (message.type !== "WA_EMBEDDED_SIGNUP" || typeof message.event !== "string") return null;
  const body = (message.data && typeof message.data === "object" ? message.data : {}) as Record<string, unknown>;
  const text = (key: string) => (typeof body[key] === "string" ? (body[key] as string) : undefined);
  return {
    event: message.event,
    waba_id: text("waba_id"),
    phone_number_id: text("phone_number_id"),
    business_id: text("business_id"),
    current_step: text("current_step"),
    error_message: text("error_message"),
  };
}

let loading: Promise<FacebookSdk> | null = null;

/** Load and initialise Meta's SDK ahead of the click that opens its window. */
export function prepareEmbeddedSignup(appId: string, version: string): Promise<unknown> {
  return loadSdk(appId, version);
}

function loadSdk(appId: string, version: string): Promise<FacebookSdk> {
  if (window.FB) return Promise.resolve(window.FB);
  if (loading) return loading;
  loading = new Promise<FacebookSdk>((resolve, reject) => {
    window.fbAsyncInit = () => {
      if (!window.FB) {
        loading = null;
        reject(new Error("Meta's sign-in window could not be loaded."));
        return;
      }
      window.FB.init({ appId, autoLogAppEvents: true, xfbml: true, version });
      resolve(window.FB);
    };
    const script = document.createElement("script");
    script.src = FACEBOOK_SDK_SRC;
    script.async = true;
    script.defer = true;
    script.crossOrigin = "anonymous";
    script.onerror = () => {
      loading = null;
      reject(new Error("Meta's sign-in window could not be loaded. Check your connection and try again."));
    };
    document.head.appendChild(script);
  });
  return loading;
}

/**
 * Open Meta's window and wait for the owner to finish or close it. Resolves; never rejects
 * for an ordinary cancel, so the screen can say what happened in plain words.
 */
export async function runEmbeddedSignup(options: {
  appId: string;
  configId: string;
  graphVersion: string;
  extras: Record<string, unknown>;
}): Promise<SignupOutcome> {
  // The SDK should already be loaded (`prepareEmbeddedSignup`), so `FB.login` runs in the
  // same task as the owner's click: a browser blocks a pop-up opened later than that.
  let sdk: FacebookSdk;
  if (window.FB) {
    sdk = window.FB;
  } else {
    try {
      sdk = await loadSdk(options.appId, options.graphVersion);
    } catch (error) {
      return { kind: "failed", message: error instanceof Error ? error.message : String(error) };
    }
  }
  return new Promise<SignupOutcome>((resolve) => {
    let session: SessionEvent | null = null;
    let code: string | null = null;
    let settled = false;
    let waitTimer: ReturnType<typeof setTimeout> | null = null;

    const finish = (outcome: SignupOutcome) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMessage);
      if (waitTimer) clearTimeout(waitTimer);
      resolve(outcome);
    };

    const tryFinish = () => {
      if (!code || !session) return;
      if (session.event === "CANCEL") {
        finish({ kind: "cancelled", step: session.current_step ?? null });
        return;
      }
      if (session.event === "ERROR" || !session.waba_id) {
        finish({ kind: "failed", message: session.error_message ?? "Meta reported an error." });
        return;
      }
      finish({
        kind: "finished",
        result: {
          code,
          event: session.event,
          waba_id: session.waba_id,
          phone_number_id: session.phone_number_id ?? null,
          business_id: session.business_id ?? null,
        },
      });
    };

    function onMessage(event: MessageEvent) {
      const parsed = readSessionMessage(event.origin, event.data);
      if (!parsed) return;
      session = parsed;
      if (parsed.event === "CANCEL" && !code) {
        finish({ kind: "cancelled", step: parsed.current_step ?? null });
        return;
      }
      tryFinish();
    }

    window.addEventListener("message", onMessage);
    sdk.login(
      (response) => {
        code = response.authResponse?.code ?? null;
        if (!code) {
          finish({ kind: "cancelled", step: session?.current_step ?? null });
          return;
        }
        tryFinish();
        if (!settled) {
          waitTimer = setTimeout(
            () => finish({ kind: "failed", message: "Meta did not say which account was connected." }),
            SESSION_INFO_WAIT_MS,
          );
        }
      },
      {
        config_id: options.configId,
        response_type: "code",
        override_default_response_type: true,
        extras: options.extras,
      },
    );
  });
}
