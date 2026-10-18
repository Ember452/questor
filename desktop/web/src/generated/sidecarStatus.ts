/* AUTO-GENERATED from protocol/sidecar_status.schema.json. DO NOT EDIT. */
/**
 * Additive-only process-level state emitted by the desktop shell (§6-5). Distinct from the per-run event envelope: it carries no run_id. Producer = Rust shell (on_crash_detect); consumer = UI. Strict whitelist (additionalProperties:false); detail is bounded and never carries crash traces/secrets (C20).
 */
export interface SidecarStatus {
  state: "starting" | "ready" | "stopping" | "stopped" | "crashed";
  /**
   * Shell Fence generation; increments on crash-restart so the UI can drop stale status.
   */
  generation: number;
  /**
   * Bounded short attribution; never raw traceback or secrets (C20).
   */
  detail?: string | null;
}
