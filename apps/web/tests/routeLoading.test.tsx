/**
 * Opening another operator screen shows something at once. Every route is dynamic, so
 * without a loading boundary a sidebar click shows nothing until the server answers
 * (measured on a production build at 400 ms latency: about one second of no change).
 */
import { existsSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AdminScreenLoading from "@/app/admin/loading";

describe("the operator console's loading boundary", () => {
  it("exists at the realm root, so every admin screen inherits it", () => {
    expect(existsSync(resolve(__dirname, "../src/app/admin/loading.tsx"))).toBe(true);
  });

  it("says a screen is opening rather than drawing nothing", () => {
    render(<AdminScreenLoading />);
    expect(screen.getByRole("status").textContent).toContain("Opening this screen");
  });
});
