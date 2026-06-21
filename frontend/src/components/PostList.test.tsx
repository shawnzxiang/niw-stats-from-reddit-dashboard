import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SlimRecord } from "../types";
import { PostList } from "./PostList";

function record(id: string, title: string, createdUtc: number): SlimRecord {
  return {
    id,
    title,
    permalink: `/r/EB2_NIW/comments/${id}/`,
    flair: "APPROVED",
    created_utc: createdUtc,
    outcome: "approved",
    degree: "PhD",
    field: "Software/Systems",
    profession: "Research scientist",
    law_firm: "Chen/WeGreened",
    publications: [3, true],
    patents: [1, true],
    citations: [40, true],
    years_experience: [null, false],
    processing_days: [120, true],
    premium_processing: true,
    was_rfed: false,
    rfe_date: null,
    rfe_response_date: null,
    run: "claude-cli/haiku",
    prompt_version: "p2",
    schema_version: "s2",
    classified_at: 1_781_494_548,
    selftext: `${title} body`,
    op_comments: null,
  };
}

describe("PostList", () => {
  it("opens the audit panel directly below the clicked row", () => {
    const { container } = render(
      <PostList
        records={[
          record("newest", "Newest post", 1_781_490_000),
          record("middle", "Middle post", 1_781_480_000),
          record("oldest", "Oldest post", 1_781_470_000),
        ]}
      />,
    );

    expect(container.querySelector(".postlist > .audit-pane")).not.toBeInTheDocument();
    expect(container.querySelector(".audit-row")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Middle post" }));
    const middleRow = screen.getByRole("button", { name: "Middle post" }).closest("tr");
    expect(middleRow).toHaveClass("selected");
    expect(middleRow?.nextElementSibling).toHaveClass("audit-row");
    expect(within(middleRow?.nextElementSibling as HTMLElement).getByText("Extracted metadata")).toBeInTheDocument();
    expect(within(middleRow?.nextElementSibling as HTMLElement).getByText(/Middle post body/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Newest post" }));
    const newestRow = screen.getByRole("button", { name: "Newest post" }).closest("tr");
    expect(newestRow).toHaveClass("selected");
    expect(newestRow?.nextElementSibling).toHaveClass("audit-row");
    expect(container.querySelectorAll(".audit-row")).toHaveLength(1);
  });
});
