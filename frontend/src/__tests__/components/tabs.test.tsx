import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

// Mock @base-ui/react/tabs
vi.mock("@base-ui/react/tabs", () => {
  const TabsRoot = ({ children, className, ...props }: { children: React.ReactNode; className?: string; [key: string]: unknown }) => (
    <div data-slot="tabs" className={className} data-testid="tabs-root" {...props}>{children}</div>
  );
  TabsRoot.displayName = "TabsRoot";

  const TabsList = ({ children, className, ...props }: { children: React.ReactNode; className?: string; [key: string]: unknown }) => (
    <div data-slot="tabs-list" className={className} data-testid="tabs-list" {...props}>{children}</div>
  );
  TabsList.displayName = "TabsList";

  const TabsTab = ({ children, className, ...props }: { children: React.ReactNode; className?: string; [key: string]: unknown }) => (
    <button data-slot="tabs-trigger" className={className} data-testid="tabs-trigger" {...props}>{children}</button>
  );
  TabsTab.displayName = "TabsTab";

  const TabsPanel = ({ children, className, ...props }: { children: React.ReactNode; className?: string; [key: string]: unknown }) => (
    <div data-slot="tabs-content" className={className} data-testid="tabs-content" {...props}>{children}</div>
  );
  TabsPanel.displayName = "TabsPanel";

  return {
    Tabs: {
      Root: TabsRoot,
      List: TabsList,
      Tab: TabsTab,
      Panel: TabsPanel,
    },
  };
});

// Mock class-variance-authority
vi.mock("class-variance-authority", () => ({
  cva: (base: string, config?: { variants?: { variant?: Record<string, string> } }) => {
    return (options?: { variant?: string }) => {
      let result = base;
      if (options?.variant && config?.variants?.variant?.[options.variant]) {
        result += " " + config.variants.variant[options.variant];
      }
      return result;
    };
  },
}));

describe("Tabs", () => {
  it("renders Tabs root component", () => {
    render(
      <Tabs>
        <TabsList>
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
        </TabsList>
        <TabsContent value="tab1">Content 1</TabsContent>
      </Tabs>
    );
    expect(screen.getByTestId("tabs-root")).toBeInTheDocument();
  });

  it("renders TabsList container", () => {
    render(
      <Tabs>
        <TabsList>
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
        </TabsList>
      </Tabs>
    );
    expect(screen.getByTestId("tabs-list")).toBeInTheDocument();
  });

  it("renders multiple tab triggers", () => {
    render(
      <Tabs>
        <TabsList>
          <TabsTrigger value="tab1">First</TabsTrigger>
          <TabsTrigger value="tab2">Second</TabsTrigger>
          <TabsTrigger value="tab3">Third</TabsTrigger>
        </TabsList>
      </Tabs>
    );
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
    expect(screen.getByText("Third")).toBeInTheDocument();
  });

  it("renders tab content panels", () => {
    render(
      <Tabs>
        <TabsList>
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
        </TabsList>
        <TabsContent value="tab1">Content Panel 1</TabsContent>
      </Tabs>
    );
    expect(screen.getByText("Content Panel 1")).toBeInTheDocument();
  });

  it("applies custom className to Tabs root", () => {
    render(
      <Tabs className="my-custom-class">
        <TabsList>
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
        </TabsList>
      </Tabs>
    );
    const root = screen.getByTestId("tabs-root");
    expect(root.className).toContain("my-custom-class");
  });

  it("applies custom className to TabsList", () => {
    render(
      <Tabs>
        <TabsList className="custom-list-class">
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
        </TabsList>
      </Tabs>
    );
    const list = screen.getByTestId("tabs-list");
    expect(list.className).toContain("custom-list-class");
  });

  it("applies custom className to TabsTrigger", () => {
    render(
      <Tabs>
        <TabsList>
          <TabsTrigger value="tab1" className="custom-trigger-class">Tab 1</TabsTrigger>
        </TabsList>
      </Tabs>
    );
    const trigger = screen.getByText("Tab 1");
    expect(trigger.className).toContain("custom-trigger-class");
  });

  it("applies custom className to TabsContent", () => {
    render(
      <Tabs>
        <TabsList>
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
        </TabsList>
        <TabsContent value="tab1" className="custom-content-class">Content</TabsContent>
      </Tabs>
    );
    const content = screen.getByText("Content");
    expect(content.className).toContain("custom-content-class");
  });

  it("renders with line variant on TabsList", () => {
    render(
      <Tabs>
        <TabsList variant="line">
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
        </TabsList>
      </Tabs>
    );
    const list = screen.getByTestId("tabs-list");
    expect(list).toBeInTheDocument();
  });

  it("exports all expected components", () => {
    expect(Tabs).toBeDefined();
    expect(TabsList).toBeDefined();
    expect(TabsTrigger).toBeDefined();
    expect(TabsContent).toBeDefined();
  });
});
