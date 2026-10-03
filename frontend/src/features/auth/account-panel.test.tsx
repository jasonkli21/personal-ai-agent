import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AccountPanel } from "./account-panel";

describe("account controls", () => {
  it("shows when export and deletion are disabled by the deployment", () => {
    render(<AccountPanel exportEnabled={false} deletionEnabled={false} />);

    expect(screen.getByText("Export is disabled by the deployment operator.")).toBeInTheDocument();
    expect(screen.getByText("Deletion requests are disabled by the deployment operator.")).toBeInTheDocument();
  });
});
