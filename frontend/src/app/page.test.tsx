import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("renders the application name", () => {
    render(<Home />);

    expect(screen.getByRole("main")).toHaveTextContent("Personal AI System");
  });
});
