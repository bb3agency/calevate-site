import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import VoicesPage from "@/app/admin/ops/voices/page";
import {
  ADD_A_VOICE,
  OPS_VOICES_PATH,
  OPS_VOICES_REFRESH_PATH,
  type CuratedVoice,
  type CuratedVoices,
} from "@/lib/api/opsVoices";

import { problem, renderAdminPage, stillLoading, type Routes } from "./harness";

/**
 * THE VOICES PAGE — the console half of D-588.
 *
 * The founder asked for a place to "add, delete and archive voices end to end" where only
 * the voices added there are selectable. The ADD half is not buildable: the voice
 * platform's API is READ-ONLY (two GET routes, no create/update/delete anywhere in it), so
 * a voice is imported or cloned in their Playground. What this screen must get right is
 * therefore not layout — it is the set of claims it is allowed to make, ranked by what each
 * failure costs:
 *
 * 1. **It must say where a new voice actually comes from.** An operator who reads this
 *    screen as "the place voices are added", finds no Add button and concludes the feature
 *    is broken is the most likely failure of the whole slice, and it costs a support
 *    conversation every time.
 * 2. **"Nothing is enabled" must not render as "no voices".** They are different states
 *    with different fixes — one is a Refresh, the other is a click — and the server sends
 *    the sentence that says which. A screen that paraphrased either is how a working
 *    platform gets reported as an outage.
 * 3. **Archiving a voice with live agents on it must be offered, with the count.** The
 *    write cannot break a call, and refusing would make a vendor's own withdrawal
 *    unfileable. What the screen owes the operator is the number, BEFORE the click.
 * 4. **A withdrawn voice must be visibly different from a disabled one.** One is our
 *    decision and one is the vendor's; only the first is fixable here.
 * 5. **§52.** Loading is a skeleton, a failed read is a refusal, and neither is an empty
 *    catalogue — which on this screen is a real and meaningful state.
 * 6. **A refused session is told so and is not shown an outage.**
 */

const SUPERADMIN: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000f1",
  realm: "admin",
  role: "superadmin",
  permissions: ["ops:manage", "admin:tenants"],
};

/** An admin who may run the console but may not curate what the platform offers. */
const OPERATOR: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000f2",
  realm: "admin",
  role: "operator",
  permissions: ["admin:tenants", "org:read"],
};

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
    offered: true,
    synced_at: "2026-09-11T04:30:00Z",
    curated_at: "2026-09-11T05:00:00Z",
    withdrawn_at: null,
    live_agents: 0,
    ...over,
  };
}

/**
 * `note` and `offered` are the SERVER's, and the fixtures below say something the rows do
 * not, on purpose: a bundle that composed either from the rows would pass against a
 * consistent fixture and be wrong in production, where the server counts withdrawal too.
 */
function catalogue(over: Partial<CuratedVoices> = {}): CuratedVoices {
  return {
    voices: [voice()],
    source: "engine",
    offered: 1,
    note: "These are every voice the voice platform lists for our account.",
    ...over,
  };
}

function routes(over: Routes = {}): Routes {
  return {
    [ADMIN_ME_PATH]: SUPERADMIN,
    [OPS_VOICES_PATH]: catalogue(),
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
  it("says where a NEW voice comes from, because it cannot add one", async () => {
    const { container } = renderAdminPage(<VoicesPage />, routes());
    await screen.findByRole("table");

    // The sentence itself, verbatim from the one place it is written.
    expect(container.textContent).toContain(ADD_A_VOICE);
    // And it names both routes the voice platform documents, because an operator who has
    // a voice id and an operator who has a recording need different halves of it.
    expect(ADD_A_VOICE).toMatch(/import/i);
    expect(ADD_A_VOICE).toMatch(/clone/i);
    // NO ADD CONTROL. A button that opened a form we cannot submit is worse than none.
    expect(screen.queryByRole("button", { name: /add voice/i })).toBeNull();
  });

  it("renders every voice with its state, its origin and the tier a client is told", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [OPS_VOICES_PATH]: catalogue({
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
    expect(stock.textContent).toContain("Stock voice");
    expect(stock.textContent).toContain("enabled");

    const clone = await rowFor("Cloned Anita");
    // THE ONE ENTRY CLASS NO COMPILED LIST COULD EVER HAVE HELD, and the operator has to be
    // able to tell their own clone from a stock persona at a glance.
    expect(clone.textContent).toContain("Imported or cloned by us");
    expect(clone.textContent).toContain("Studio");
    // The VENDOR is named on this console and nowhere a client can read it.
    expect(clone.textContent).toContain("cartesia");
    // "Never reviewed" is not the same fact as "disabled", and the column cannot say both.
    expect(clone.textContent).toContain("Never reviewed");
  });

  it("distinguishes a voice WE disabled from one the PLATFORM dropped", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [OPS_VOICES_PATH]: catalogue({
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
          note: "The catalogue has been read, but no voice is enabled.",
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
      routes({
        [OPS_VOICES_PATH]: catalogue({ voices: [voice({ live_agents: 4 })] }),
      }),
    );

    const row = await rowFor("Ashutosh");
    expect(row.textContent).toContain("4");
    // The reassurance travels WITH the number, because the number alone reads as a warning
    // that the click will break something — and it will not.
    expect(row.textContent).toMatch(/keep speaking it/i);
    // ARCHIVING IS OFFERED, NOT REFUSED. Refusing while any agent holds the voice would
    // make a vendor's own withdrawal unfileable.
    expect(
      (
        within(row).getByRole("button", {
          name: /Archive Ashutosh/i,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  it("sends one PATCH naming the voice and the destination state", async () => {
    // The stub table is keyed by PATH, so the list read and the write share an entry: the
    // route answers from the request it was given, which is also the only shape in which a
    // PATCH can return `SetCurationOut` while the GET returns the table.
    const { calls } = renderAdminPage(
      <VoicesPage />,
      routes({
        [OPS_VOICES_PATH]: (call: { method: string }) =>
          call.method === "PATCH"
            ? {
                voice: voice({ state: "disabled", offered: false }),
                offered: 0,
                next_step: "This voice can no longer be chosen for an agent.",
              }
            : catalogue(),
      }),
    );
    const row = await rowFor("Ashutosh");

    fireEvent.click(
      within(row).getByRole("button", { name: /Disable Ashutosh/i }),
    );

    await waitFor(() => {
      const patch = calls.find((call) => call.method === "PATCH");
      expect(patch?.path).toBe(OPS_VOICES_PATH);
      // The harness records the raw body, so it is parsed here rather than compared as an
      // object — the assertion is about the two fields the server reads, not about key
      // order or whitespace.
      expect(JSON.parse(String(patch?.body))).toEqual({
        voice_id: "bulbul:v3:ashutosh",
        state: "disabled",
      });
    });
  });

  it("does not offer the state a voice is already in", async () => {
    renderAdminPage(<VoicesPage />, routes());
    const row = await rowFor("Ashutosh");

    // Disabled rather than hidden: three controls that appear and disappear as you click
    // them is a row that moves under the pointer, and the fixed set is also how the current
    // state is legible a second way.
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

    fireEvent.click(screen.getByRole("button", { name: /Refresh/i }));

    await waitFor(() => {
      expect(calls.some((call) => call.path === OPS_VOICES_REFRESH_PATH)).toBe(
        true,
      );
    });
    // VERBATIM. A partial or refused sync is a fact the operator has to see, and a screen
    // that paraphrased it is how "the catalogue is up to date" becomes a support ticket.
    await waitFor(() => {
      expect(container.textContent).toContain(
        "9 voice(s) cached and 1 withdrawn by the voice platform.",
      );
    });
  });

  it("says WHICH empty it is when nothing can be chosen", async () => {
    // SYNCED, NOTHING ENABLED — the state a Refresh will not fix, so the sentence must not
    // send the operator to press it.
    const { container } = renderAdminPage(
      <VoicesPage />,
      routes({
        [OPS_VOICES_PATH]: catalogue({
          voices: [voice({ state: "disabled", offered: false })],
          offered: 0,
          note: "The catalogue has been read, but no voice is enabled for this platform.",
        }),
      }),
    );
    await screen.findByRole("table");

    expect(container.textContent).toContain(
      "No voice can be chosen for any agent right now",
    );
    expect(container.textContent).toContain(
      "The catalogue has been read, but no voice is enabled for this platform.",
    );
    // The table is NOT empty in this state — every voice is there, switched off — so the
    // empty state must not have replaced it.
    expect(await screen.findByRole("table")).toBeTruthy();
  });

  it("renders a never-synced deployment as an empty state, not as a failure", async () => {
    const { container } = renderAdminPage(
      <VoicesPage />,
      routes({
        [OPS_VOICES_PATH]: catalogue({
          voices: [],
          offered: 0,
          source: "unsynced",
          note: "No voices are available yet.",
        }),
      }),
    );

    expect(
      await screen.findByText(
        /No voices have been read from the voice platform/i,
      ),
    ).toBeTruthy();
    expect(container.textContent).toMatch(/press Refresh/i);
    // §52: an empty catalogue is a state, and it must not be painted as a transport fault.
    expect(screen.queryByRole("button", { name: /Try again/i })).toBeNull();
  });

  it("shows a skeleton while the read is in flight, never an empty catalogue", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({ [OPS_VOICES_PATH]: stillLoading() }),
    );

    expect(
      await screen.findByText(/Loading the voices this platform offers/i),
    ).toBeTruthy();
    expect(screen.queryByText(/No voices have been read/i)).toBeNull();
  });

  it("renders a failed read as a refusal, never as 'no voices'", async () => {
    renderAdminPage(
      <VoicesPage />,
      routes({
        [OPS_VOICES_PATH]: problem(503, { title: "Upstream unavailable" }),
      }),
    );

    expect(await screen.findByText(/Upstream unavailable/i)).toBeTruthy();
    // The claim this screen must never make off a failed read: that the platform has no
    // voices. An operator who believes it goes and presses Refresh against a dead API.
    expect(
      screen.queryByText(/No voices have been read from the voice platform/i),
    ).toBeNull();
  });

  it("tells an admin without ops:manage why, instead of showing them an outage", async () => {
    renderAdminPage(<VoicesPage />, { ...routes(), [ADMIN_ME_PATH]: OPERATOR });

    expect(
      await screen.findByText(/curate the voices this platform offers/i),
    ).toBeTruthy();
    // The refusal INSTEAD of the table, and no retry button: this is a permission working
    // as designed, not a platform fault.
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: /Refresh/i })).toBeNull();
  });
});
