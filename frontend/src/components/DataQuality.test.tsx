import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SlimRecord } from "../types";
import { CompletenessStrip, DataQualityBanner, completenessItems } from "./DataQuality";

const baseRecord: SlimRecord = {
  id: "a",
  title: "A",
  permalink: "/r/EB2_NIW/comments/a/",
  flair: "APPROVED",
  created_utc: 1_700_000_000,
  outcome: "approved",
  degree: null,
  field: null,
  law_firm: null,
  publications: [null, false],
  citations: [null, false],
  years_experience: [null, false],
  processing_days: [null, false],
  premium_processing: null,
  was_rfed: null,
  rfe_date: null,
  rfe_response_date: null,
};

describe("DataQualityBanner", () => {
  it("shows partial-run provenance", () => {
    render(
      <DataQualityBanner
        backend="claude-cli"
        version="p2/s2"
        processed={220}
        candidates={4190}
        pending={3970}
        isPartial
        recordCount={47}
      />,
    );

    expect(screen.getByText(/Preliminary dataset/)).toBeInTheDocument();
    expect(screen.getByText(/220 \/ 4,190 candidates processed/)).toBeInTheDocument();
  });

  it("stays hidden for complete non-empty datasets", () => {
    const { container } = render(
      <DataQualityBanner
        backend="mock"
        version="p2/s2"
        processed={2}
        candidates={2}
        pending={0}
        isPartial={false}
        recordCount={2}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

describe("CompletenessStrip", () => {
  it("computes known-rate percentages from records", () => {
    const records: SlimRecord[] = [
      {
        ...baseRecord,
        degree: "PhD",
        field: "CS/AI",
        citations: [0, true],
        premium_processing: true,
      },
      { ...baseRecord, id: "b", title: "B" },
    ];

    const degree = completenessItems(records).find((i) => i.key === "degree");
    const citations = completenessItems(records).find((i) => i.key === "citations");
    expect(degree?.rate).toBe(0.5);
    expect(citations?.known).toBe(1);

    render(<CompletenessStrip records={records} />);
    expect(screen.getByText("Data completeness")).toBeInTheDocument();
    expect(screen.getAllByText("50%").length).toBeGreaterThan(0);
  });
});
