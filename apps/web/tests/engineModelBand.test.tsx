import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { ModelBandControl } from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/sections/modelBand";
import type { EngineCatalogueModel } from "@/lib/api/engineCatalogue";
import {
  ENGINE_MODEL_BANDS_PATH,
  recordEngineModelBandConfirmation,
  type EngineModelBand,
} from "@/lib/api/engineModelBands";

import { renderAdminPage } from "./harness";

/**
 * Recording whether one of the voice platform's models costs extra, from the agent's model
 * list (D-750). A model nobody has checked carries a one-click "No extra charge" control;
 * "Costs extra" asks once more because it hides the model everywhere. The POST goes to the
 * RAW model id the band list carries for the row's opaque id, under the route's step-up.
 */

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-00000000ad03",
  role: "superadmin",
  permissions: ["ops:manage", "admin:tenants"],
};

const UNCHECKED: EngineCatalogueModel = {
  model_id: "m_0123456789abcdef",
  label: "Composer v0.1",
  call_capable: true,
  plan_allows: true,
  usable_with_studio_voice: false,
  price_band: null,
  latency_ms: null,
  offerable: false,
  reason: "Not checked yet.",
};

function bandRow(over: Partial<EngineModelBand> = {}): EngineModelBand {
  return {
    engine: "thinnest",
    model_id: "composer-v0.1",
    catalogue_id: UNCHECKED.model_id,
    label: "Composer v0.1",
    band: null,
    recorded_at: null,
    recorded_by: null,
    source_note: null,
    latency_ms: null,
    usable_with_studio_voice: false,
    ...over,
  };
}

const BANDS = {
  engine: "thinnest",
  available: true,
  complete: true,
  models: [bandRow()],
  as_of: "2026-10-11T06:00:00Z",
};

const POST_PATH = `POST ${ENGINE_MODEL_BANDS_PATH}/thinnest/composer-v0.1`;

describe("ModelBandControl", () => {
  it("records an unchecked model as included, in one click, against its raw id", async () => {
    const { calls } = renderAdminPage(<ModelBandControl model={UNCHECKED} />, {
      [ADMIN_ME_PATH]: ME,
      [ENGINE_MODEL_BANDS_PATH]: BANDS,
      [POST_PATH]: bandRow({ band: "none" }),
    });
    const button = await screen.findByRole("button", {
      name: "No extra charge (checked in the console)",
    });
    await waitFor(() =>
      expect((button as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(button);
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST")).toBe(true),
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(
      `${ENGINE_MODEL_BANDS_PATH}/thinnest/composer-v0.1`,
    );
    expect(JSON.parse(post?.body ?? "null")).toMatchObject({ band: "none" });
    expect(post?.headers["X-Confirm-Action"]).toBe(
      recordEngineModelBandConfirmation("thinnest", "composer-v0.1"),
    );
  });

  it("asks once more before recording a model as paid", async () => {
    const { calls } = renderAdminPage(<ModelBandControl model={UNCHECKED} />, {
      [ADMIN_ME_PATH]: ME,
      [ENGINE_MODEL_BANDS_PATH]: BANDS,
      [POST_PATH]: bandRow({ band: "premium" }),
    });
    const paid = await screen.findByRole("button", { name: "Costs extra" });
    await waitFor(() =>
      expect((paid as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(paid);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Record as paid" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST")).toBe(true),
    );
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(post?.body ?? "null")).toMatchObject({ band: "premium" });
  });

  it("shows nothing for a model already checked", () => {
    const { container } = renderAdminPage(
      <ModelBandControl
        model={{
          ...UNCHECKED,
          price_band: "none",
          offerable: true,
          reason: null,
        }}
      />,
      { [ADMIN_ME_PATH]: ME, [ENGINE_MODEL_BANDS_PATH]: BANDS },
    );
    expect(container.textContent).toBe("");
  });
});
