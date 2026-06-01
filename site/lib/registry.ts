// Mirrors web/api/dims.py — the dimensions, metrics, and filterable fields.
export const DIMENSIONS: Record<string, string> = {
  fiscal_year: "Fiscal year", month: "Month", awarding_agency: "Awarding agency",
  awarding_subagency: "Awarding sub-agency", funding_agency: "Funding agency",
  funding_subagency: "Funding sub-agency", recipient: "Recipient",
  recipient_parent: "Recipient parent", state: "Recipient state",
  county: "Recipient county", naics: "NAICS code", naics_desc: "Industry (NAICS)",
  psc: "PSC (product/service)", psc_desc: "Product/service", award_type: "Award type",
  extent_competed: "Competition", set_aside: "Set-aside", pricing: "Pricing type",
  business_size: "Business size",
};
export const METRICS: Record<string, string> = {
  obligations: "Obligations ($)", transactions: "Transactions",
  vendors: "Distinct vendors", vendors_nonzero_net: "Vendors (nonzero net)",
};
export const FILTER_FIELDS: Record<string, string> = {
  ...DIMENSIONS,
  funding_subagency_code: "Funding sub-agency CODE",
  awarding_subagency_code: "Awarding sub-agency CODE",
  naics_code: "NAICS code (raw)", psc_code: "PSC code (raw)",
};
export const DATASETS = [
  { value: "contracts", label: "Contracts (prime)" },
  { value: "assistance", label: "Assistance (grants/loans)" },
];
