import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TimeRangeSelector } from "./TimeRangeSelector";

describe("TimeRangeSelector", () => {
  it("emits the selected range key", () => {
    const onRange = vi.fn();
    render(
      <TimeRangeSelector rangeKey="24m" onRange={onRange} customStart="" customEnd="" onCustom={() => {}} />,
    );
    fireEvent.click(screen.getByText("1 year"));
    expect(onRange).toHaveBeenCalledWith("12m");
  });

  it("shows two date inputs when custom is selected", () => {
    const { container } = render(
      <TimeRangeSelector rangeKey="custom" onRange={() => {}} customStart="" customEnd="" onCustom={() => {}} />,
    );
    expect(container.querySelectorAll('input[type="date"]')).toHaveLength(2);
  });
});
