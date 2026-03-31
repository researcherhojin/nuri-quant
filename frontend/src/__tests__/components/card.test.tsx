import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
} from "@/components/ui/card";

describe("Card", () => {
  it("renders Card with children", () => {
    render(<Card>Card content</Card>);
    expect(screen.getByText("Card content")).toBeInTheDocument();
  });

  it("applies data-slot=card attribute", () => {
    const { container } = render(<Card>Test</Card>);
    const card = container.querySelector('[data-slot="card"]');
    expect(card).not.toBeNull();
  });

  it("applies custom className", () => {
    const { container } = render(<Card className="custom-class">Test</Card>);
    const card = container.querySelector('[data-slot="card"]');
    expect(card!.className).toContain("custom-class");
  });

  it("applies default size", () => {
    const { container } = render(<Card>Test</Card>);
    const card = container.querySelector('[data-slot="card"]');
    expect(card!.getAttribute("data-size")).toBe("default");
  });

  it("applies sm size", () => {
    const { container } = render(<Card size="sm">Test</Card>);
    const card = container.querySelector('[data-slot="card"]');
    expect(card!.getAttribute("data-size")).toBe("sm");
  });

  it("has rounded-xl and overflow-hidden", () => {
    const { container } = render(<Card>Test</Card>);
    const card = container.querySelector('[data-slot="card"]');
    expect(card!.className).toContain("rounded-xl");
    expect(card!.className).toContain("overflow-hidden");
  });
});

describe("CardHeader", () => {
  it("renders with children", () => {
    render(<CardHeader>Header</CardHeader>);
    expect(screen.getByText("Header")).toBeInTheDocument();
  });

  it("applies data-slot=card-header", () => {
    const { container } = render(<CardHeader>Test</CardHeader>);
    expect(container.querySelector('[data-slot="card-header"]')).not.toBeNull();
  });

  it("applies custom className", () => {
    const { container } = render(<CardHeader className="my-header">Test</CardHeader>);
    const el = container.querySelector('[data-slot="card-header"]');
    expect(el!.className).toContain("my-header");
  });
});

describe("CardTitle", () => {
  it("renders with children", () => {
    render(<CardTitle>My Title</CardTitle>);
    expect(screen.getByText("My Title")).toBeInTheDocument();
  });

  it("applies data-slot=card-title", () => {
    const { container } = render(<CardTitle>Test</CardTitle>);
    expect(container.querySelector('[data-slot="card-title"]')).not.toBeNull();
  });

  it("has font-medium class", () => {
    const { container } = render(<CardTitle>Test</CardTitle>);
    const el = container.querySelector('[data-slot="card-title"]');
    expect(el!.className).toContain("font-medium");
  });
});

describe("CardDescription", () => {
  it("renders with children", () => {
    render(<CardDescription>Some description</CardDescription>);
    expect(screen.getByText("Some description")).toBeInTheDocument();
  });

  it("applies data-slot=card-description", () => {
    const { container } = render(<CardDescription>Test</CardDescription>);
    expect(container.querySelector('[data-slot="card-description"]')).not.toBeNull();
  });

  it("has text-muted-foreground class", () => {
    const { container } = render(<CardDescription>Test</CardDescription>);
    const el = container.querySelector('[data-slot="card-description"]');
    expect(el!.className).toContain("text-muted-foreground");
  });
});

describe("CardAction", () => {
  it("renders with children", () => {
    render(<CardAction>Action</CardAction>);
    expect(screen.getByText("Action")).toBeInTheDocument();
  });

  it("applies data-slot=card-action", () => {
    const { container } = render(<CardAction>Test</CardAction>);
    expect(container.querySelector('[data-slot="card-action"]')).not.toBeNull();
  });
});

describe("CardContent", () => {
  it("renders with children", () => {
    render(<CardContent>Main content</CardContent>);
    expect(screen.getByText("Main content")).toBeInTheDocument();
  });

  it("applies data-slot=card-content", () => {
    const { container } = render(<CardContent>Test</CardContent>);
    expect(container.querySelector('[data-slot="card-content"]')).not.toBeNull();
  });

  it("has px-4 class", () => {
    const { container } = render(<CardContent>Test</CardContent>);
    const el = container.querySelector('[data-slot="card-content"]');
    expect(el!.className).toContain("px-4");
  });

  it("applies custom className", () => {
    const { container } = render(<CardContent className="pt-5">Test</CardContent>);
    const el = container.querySelector('[data-slot="card-content"]');
    expect(el!.className).toContain("pt-5");
  });
});

describe("CardFooter", () => {
  it("renders with children", () => {
    render(<CardFooter>Footer</CardFooter>);
    expect(screen.getByText("Footer")).toBeInTheDocument();
  });

  it("applies data-slot=card-footer", () => {
    const { container } = render(<CardFooter>Test</CardFooter>);
    expect(container.querySelector('[data-slot="card-footer"]')).not.toBeNull();
  });

  it("has border-t class", () => {
    const { container } = render(<CardFooter>Test</CardFooter>);
    const el = container.querySelector('[data-slot="card-footer"]');
    expect(el!.className).toContain("border-t");
  });

  it("has bg-muted/50 class", () => {
    const { container } = render(<CardFooter>Test</CardFooter>);
    const el = container.querySelector('[data-slot="card-footer"]');
    expect(el!.className).toContain("bg-muted/50");
  });
});

describe("Card composition", () => {
  it("renders full card structure", () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Title</CardTitle>
          <CardDescription>Description</CardDescription>
          <CardAction>Action Button</CardAction>
        </CardHeader>
        <CardContent>Body content</CardContent>
        <CardFooter>Footer content</CardFooter>
      </Card>
    );

    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Description")).toBeInTheDocument();
    expect(screen.getByText("Action Button")).toBeInTheDocument();
    expect(screen.getByText("Body content")).toBeInTheDocument();
    expect(screen.getByText("Footer content")).toBeInTheDocument();
  });

  it("renders card with only content", () => {
    render(
      <Card>
        <CardContent>Just content</CardContent>
      </Card>
    );
    expect(screen.getByText("Just content")).toBeInTheDocument();
  });
});
