export const SELLER_CALLER_LABEL = "Seller";
export const MAX_CHAT_RESULTS = 5;
// Fallbacks only; live values come from GET /search/config (backend main.py).
export const MIN_MATCH_THRESHOLD = 0.28;
export const WEAK_MATCH_THRESHOLD = 0.45; // suggest supervisor when top match is weak
export const SUPERVISOR_POLL_MS = 8000;

// Fallback for result highlighting; the live list comes from GET /search/config.
export const DEFAULT_SYNONYM_GROUPS = [
  ["otp", "one time password", "login code", "verification code"],
  ["listing", "product", "item", "catalogue", "catalog"],
  ["visible", "showing", "appear", "listed", "display"],
  ["bid", "tender", "rfq", "quotation"],
  ["invoice", "bill"],
  ["payment", "payout", "settlement"],
  ["dispute", "complaint", "grievance"],
];
