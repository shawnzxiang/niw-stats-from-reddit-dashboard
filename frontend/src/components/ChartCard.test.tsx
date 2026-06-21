import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChartCard } from "./ChartCard";

describe("ChartCard", () => {
  it("renders title and n, and toggles hide-unknown", () => {
    const onToggle = vi.fn();
    render(
      <ChartCard title="Degree" n={5} unknownCount={2} hideUnknown={false} onToggleHide={onToggle}>
        <div>chart</div>
      </ChartCard>,
    );
    expect(screen.getByText("Degree")).toBeInTheDocument();
    expect(screen.getByText(/n=5/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalledWith(true);
  });
});
