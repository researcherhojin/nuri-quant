/**
 * Branch-coverage test for OpportunityExplorer / OpportunityCard.
 *
 * Drives every remaining branch arm to 100% (v8 branch coverage). All arms
 * are REACHABLE via props / fetch fixtures — no v8-ignore needed, no runtime
 * logic changed in the source.
 *
 * Uncovered arms targeted (line refs are in opportunity-explorer.tsx):
 *   L50  `if (res.ok)` false arm            -> fetch returns ok:false
 *   L54  `?? data.action`  middle arm       -> final_action nullish, action set
 *   L54  `?? "HOLD"`       final arm        -> both nullish
 *   L56  `agreement_rate ? .. : 0` -> `: 0` -> agreement_rate falsy (0)
 *   L68  `|| verdictStyles.muted`           -> unknown verdict_level
 *   L80  `?? "—"`                           -> price null
 *   L89  `(change_5d ?? 0)` / `?? 0`        -> change_5d null
 *   L91  Vol badge JSX render arm           -> volume_ratio >= 1.5
 *   L94  `rsi < 30 ? emerald`               -> rsi < 30
 *   L94  `rsi > 70 ? red`                   -> rsi > 70
 *   L131 `"bg-zinc-700 text-zinc-400"`      -> action neither BUY nor SELL
 *   L141 `|| "기술지표 반대"`                -> divergence_reason empty
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import {
    render,
    screen,
    cleanup,
    fireEvent,
    waitFor,
} from "@testing-library/react";
import type { Opportunity } from "./opportunity-explorer";
import { OpportunityExplorer } from "./opportunity-explorer";

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

const make = (over: Partial<Opportunity>): Opportunity => ({
    ticker: "AAA",
    price: 100,
    change_1d: 1.0,
    change_5d: 2.5,
    volume_ratio: 1.0,
    rsi: 50,
    signal: "BUY",
    score: 80,
    pros: ["good thing"],
    cons: ["bad thing"],
    verdict: "괜찮은 후보",
    verdict_level: "positive",
    ...over,
});

describe("OpportunityExplorer / OpportunityCard branch coverage", () => {
    it("empty vs non-empty opportunities (line 181 both arms)", () => {
        const { container, rerender } = render(
            <OpportunityExplorer opportunities={[]} />,
        );
        expect(container.querySelector(".space-y-2")).toBeNull(); // empty arm
        rerender(
            <OpportunityExplorer opportunities={[make({ ticker: "BUYX" })]} />,
        );
        expect(container.querySelector(".space-y-2")).not.toBeNull(); // list arm
        expect(screen.getByText("BUYX")).toBeTruthy();
    });

    it("change_5d null -> `?? 0` fallback: emerald +0% (lines 69, 89 fallback arms)", () => {
        render(
            <OpportunityExplorer
                opportunities={[make({ ticker: "NULL5D", change_5d: null })]}
            />,
        );
        const span = screen.getByText(/5D\s*\+0%/);
        expect(span.className).toContain("text-emerald-400");
    });

    it("change_5d negative -> left (non-fallback) arms: red, no + sign", () => {
        render(
            <OpportunityExplorer
                opportunities={[make({ ticker: "NEG5D", change_5d: -4.2 })]}
            />,
        );
        const span = screen.getByText(/5D\s*-4\.2%/);
        expect(span.className).toContain("text-red-400");
        expect(span.textContent).not.toContain("+");
    });

    it("price null -> `?? \"—\"` fallback (line 80 right arm)", () => {
        render(
            <OpportunityExplorer
                opportunities={[make({ ticker: "NOPRICE", price: null })]}
            />,
        );
        expect(screen.getByText("$—")).toBeTruthy();
    });

    it("unknown verdict_level -> `|| verdictStyles.muted` (line 68 right arm)", () => {
        render(
            <OpportunityExplorer
                opportunities={[
                    make({ ticker: "MUTEDX", verdict_level: "unknown-xyz" }),
                ]}
            />,
        );
        // muted 스타일 라벨 = OPPORTUNITY.MUTED ("데이터 부족")
        expect(screen.getByText("데이터 부족")).toBeTruthy();
    });

    it("volume_ratio >= 1.5 -> Vol badge renders (line 91 JSX arm)", () => {
        render(
            <OpportunityExplorer
                opportunities={[
                    make({ ticker: "HIVOL", volume_ratio: 2.3 }),
                ]}
            />,
        );
        expect(screen.getByText(/Vol\s*2\.3x/)).toBeTruthy();
    });

    it("rsi < 30 -> emerald RSI (line 94 first cond arm)", () => {
        render(
            <OpportunityExplorer
                opportunities={[make({ ticker: "LORSI", rsi: 22 })]}
            />,
        );
        const rsi = screen.getByText(/RSI\s*22/);
        expect(rsi.className).toContain("text-emerald-400");
    });

    it("rsi > 70 -> red RSI (line 94 second cond arm)", () => {
        render(
            <OpportunityExplorer
                opportunities={[make({ ticker: "HIRSI", rsi: 81 })]}
            />,
        );
        const rsi = screen.getByText(/RSI\s*81/);
        expect(rsi.className).toContain("text-red-400");
    });

    it("res.ok false -> analysis stays null, button remains (line 50 false arm)", async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: false,
            json: async () => ({}),
        });
        vi.stubGlobal("fetch", fetchMock);

        render(
            <OpportunityExplorer
                opportunities={[make({ ticker: "FAILOK" })]}
            />,
        );
        fireEvent.click(screen.getByRole("button"));

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledWith("/api/consensus/FAILOK");
        });
        // ok=false -> setAnalysis 미호출 -> 버튼이 그대로 남음, 분석 패널 없음
        await waitFor(() => {
            expect(screen.getByRole("button")).toBeTruthy();
        });
        expect(screen.queryByText("판정 0")).toBeNull();
    });

    it("analysis: no final_action/action/confidence -> HOLD + 0 + agreement 0 (lines 54, 54, 56, 131)", async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            // final_action, action 모두 누락 -> `?? "HOLD"` 최종 arm,
            // final_confidence, confidence 누락 -> `?? 0`,
            // agreement_rate falsy(0) -> `: 0` arm.
            json: async () => ({ agreement_rate: 0 }),
        });
        vi.stubGlobal("fetch", fetchMock);

        render(
            <OpportunityExplorer opportunities={[make({ ticker: "HOLDX" })]} />,
        );
        fireEvent.click(screen.getByRole("button"));

        // action HOLD -> 배지는 BUY/SELL 아님 -> "bg-zinc-700 text-zinc-400" (line 131)
        const badge = await screen.findByText(
            (_c, el) =>
                (el?.className ?? "").includes("bg-zinc-700") &&
                (el?.textContent ?? "") === "HOLD",
        );
        expect(badge).toBeTruthy();
        // confidence 0 fallback
        expect(screen.getByText("판정 0")).toBeTruthy();
        // agreement 0% (`: 0` arm)
        expect(screen.getByText("0% 합의")).toBeTruthy();
    });

    it("analysis: final_action absent but action present -> `?? data.action` middle arm (line 54)", async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            // final_action 누락, action 존재 -> 중간 arm 사용.
            json: async () => ({
                action: "BUY",
                confidence: 42,
                agreement_rate: 0.6,
            }),
        });
        vi.stubGlobal("fetch", fetchMock);

        render(
            <OpportunityExplorer opportunities={[make({ ticker: "ACTX" })]} />,
        );
        fireEvent.click(screen.getByRole("button"));

        // action BUY -> emerald 배지 (line 129 left), confidence 42 (left arm)
        const badge = await screen.findByText(
            (_c, el) =>
                (el?.className ?? "").includes("bg-emerald-500/20") &&
                (el?.textContent ?? "") === "BUY",
        );
        expect(badge).toBeTruthy();
        expect(screen.getByText("판정 42")).toBeTruthy();
        expect(screen.getByText("60% 합의")).toBeTruthy();
    });

    it("analysis: SELL + divergence with empty reason -> title fallback (lines 130, 141 fallback)", async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({
                final_action: "SELL",
                final_confidence: 77,
                agreement_rate: 0.9,
                divergence_flag: true,
                divergence_reason: "", // empty -> `|| "기술지표 반대"` fallback
            }),
        });
        vi.stubGlobal("fetch", fetchMock);

        render(
            <OpportunityExplorer opportunities={[make({ ticker: "SELLX" })]} />,
        );
        fireEvent.click(screen.getByRole("button"));

        // SELL -> red 배지 (line 130 left arm)
        const badge = await screen.findByText(
            (_c, el) =>
                (el?.className ?? "").includes("bg-red-500/20") &&
                (el?.textContent ?? "") === "SELL",
        );
        expect(badge).toBeTruthy();
        // divergence badge with fallback title
        const div = screen.getByTestId("divergence-badge");
        expect(div.getAttribute("title")).toBe("기술지표 반대");
    });
});
