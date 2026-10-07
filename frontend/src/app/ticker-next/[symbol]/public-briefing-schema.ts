import { z } from "zod";

const passage = z.object({ text: z.string(), claim_ids: z.array(z.string()) });

export const publicBriefingSchema = z.object({
  rejected_claim_count: z.number().optional(),
  coverage: z.object({ official: z.number(), news: z.number(), snapshot: z.number() }).optional(),
  status: z.enum(["ready", "pending", "stale", "insufficient", "unavailable", "invalid"]),
  message: z.string().optional(), as_of: z.string().optional(), collected_at: z.string().optional(),
  generated_at: z.string().optional(), model: z.string().optional(), prompt_version: z.string().optional(),
  sources: z.array(z.object({ source_id: z.string(), url: z.string().url(), title: z.string(), published_at: z.string().nullable(), collected_at: z.string(), entity: z.string(), kind: z.string() })).optional(),
  claims: z.array(z.object({ claim_id: z.string(), source_id: z.string(), statement: z.string(), kind: z.enum(["fact", "plan", "forecast"]), entity: z.string(), period: z.string().nullable() })).optional(),
  report: z.object({ summary: passage, business: passage, changes: passage, financials: passage, schedule: passage,
    arguments: z.array(z.object({ title: z.string(), fact: passage, impact: passage, counterpoint: passage, checkpoint: passage, timing: passage })) }).optional(),
});

export type PublicBriefingData = z.infer<typeof publicBriefingSchema>;

export type BriefingPassage = z.infer<typeof passage>;
