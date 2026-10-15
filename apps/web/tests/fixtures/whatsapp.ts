/**
 * WhatsApp through Meta (D-784). `WHATSAPP_OFF_ROUTES` is a deployment where Calevate's
 * Meta set-up is not finished and the client has no account: the Integrations screen shows
 * the provider-key guides. Screens that merely host the section spread it into their routes.
 */
import type { AdminWhatsApp, WhatsAppAccount, WhatsAppOverview, WhatsAppTemplate } from "@/lib/api/whatsapp";

const PRICING = "https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing";
const MANAGER = "https://business.facebook.com/wa/manage/home/";

export const WHATSAPP_OFF: WhatsAppOverview = {
  setup: {
    available: false,
    reason: "not_configured",
    coexistence: false,
    pricing_url: PRICING,
    payment_method_url: MANAGER,
  },
  accounts: [],
};

export const WHATSAPP_OFF_ROUTES = { "/v1/whatsapp": WHATSAPP_OFF };

export const WHATSAPP_READY: WhatsAppOverview = {
  ...WHATSAPP_OFF,
  setup: { ...WHATSAPP_OFF.setup, available: true, reason: null },
};

export const ACCOUNT: WhatsAppAccount = {
  id: "0192f0aa-5555-7000-8000-000000000001",
  status: "connected",
  onboarding: "new",
  display_phone_number: "+91 98765 43210",
  verified_name: "Lakshmi Traders",
  name_status: "APPROVED",
  quality_rating: "GREEN",
  messaging_limit: "TIER_250",
  registered: true,
  webhooks_subscribed: true,
  setup_error: null,
  templates_submitted: true,
  account_alert: null,
  last_send_error: null,
  last_event_at: "2026-10-15T05:00:00Z",
  connected_at: "2026-10-15T04:00:00Z",
};

export const WHATSAPP_CONNECTED: WhatsAppOverview = { ...WHATSAPP_READY, accounts: [ACCOUNT] };

export const TEMPLATES: WhatsAppTemplate[] = [
  {
    id: "0192f0aa-6666-7000-8000-000000000001",
    account_id: ACCOUNT.id,
    name: "calevate_payment_link",
    language: "te",
    category: "UTILITY",
    body: "నమస్కారం, మీరు {{1}} కోసం అడిగిన చెల్లింపు లింక్ ఇది. మొత్తం: ₹{{2}}. ఇక్కడ చెల్లించండి: {{3}} ధన్యవాదాలు.",
    variables: [
      { label: "What the payment is for", example: "your order" },
      { label: "Amount in rupees", example: "1500" },
      { label: "Payment link", example: "https://rzp.io/l/example" },
    ],
    origin: "calevate",
    purpose: "payment_link",
    status: "approved",
    rejection_code: null,
    category_changed_to: null,
    submitted_at: "2026-10-15T04:00:00Z",
    decided_at: "2026-10-15T06:00:00Z",
  },
  {
    id: "0192f0aa-6666-7000-8000-000000000002",
    account_id: ACCOUNT.id,
    name: "order_ready",
    language: "en",
    category: "UTILITY",
    body: "Your order is ready, {{1}}. Thank you.",
    variables: [{ label: "Customer's name", example: "Ravi" }],
    origin: "client",
    purpose: null,
    status: "rejected",
    rejection_code: "INVALID_FORMAT",
    category_changed_to: null,
    submitted_at: "2026-10-15T04:00:00Z",
    decided_at: "2026-10-15T06:00:00Z",
  },
];

export const ADMIN_WHATSAPP: AdminWhatsApp = {
  configured: true,
  app_secret_set: true,
  verify_token_set: true,
  coexistence: false,
  week_count: 3,
  weekly_limit: 10,
  last_event_at: "2026-10-15T05:00:00Z",
  callback_path: "/hooks/v1/meta/whatsapp",
  clients: [
    {
      tenant_id: "t1",
      name: "Lakshmi Traders",
      slug: "lakshmi",
      accounts: [
        {
          id: ACCOUNT.id,
          status: "connected",
          onboarding: "new",
          display_phone_number: "+91 98765 43210",
          verified_name: "Lakshmi Traders",
          name_status: "APPROVED",
          quality_rating: "GREEN",
          messaging_limit: "TIER_250",
          setup_error: null,
          account_alert: null,
          last_send_error: null,
          last_event_at: "2026-10-15T05:00:00Z",
          connected_at: "2026-10-15T04:00:00Z",
          templates_approved: 12,
          templates_pending: 0,
          templates_rejected: 0,
        },
      ],
    },
  ],
};
