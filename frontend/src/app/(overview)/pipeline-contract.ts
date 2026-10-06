import { z } from "zod";

export const pipelineSchema = z.object({ steps: z.array(z.object({
  execution_mode: z.string().optional(),
  artifact: z.object({ status: z.string(), date: z.string().nullable(), count: z.number().nullable(), recorded_at: z.string().nullable().optional() }).optional(),
  step: z.string(), label: z.string(), status: z.string(), last_updated: z.string().nullable(),
})) });

export const schedulerSchema = z.object({
  status: z.string(), last_heartbeat: z.string().optional(), detail: z.string().optional(),
});

export type Pipeline = z.infer<typeof pipelineSchema>;
