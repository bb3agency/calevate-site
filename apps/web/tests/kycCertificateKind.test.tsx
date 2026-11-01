import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import VerifyBusinessPage from "@/app/c/[slug]/verify-business/page";
import type { Me } from "@/lib/api/client";
import { PE_REGISTRATION_PATH } from "@/lib/api/dltRegistration";
import { KYC_PATH, type KycRecord } from "@/lib/api/kyc";
import { OWN_NUMBERS_PATHS } from "@/lib/api/ownNumbers";
import { PLEDGE_PATH } from "@/lib/api/verifyBusiness";

import { DLT_NOT_RECORDED, KYC_NOT_STARTED } from "./fixtures/sharedReads";
import { renderClientPage } from "./harness";

/**
 * The certificate kind sent with a business document follows the GST answer ON SCREEN.
 *
 * Step 1's answer can change while the document step stays mounted. The kind used to be
 * state seeded once from the first answer, so a business that said "GST registered", then
 * "not registered", uploaded its Incorporation certificate filed as `gst` — the select
 * showing one kind and the request carrying another.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["org:read", "org:manage"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const GST_YES: KycRecord = {
  ...KYC_NOT_STARTED,
  entity_type: "private_limited",
  legal_business_name: "Acme Traders Pvt Ltd",
  gst_registered: true,
  gstin: "36AABCT1234C1Z5",
};

const sent: FormData[] = [];

/** The multipart seam `apiUpload` uses, answering once the request is recorded. */
class StubXhr {
  status = 0;
  responseText = "";
  withCredentials = false;
  readonly upload = new EventTarget();
  private readonly events = new EventTarget();
  open(): void {}
  setRequestHeader(): void {}
  getResponseHeader(): string | null {
    return "application/json";
  }
  addEventListener(type: string, listener: EventListener): void {
    this.events.addEventListener(type, listener);
  }
  abort(): void {}
  send(form: FormData): void {
    sent.push(form);
    queueMicrotask(() => {
      this.status = 201;
      this.responseText = "{}";
      this.events.dispatchEvent(new Event("load"));
    });
  }
}

beforeEach(() => {
  sent.length = 0;
  vi.stubGlobal("XMLHttpRequest", StubXhr);
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe("the business certificate's kind", () => {
  it("is one of the kinds offered for the current GST answer, not the first answer's", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
    });
    await renderClientPage(
      <VerifyBusinessPage />,
      {
        "/v1/me": OWNER,
        [KYC_PATH]: GST_YES,
        [PLEDGE_PATH]: {
          version: 2,
          pledge_text: "We do not cold-call.",
          text_sha256: "0".repeat(64),
          is_current: false,
          accepted_version: null,
          accepted_at: null,
        },
        [OWN_NUMBERS_PATHS.status]: { available: false },
        [PE_REGISTRATION_PATH]: DLT_NOT_RECORDED,
      },
      "acme",
      client,
    );
    await screen.findByText("Upload the GST registration certificate.");

    // Step 1 is answered again: not GST registered.
    act(() => {
      client.setQueryData(["kyc", "acme"], { ...GST_YES, gst_registered: false, gstin: null });
    });
    const select = (await screen.findByLabelText("Which certificate")) as HTMLSelectElement;
    expect(select.value).toBe("incorporation");

    const picker = screen.getByLabelText(/Choose the certificate/) as HTMLInputElement;
    await waitFor(() => expect(picker.disabled).toBe(false));
    const file = new File(["%PDF-1.4"], "incorporation.pdf", { type: "application/pdf" });
    fireEvent.change(picker, { target: { files: [file] } });

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].get("slot")).toBe("business");
    expect(sent[0].get("kind")).toBe("incorporation");
  });
});
