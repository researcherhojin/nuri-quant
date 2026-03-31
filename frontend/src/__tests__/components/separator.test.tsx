import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Separator } from "@/components/ui/separator";

describe("Separator", () => {
  it("renders horizontal separator by default", () => {
    const { container } = render(<Separator />);
    const el = container.firstChild as HTMLElement;
    expect(el).toBeInTheDocument();
    expect(el.getAttribute("data-slot")).toBe("separator");
  });

  it("accepts custom className", () => {
    const { container } = render(<Separator className="my-4" />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("my-4");
  });

  it("renders with vertical orientation", () => {
    const { container } = render(<Separator orientation="vertical" />);
    const el = container.firstChild as HTMLElement;
    expect(el).toBeInTheDocument();
  });
});
