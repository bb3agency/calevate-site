import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider, useMutation } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ActionButton, problemToast, useActionFeedback, useAsyncAction } from "@/components/arc/feedback";
import { MOTION } from "@/components/arc/motion";
import { ToastProvider, useToast } from "@/components/arc/toast";
import { ApiProblem } from "@/lib/api/client";

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}

const TAKEN = new ApiProblem(409, {
  type: "https://calevate.tech/problems/agent_name_taken",
  title: "That name is taken",
  detail: "Another agent is already called Reception.",
  retryable: false,
});

function Rename({ fail, inline = false }: { fail: boolean; inline?: boolean }) {
  const rename = useMutation({
    mutationFn: async () => {
      if (fail) throw TAKEN;
      return { name: "Reception" };
    },
  });
  const renameFeedback = useActionFeedback(rename, {
    errorTitle: "Could not rename the agent",
    errorDisplay: inline ? "inline" : "toast",
    successToast: "Agent renamed",
    undo: () => undefined,
  });
  return (
    <ActionButton status={renameFeedback.status} successLabel="Renamed" onClick={() => renameFeedback.run()}>
      Rename agent
    </ActionButton>
  );
}

describe("ActionButton", () => {
  it("keeps its name through every state and says the outcome outside the name", () => {
    const { rerender } = render(<ActionButton>Save changes</ActionButton>);
    const button = screen.getByRole("button", { name: "Save changes" });
    expect(button.dataset.status).toBe("idle");
    for (const status of ["pending", "success", "error"] as const) {
      rerender(
        <ActionButton status={status} successLabel="Saved">
          Save changes
        </ActionButton>,
      );
      expect(screen.getByRole("button", { name: "Save changes" }).dataset.status).toBe(status);
    }
    expect(screen.getByRole("status").textContent).toBe("Did not work");
  });

  it("ignores presses while pending without losing focus", () => {
    const onClick = vi.fn();
    render(
      <ActionButton status="pending" onClick={onClick}>
        Save
      </ActionButton>,
    );
    const button = screen.getByRole("button", { name: "Save" });
    button.focus();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(button);
  });

  it("waits with its reason shown and described, ignores presses and a form's submit, then comes back", () => {
    const onClick = vi.fn();
    const onSubmit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault());
    const view = (waitingFor: string | null) => (
      <form onSubmit={onSubmit}>
        <ActionButton type="submit" waitingFor={waitingFor} onClick={onClick}>
          Continue
        </ActionButton>
      </form>
    );
    const { rerender } = render(view("Waiting for your file to be read."));
    const button = screen.getByRole("button", { name: "Continue" });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.hasAttribute("disabled")).toBe(false);
    expect(button.getAttribute("aria-describedby")).toBe(screen.getByText("Waiting for your file to be read.").id);
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
    rerender(view(null));
    expect(button.hasAttribute("aria-disabled")).toBe(false);
    expect(button.hasAttribute("aria-describedby")).toBe(false);
    expect(screen.queryByText("Waiting for your file to be read.")).toBeNull();
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});

describe("useActionFeedback", () => {
  it("runs one action once when it is started twice in the same tick, and other arguments still run", async () => {
    const sent: string[] = [];
    let resolve: (() => void) | undefined;
    function Twice() {
      const confirm = useMutation({
        mutationFn: (token: string) =>
          new Promise<void>((done) => {
            sent.push(token);
            resolve = done;
          }),
      });
      const feedback = useActionFeedback(confirm, {});
      return (
        <button
          type="button"
          onClick={() => {
            feedback.run("t1");
            feedback.run("t1");
            feedback.run("t2");
          }}
        >
          Confirm
        </button>
      );
    }
    render(wrap(<Twice />));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(sent).toEqual(["t1", "t2"]));
    await act(async () => resolve?.());
  });

  it("shows success on the button and offers Undo in a toast", async () => {
    render(wrap(<Rename fail={false} />));
    fireEvent.click(screen.getByRole("button", { name: "Rename agent" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Rename agent" }).dataset.status).toBe("success"));
    expect(await screen.findByRole("group", { name: "Done: Agent renamed" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Undo" })).toBeTruthy();
  });

  it("puts a failure on the button and in an assertive toast with the server's words and code", async () => {
    render(wrap(<Rename fail />));
    fireEvent.click(screen.getByRole("button", { name: "Rename agent" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Rename agent" }).dataset.status).toBe("error"));
    const toast = await screen.findByRole("group", { name: "Error: That name is taken" });
    expect(toast.textContent).toContain("Another agent is already called Reception.");
    expect(toast.textContent).toContain("agent_name_taken");
    // Not retryable, so no "Try again" in the toast.
    expect(toast.textContent).not.toContain("Try again");
    expect(screen.getByRole("alert").textContent).toContain("That name is taken");
  });

  it("does not carry a failure's code, sentence or Try again into the success that replaces it", async () => {
    const BUSY = new ApiProblem(503, {
      type: "https://calevate.tech/problems/engine_unavailable",
      title: "The voice service did not answer",
      detail: "Nothing was changed.",
      retryable: true,
      kind: "dependency",
      trace_id: "abc123",
    });
    let fail = true;
    function Save() {
      const save = useMutation({
        mutationFn: async () => {
          if (fail) throw BUSY;
          return { ok: true };
        },
      });
      const feedback = useActionFeedback(save, { errorTitle: "Could not save", successToast: "Saved" });
      return (
        <ActionButton status={feedback.status} onClick={() => feedback.run()}>
          Save
        </ActionButton>
      );
    }
    render(wrap(<Save />));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const failed = await screen.findByRole("group", { name: "Error: The voice service did not answer" });
    expect(failed.textContent).toContain("engine_unavailable");
    fail = false;
    // Pressed again on the button itself, so the failure toast is still up to be replaced.
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const saved = await screen.findByRole("group", { name: "Done: Saved" });
    expect(saved.textContent).not.toContain("engine_unavailable");
    expect(saved.textContent).not.toContain("Nothing was changed.");
    expect(within(saved).queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("announces the success of a form that closes itself on success", async () => {
    function Form({ onDone }: { onDone: () => void }) {
      const save = useMutation({ mutationFn: async () => ({ ok: true }), onSuccess: onDone });
      const feedback = useActionFeedback(save, { successToast: "Note added" });
      return (
        <ActionButton status={feedback.status} onClick={() => feedback.run()}>
          Add note
        </ActionButton>
      );
    }
    function Screen() {
      const [open, setOpen] = useState(true);
      return open ? <Form onDone={() => setOpen(false)} /> : <p>Closed</p>;
    }
    render(wrap(<Screen />));
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    await screen.findByText("Closed");
    expect(await screen.findByRole("group", { name: "Done: Note added" })).toBeTruthy();
  });

  it("announces the failure of a form that is closed while it saves", async () => {
    function Form() {
      const save = useMutation({
        mutationFn: async () => {
          throw TAKEN;
        },
      });
      const feedback = useActionFeedback(save, { errorTitle: "Could not rename the agent" });
      return (
        <ActionButton status={feedback.status} onClick={() => feedback.run()}>
          Rename
        </ActionButton>
      );
    }
    function Screen() {
      const [open, setOpen] = useState(true);
      return open ? (
        <div onClickCapture={() => queueMicrotask(() => setOpen(false))}>
          <Form />
        </div>
      ) : (
        <p>Closed</p>
      );
    }
    render(wrap(<Screen />));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    await screen.findByText("Closed");
    expect(await screen.findByRole("group", { name: "Error: That name is taken" })).toBeTruthy();
  });

  it("announces a success once, not again from the effect", async () => {
    render(wrap(<Rename fail={false} />));
    fireEvent.click(screen.getByRole("button", { name: "Rename agent" }));
    await screen.findByRole("group", { name: "Done: Agent renamed" });
    await act(async () => {});
    expect(screen.getAllByRole("group", { name: "Done: Agent renamed" })).toHaveLength(1);
  });

  it("raises no toast when the screen shows the failure inline", async () => {
    render(wrap(<Rename fail inline />));
    fireEvent.click(screen.getByRole("button", { name: "Rename agent" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Rename agent" }).dataset.status).toBe("error"));
    expect(screen.queryByRole("group", { name: /Error/ })).toBeNull();
  });
});

describe("useAsyncAction", () => {
  function Copy({ action }: { action: () => Promise<void> }) {
    const copy = useAsyncAction(action, { errorTitle: "Could not copy" });
    return (
      <ActionButton status={copy.status} successLabel="Copied" onClick={() => copy.run()}>
        Copy
      </ActionButton>
    );
  }

  it("treats a rejection as the failure", async () => {
    render(wrap(<Copy action={() => Promise.reject(new Error("Clipboard is blocked."))} />));
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy" }).dataset.status).toBe("error"));
    expect((await screen.findByRole("group", { name: "Error: Could not copy" })).textContent).toContain(
      "Clipboard is blocked.",
    );
  });
});

describe("toast stack", () => {
  function Raise({ onReady }: { onReady: (api: ReturnType<typeof useToast>) => void }) {
    onReady(useToast());
    return null;
  }

  it("updates a toast in place, and errors stay until dismissed", async () => {
    // Fake timers throughout, exits included. Switching to real timers part-way strands
    // motion's frame loop on a frame scheduled under the fake clock, and its exit settles
    // through promises between frames, so only the async advance lets a card leave.
    vi.useFakeTimers();
    try {
      let api!: ReturnType<typeof useToast>;
      render(wrap(<Raise onReady={(a) => (api = a)} />));
      await act(async () => {});
      let id = "";
      act(() => {
        id = api.toast({ kind: "loading", title: "Placing a test call" });
      });
      expect(screen.getByRole("group", { name: "Working: Placing a test call" })).toBeTruthy();
      act(() => api.update(id, { kind: "error", title: "The call did not connect" }));
      expect(screen.queryByRole("group", { name: /Placing/ })).toBeNull();
      act(() => vi.advanceTimersByTime(60_000));
      expect(screen.getByRole("group", { name: "Error: The call did not connect" })).toBeTruthy();
      act(() => api.toast({ kind: "success", title: "Saved" }));
      act(() => vi.advanceTimersByTime(5_100));
      // The card plays its short exit before it leaves the DOM.
      await act(() => vi.advanceTimersByTimeAsync(1_000));
      expect(screen.queryByRole("group", { name: "Done: Saved" })).toBeNull();
      expect(screen.getByRole("group", { name: "Error: The call did not connect" })).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
      await act(() => vi.advanceTimersByTimeAsync(1_000));
      expect(screen.queryByRole("group", { name: /Error/ })).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("is a safe no-op outside a provider", () => {
    let api!: ReturnType<typeof useToast>;
    render(<Raise onReady={(a) => (api = a)} />);
    expect(api.toast({ title: "x" })).toBe("");
  });
});

describe("problemToast", () => {
  it("keeps the plain message and the code, and never invents one", () => {
    expect(problemToast(TAKEN, "Could not save")).toEqual({
      title: "That name is taken",
      description: "Another agent is already called Reception.",
      code: "agent_name_taken",
    });
    expect(problemToast(new Error(""), "Could not save")).toEqual({
      title: "Could not save",
      description: "Try again in a moment.",
      code: undefined,
    });
  });
});

describe("motion values", () => {
  it("match the CSS motion tokens, so there is one scale", () => {
    const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");
    const ms = (name: string) => Number(new RegExp(`--duration-${name}:\\s*(\\d+)ms`).exec(css)?.[1]) / 1000;
    expect(MOTION.duration).toEqual({ press: ms("press"), fast: ms("fast"), base: ms("base"), slow: ms("slow") });
    const curve = (name: string) =>
      new RegExp(`--${name}:\\s*cubic-bezier\\(([^)]*)\\)`).exec(css)?.[1].split(",").map(Number);
    expect([...MOTION.ease.out]).toEqual(curve("ease-out-strong"));
    expect([...MOTION.ease.inOut]).toEqual(curve("ease-in-out-strong"));
    expect([...MOTION.ease.drawer]).toEqual(curve("ease-drawer-curve"));
  });
});
