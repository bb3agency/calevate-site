import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import VoicesPage from "@/app/admin/ops/voices/page";
import {
  CLONE_FIRST,
  OPS_VOICES_PATH,
  OPS_VOICES_REFRESH_PATH,
  type AddVoiceForm,
  type CuratedVoice,
  type CuratedVoices,
} from "@/lib/api/opsVoices";

import { problem, renderAdminPage, stillLoading, type Routes } from "./harness";

/**
 * THE VOICES PAGE — the console half of D-590.
 *
 * ⚠ **THIS FILE USED TO ASSERT THAT THE SCREEN HAS NO ADD BUTTON** ("says where a NEW voice
 * comes from, because it cannot add one"). D-588 reasoned from a true premise — the voice
 * platform's API is read-only — to a false conclusion: nothing here can clone a voice ON
 * THAT PLATFORM, but adding one to THIS product's catalogue needs only the operator's facts
 * and one read to check them. The founder's reply to the curation screen was *"these are too
 * much … I should be able to add voices"*. So the claims this screen must get right have
 * changed, and they are ranked here by what each failure costs:
 *
 * 1. **The Add form is the primary action, and it sends exactly the five facts the wire
 *    needs.** A screen that dropped one silently would produce a voice that saves and fails
 *    on a client's call — the failure this whole slice exists to move onto this screen.
 * 2. **ElevenLabs is VISIBLE and REFUSED with its reason.** The voice platform clones on
 *    ElevenLabs or Cartesia and this product has no ElevenLabs model. An operator who has
 *    just spent a voice sample there and finds the option missing concludes the console is
 *    broken; one who finds it disabled with a sentence re-clones on Cartesia.
 * 3. **A refusal is the SERVER's sentence, printed verbatim.** Every check that matters
 *    happens against the platform's own list, so the browser must not paraphrase a verdict
 *    it did not reach.
 * 4. **The screen does not open with the vendor's whole catalogue.** That was the founder's
 *    actual complaint; the full list is one control away and says it is a reference.
 * 5. **Archiving a voice with live agents on it must be offered, with the count.** The write
 *    cannot break a call, and refusing would make a vendor's own withdrawal unfileable.
 * 6. **A withdrawn voice must be visibly different from a disabled one.**
 * 7. **§52.** Loading is a skeleton, a failed read is a refusal, and neither is "no voices".
 * 8. **A refused session is told so and is not shown an outage.**
 */

const SUPERADMIN: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000f1",
  realm: "admin",
  role: "superadmin",
  permissions: ["ops:manage", "admin:tenants"],
};

/** An admin who may run the console but may not decide what the platform offers. */
const OPERATOR: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000f2",
  realm: "admin",
  role: "operator",
  permissions: ["admin:tenants", "org:read"],
};

/** The GET the page actually makes — the scope travels in the query string. */
const LIST_PATH = `${OPS_VOICES_PATH}?scope=decided`;
const ALL_PATH = `${OPS_VOICES_PATH}?scope=all`;

function voice(over: Partial<CuratedVoice> = {}): CuratedVoice {
  return {
    voice_id: "bulbul:v3:ashutosh",
    label: "Ashutosh",
    provider: "sarvam",
    tier_label: "Clear",
    tts_model: "bulbul:v3",
    engine_voice_id: "ashutosh",
    languages: ["te-IN", "hi-IN", "en-IN"],
    source: "platform",
    state: "enabled",
    origin: "operator",
    offered: true,
    synced_at: "2026-09-11T04:30:00Z",
    curated_at: "2026-09-11T05:00:00Z",
    withdrawn_at: null,
    live_agents: 0,
    ...over,
  };
}

/**
 * The form's options, AS THE SERVER SENDS THEM — including the provider it sends only so the
 * screen can refuse it. Composed on the server for one reason and asserted here for the
 * same one: which providers exist is a fact with a single source, and a browser-side copy
 * is the copy that goes stale.
 */
function form(over: Partial<AddVoiceForm> = {}): AddVoiceForm {
  return {
    providers: [
      {
        provider: "sarvam",
        tier_label: "Clear",
        models: ["bulbul:v3"],
        selectable: true,
        unavailable_reason: null,
      },
      {
        provider: "cartesia",
        tier_label: "Studio",
        models: ["sonic-3.5"],
        selectable: true,
        unavailable_reason: null,
      },
      {
        provider: "elevenlabs",
        tier_label: null,
        models: [],
        selectable: false,
        unavailable_reason:
          "elevenlabs is one of the two providers the voice platform will clone a voice " +
          "on, but it is not a provider this product runs: there is no ElevenLabs TTS " +
          "model in our catalogue, so a minute spoken on it has no voice tier and no " +
          "price. Clone the voice again on Cartesia.",
      },
    ],
    languages: ["te-IN", "hi-IN", "en-IN"],
    voice_lab_url: "https://platform.bolna.ai/voices",
    ...over,
  };
}

/**
 * `note`, `offered` and `cached` are the SERVER's, and the fixtures below say things the
 * rows do not, on purpose: a bundle that composed any of them from the rows would pass
 * against a consistent fixture and be wrong in production.
 */
function catalogue(over: Partial<CuratedVoices> = {}): CuratedVoices {
  return {
    voices: [voice()],
    source: "engine",
    offered: 1,
    scope: "decided",
    cached: 418,
    note: "These are the voices this platform has added.",
    form: form(),
    ...over,
  };
}

function routes(over: Routes = {}): Routes {
  return {
    [ADMIN_ME_PATH]: SUPERADMIN,
    [LIST_PATH]: catalogue(),
    ...over,
  };
}

async function rowFor(label: string): Promise<HTMLElement> {
  const table = await screen.findByRole("table");
  const row = within(table)
    .getAllByRole("row")
    .find((candidate) => (candidate.textContent ?? "").includes(label));
  expect(row).toBeDefined();
  return row as HTMLElement;
}

describe("the voices page", () => {
  it("sends the five facts the wire needs when a voice is added", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        "POST /v1/ops/voices": {
          voice: voice({ voice_id: "sonic-3.5:abc123", label: "my-custom-voice" }),
          offered: 2,
          offerable: true,
          unofferable_reason: null,
          next_step: "my-custom-voice was added, verified against the voice platform.",
        },
      }),
    );
    await screen.findByRole("table");

    fireEvent.click(screen.getByRole("radio", { name: /cartesia/i }));
    fireEvent.change(screen.getByLabelText(/Voice ID/i), { target: { value: " abc123 " } });
    fireEvent.change(screen.getByLabelText(/Name, exactly/i), {
      target: { value: " my-custom-voice " },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add this voice/i }));

    await waitFor(() => {
      const post = calls.find((call) => call.method === "POST" && call.path === OPS_VOICES_PATH);
      expect(post).toBeDefined();
      // The MODEL follows the provider without the operator choosing it, and the surrounding
      // whitespace is trimmed — an id pasted out of another product's UI usually carries it,
      // and a voice id is compared byte for byte on the server.
      expect(JSON.parse(String(post?.body))).toEqual({
        provider: "cartesia",
        tts_model: "sonic-3.5",
        engine_voice_id: "abc123",
        label: "my-custom-voice",
        languages: ["te-IN"],
      });
    });

    // The server's own sentence, printed verbatim — including, when it says so, the reason
    // nobody can be put on the voice yet.
    await waitFor(() => {
      expect(
        screen.getByText(/was added, verified against the voice platform/i),
      ).toBeTruthy();
    });
  });

  it("offers ElevenLabs and refuses it with the reason, rather than omitting it", async () => {
    const { container } = renderAdminPage(<VoicesPage />, routes());
    await screen.findByRole("table");

    // PRESENT — an operator who cloned there must find it rather than conclude the console
    // is broken and try again.
    const option = screen.getByRole("radio", { name: /elevenlabs/i }) as HTMLInputElement;
    expect(option.disabled).toBe(true);
    // AND THE REASON, from the server, beside it. A greyed line with no sentence teaches
    // nothing and costs another voice sample.
    expect(container.textContent).toMatch(/no ElevenLabs TTS model in our catalogue/i);
    expect(container.textContent).toMatch(/Clone the voice again on Cartesia/i);
  });

  it("prints the server's refusal verbatim when a voice id is not on the platform", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        "POST /v1/ops/voices": problem(422, {
          title: "That voice is not on the voice platform",
          detail:
            "The voice platform does not list 'typo-id' for sonic-3.5 on our account, so " +
            "an agent published on it would be refused at create time.",
        }),
      }),
    );
    await screen.findByRole("table");

    fireEvent.change(screen.getByLabelText(/Voice ID/i), { target: { value: "typo-id" } });
    fireEvent.change(screen.getByLabelText(/Name, exactly/i), { target: { value: "Whatever" } });
    fireEvent.click(screen.getByRole("button", { name: /Add this voice/i }));

    // VERBATIM. The browser reached no verdict of its own and must not paraphrase one.
    expect(
      await screen.findByText(/does not list 'typo-id' for sonic-3\.5 on our account/i),
    ).toBeTruthy();
  });

  it("opens on the added voices, not on the vendor's whole catalogue", async () => {
    const { container } = renderAdminPage(<VoicesPage />, routes());
    await screen.findByRole("table");

    // THE FOUNDER'S ACTUAL COMPLAINT: one added voice on screen, 418 on the platform, and
    // no suggestion that the other 417 are a to-do list.
    expect(container.textContent).toContain(CLONE_FIRST);
    expect(within(await screen.findByRole("table")).getAllByRole("row")).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: /Show every voice the platform lists \(418\)/i }),
    ).toBeTruthy();
    expect(container.textContent).toMatch(/Nothing needs to be done with them/i);
  });

  it("fetches the full list only when the operator asks for it", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({ [ALL_PATH]: catalogue({ scope: "all", voices: [voice(), voice({
        voice_id: "bulbul:v3:stock",
        label: "Stock One",
        origin: "synced",
        state: "disabled",
        offered: false,
      })] }) }),
    );
    await screen.findByRole("table");
    expect(calls.some((call) => call.path === ALL_PATH)).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /Show every voice/i }));

    await waitFor(() => expect(calls.some((call) => call.path === ALL_PATH)).toBe(true));
    const stock = await rowFor("Stock One");
    expect(stock.textContent).toMatch(/Read off the voice platform's own list/i);
  });

  it("renders every voice with its state, its provenance and the tier a client is told", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [LIST_PATH]: catalogue({
          voices: [
            voice(),
            voice({
              voice_id: "sonic-3.5:x1",
              label: "Cloned Anita",
              source: "custom",
              provider: "cartesia",
              tier_label: "Studio",
              tts_model: "sonic-3.5",
              state: "disabled",
              offered: false,
              curated_at: null,
            }),
          ],
          offered: 1,
        }),
      }),
    );

    const stock = await rowFor("Ashutosh");
    expect(stock.textContent).toContain("Clear");
    expect(stock.textContent).toContain("enabled");
    expect(stock.textContent).toMatch(/Added here, and checked against the voice platform/i);

    const clone = await rowFor("Cloned Anita");
    // THE ONE ENTRY CLASS NO COMPILED LIST COULD EVER HAVE HELD.
    expect(clone.textContent).toMatch(/cloned or imported/i);
    expect(clone.textContent).toContain("Studio");
    // The VENDOR is named on this console and nowhere a client can read it.
    expect(clone.textContent).toContain("cartesia");
  });

  it("distinguishes a voice WE disabled from one the PLATFORM dropped", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [LIST_PATH]: catalogue({
          voices: [
            voice({ state: "disabled", offered: false }),
            voice({
              voice_id: "bulbul:v3:gone",
              label: "Withdrawn One",
              state: "enabled",
              offered: false,
              withdrawn_at: "2026-09-10T09:00:00Z",
            }),
          ],
          offered: 0,
          note: "Voices have been added, but none can currently be offered.",
        }),
      }),
    );

    const withdrawn = await rowFor("Withdrawn One");
    // The vendor's statement, said as one: nothing on this console restores it, so an
    // operator must not read it as another toggle they have forgotten to flip.
    expect(withdrawn.textContent).toMatch(/no longer lists this voice/i);
    const ours = await rowFor("Ashutosh");
    expect(ours.textContent).not.toMatch(/no longer lists this voice/i);
    expect(ours.textContent).toMatch(/Not offered/i);
  });

  it("tells an operator how many live agents are on a voice before they archive it", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({ [LIST_PATH]: catalogue({ voices: [voice({ live_agents: 4 })] }) }),
    );

    const row = await rowFor("Ashutosh");
    expect(row.textContent).toContain("4");
    // The reassurance travels WITH the number, because the number alone reads as a warning
    // that the click will break something — and it will not.
    expect(row.textContent).toMatch(/keep speaking it/i);
    // ARCHIVING IS OFFERED, NOT REFUSED.
    expect(
      (within(row).getByRole("button", { name: /Archive Ashutosh/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("sends one PATCH naming the voice and the destination state", async () => {
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        "PATCH /v1/ops/voices": {
          voice: voice({ state: "disabled", offered: false }),
          offered: 0,
          next_step: "This voice can no longer be chosen for an agent.",
        },
      }),
    );
    const row = await rowFor("Ashutosh");

    fireEvent.click(within(row).getByRole("button", { name: /Disable Ashutosh/i }));

    await waitFor(() => {
      const patch = calls.find((call) => call.method === "PATCH");
      expect(patch?.path).toBe(OPS_VOICES_PATH);
      expect(JSON.parse(String(patch?.body))).toEqual({
        voice_id: "bulbul:v3:ashutosh",
        state: "disabled",
      });
    });
  });

  it("does not offer the state a voice is already in", async () => {
    renderAdminPage(<VoicesPage />, routes());
    const row = await rowFor("Ashutosh");

    const enable = within(row).getByRole("button", {
      name: /Enable Ashutosh/i,
    }) as HTMLButtonElement;
    const disable = within(row).getByRole("button", {
      name: /Disable Ashutosh/i,
    }) as HTMLButtonElement;
    expect(enable.disabled).toBe(true);
    expect(disable.disabled).toBe(false);
  });

  it("refreshes through the voice platform and prints the server's own sentence", async () => {
    const { calls, container } = renderAdminPage(
      <VoicesPage />,
      routes({
        [OPS_VOICES_REFRESH_PATH]: {
          seen: 12,
          written: 9,
          pruned: 1,
          complete: true,
          in_force: 9,
          note: "9 voice(s) cached and 1 withdrawn by the voice platform.",
        },
      }),
    );
    await screen.findByRole("table");

    fireEvent.click(screen.getByRole("button", { name: /Refresh from the platform/i }));

    await waitFor(() => {
      expect(calls.some((call) => call.path === OPS_VOICES_REFRESH_PATH)).toBe(true);
    });
    // VERBATIM. A partial or refused sync is a fact the operator has to see.
    await waitFor(() => {
      expect(container.textContent).toContain(
        "9 voice(s) cached and 1 withdrawn by the voice platform.",
      );
    });
  });

  it("renders a platform with nothing added as an empty state, not as a failure", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [LIST_PATH]: catalogue({
          voices: [],
          offered: 0,
          cached: 0,
          note: "No voice has been added yet, so no client and no admin can choose a voice.",
        }),
      }),
    );

    // Two places say it, and both are correct: the server's `note` above the table (why
    // nothing can be chosen) and the empty state inside it (what to do). `findAllByText`
    // rather than a narrower matcher, because which of the two a reader sees first is a
    // layout question this assertion has no business pinning.
    expect((await screen.findAllByText(/No voice has been added yet/i)).length).toBeGreaterThan(0);
    // The ADD FORM is still there — the empty state's fix is the control above it, not a
    // Refresh against a vendor that has nothing to do with this.
    expect(screen.getByRole("button", { name: /Add this voice/i })).toBeTruthy();
    // §52: an empty catalogue is a state, and it must not be painted as a transport fault.
    expect(screen.queryByRole("button", { name: /Try again/i })).toBeNull();
  });

  it("shows a skeleton while the read is in flight, never an empty catalogue", async () => {
    renderAdminPage(<VoicesPage />, routes({ [LIST_PATH]: stillLoading() }));

    expect(await screen.findByText(/Loading the voices this platform offers/i)).toBeTruthy();
    expect(screen.queryByText(/No voice has been added yet/i)).toBeNull();
    // The form needs the server's options, so it waits with the table rather than rendering
    // a provider picker of nothing.
    expect(screen.queryByRole("button", { name: /Add this voice/i })).toBeNull();
  });

  it("renders a failed read as a refusal, never as 'no voices'", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({ [LIST_PATH]: problem(503, { title: "Upstream unavailable" }) }),
    );

    expect(await screen.findByText(/Upstream unavailable/i)).toBeTruthy();
    // The claim this screen must never make off a failed read: that the platform has no
    // voices.
    expect(screen.queryByText(/No voice has been added yet/i)).toBeNull();
  });

  it("tells an admin without ops:manage why, instead of showing them an outage", async () => {
    renderAdminPage(<VoicesPage />, { ...routes(), [ADMIN_ME_PATH]: OPERATOR });

    expect(
      await screen.findByText(/add and manage the voices this platform offers/i),
    ).toBeTruthy();
    // The refusal INSTEAD of the screen, and no retry button.
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: /Add this voice/i })).toBeNull();
  });
});
