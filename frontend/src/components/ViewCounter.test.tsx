import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ViewCounter } from "./ViewCounter";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ViewCounter", () => {
  it("renders the site-wide count once the endpoint responds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ count: "1,234" }) }),
    );
    render(<ViewCounter />);
    await waitFor(() => expect(screen.getByText(/1,234 views/)).toBeInTheDocument());
  });

  it("renders nothing when the counter setting is not enabled (403)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403 }));
    const { container } = render(<ViewCounter />);
    await waitFor(() => expect(container.querySelector(".view-count")).toBeNull());
    expect(container.querySelector(".view-count")).toBeNull();
  });

  it("renders nothing when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const { container } = render(<ViewCounter />);
    await waitFor(() => expect(container.querySelector(".view-count")).toBeNull());
    expect(container.querySelector(".view-count")).toBeNull();
  });
});
