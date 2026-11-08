import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnswerRating } from "@/components/copilot/AnswerRating";
import type { Session } from "@/lib/api/client";
import { voteBody, votePath } from "@/lib/copilot/rating";

import { problem, renderAdminPage } from "./harness";

const SESSION: Session = { orgSlug: "acme" };
const TURN = "0192f0aa-1111-7000-8000-0000000000a1";
const PUT = `PUT ${votePath("client", TURN)}`;

function bodies(calls: { method: string; path: string; body: string | null }[]) {
  return calls
    .filter((call) => call.method === "PUT")
    .map((call) => JSON.parse(call.body ?? "{}") as Record<string, unknown>);
}

describe("thumbs on a Pip answer (D-937)", () => {
  it("sends a thumbs up, and a second press takes it back", async () => {
    const { calls } = renderAdminPage(
      <AnswerRating turnId={TURN} session={SESSION} realm="client" />,
      { [PUT]: { turn_id: TURN, vote: "up", vote_reason: null } },
    );
    const up = screen.getByRole("button", { name: "Helpful" });
    expect(up.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(up);
    expect(up.getAttribute("aria-pressed")).toBe("true");
    await screen.findByText("Thanks");

    fireEvent.click(up);
    expect(up.getAttribute("aria-pressed")).toBe("false");
    await waitFor(() => expect(bodies(calls)).toHaveLength(2));
    expect(bodies(calls)).toEqual([
      { vote: "up", reason: null, note: null },
      { vote: null, reason: null, note: null },
    ]);
  });

  it("asks why after a thumbs down and sends the reason, with a note only for Other", async () => {
    const { calls } = renderAdminPage(
      <AnswerRating turnId={TURN} session={SESSION} realm="client" />,
      { [PUT]: { turn_id: TURN, vote: "down", vote_reason: null } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Not helpful" }));
    const reasons = screen.getByRole("group", { name: "What went wrong?" });
    expect(reasons).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Other" }));
    fireEvent.change(screen.getByLabelText("In a few words"), {
      target: { value: "  it missed the booking  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(bodies(calls)).toHaveLength(2));
    expect(bodies(calls)[1]).toEqual({ vote: "down", reason: "other", note: "it missed the booking" });
    expect(screen.queryByRole("group", { name: "What went wrong?" })).toBeNull();
  });

  it("shows the stored vote and goes back to it when a save fails", async () => {
    renderAdminPage(
      <AnswerRating turnId={TURN} session={SESSION} realm="client" vote="up" />,
      { [PUT]: problem(404, { type: "https://calevate.tech/problems/not_found", title: "Answer not found", status: 404 }) },
    );
    const up = screen.getByRole("button", { name: "Helpful" });
    expect(up.getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Not helpful" }));
    // The server's own reason shows under the thumbs (BUILD-LOG §52), said ONCE (audit 8 Nov
    // W4-05: a second "Couldn't save. Try again." line with no button used to sit beside it).
    expect((await screen.findByRole("alert")).textContent).toContain("Answer not found");
    expect(screen.queryByText(/Couldn't save/)).toBeNull();
    // A refusal trying again cannot fix offers no Try again.
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(up.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Not helpful" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("offers Try again on a passing failure, and it sends the same choice again (audit 8 Nov W4-05)", async () => {
    const { calls } = renderAdminPage(
      <AnswerRating turnId={TURN} session={SESSION} realm="client" />,
      {
        [PUT]: problem(503, {
          type: "https://calevate.tech/problems/unavailable",
          title: "Busy right now",
          status: 503,
          retryable: true,
        }),
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));
    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    fireEvent.click(retry);
    await waitFor(() => expect(bodies(calls)).toHaveLength(2));
    expect(bodies(calls)).toEqual([
      { vote: "up", reason: null, note: null },
      { vote: "up", reason: null, note: null },
    ]);
  });

  it("never sends a reason with a thumbs up or a note without Other", () => {
    expect(voteBody({ vote: "up", reason: "wrong", note: "x" })).toEqual({
      vote: "up",
      reason: null,
      note: null,
    });
    expect(voteBody({ vote: "down", reason: "too_slow", note: "x" })).toEqual({
      vote: "down",
      reason: "too_slow",
      note: null,
    });
    expect(votePath("admin", TURN)).toBe(`/v1/admin/copilot/turns/${TURN}/vote`);
  });
});
