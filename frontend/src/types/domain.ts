export type StoreTier = 'high' | 'mid' | 'low'
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export type RuleStatus = 'candidate' | 'adopted' | 'rejected' | 'parked'
export type ReviewDecision = 'adopt' | 'reject' | 'park'
export type SlotStatus = 'draft' | 'published' | 'archived'

export interface RunParams {
  min_support: number
  min_confidence: number
  max_itemset: number
  filter_lift: number
  filter_confidence: number
  shelf_slots?: number
  adoption_rate?: number
  sample_days?: number
}

export interface SelectionPreview {
  slot_count: number
  total_uplift: number
  slots: Array<{
    label: string
    rule_key: string
    uplift_month: number
    shelf_label: string
    zone: string
  }>
  skipped: Array<{ rule_key: string; label: string; reason: string }>
}

export interface RunSummary {
  basket_count: number
  min_count: number
  mean_amount: number
  by_size: Record<string, number>
  frequent_itemsets: number
  candidate_rules: number
  passed_rules: number
  filtered_out: number
  stable_rules: number
  params: RunParams
  selection: SelectionPreview
  algorithm: string
}

export interface MiningRun {
  id: string
  run_label: string
  status: RunStatus
  params: RunParams
  frequent_itemsets: number
  candidate_rules: number
  passed_rules: number
  stable_rules: number
  basket_count: number
  duration_ms: number
  summary: RunSummary | Record<string, never>
  error: string | null
  created_at: string | null
  finished_at: string | null
  itemsets?: Array<{ items: string[]; count: number; support: number; size: number }>
}

export interface ItemsetRow {
  items: string[]
  labels: string[]
  categories: string[]
  count: number
  support: number
  size: number
}

export interface BasketLine {
  sku: string
  name: string
  qty: number
  amount: number
}

export interface Basket {
  id: string
  basket_no: string
  store_code: string
  store_name: string
  store_tier: StoreTier
  channel: string
  basket_ts: string | null
  net_amount: number
  item_count: number
  lines: BasketLine[]
}

export interface DatasetSummary {
  baskets: number
  skus: number
  lines: number
  avg_lines: number
  revenue: number
  mean_amount: number
  stores: number
  sample_days: number
  adoption_rate: number
  tiers: Array<{ tier: StoreTier; baskets: number }>
  store_rows: Array<{ code: string; name: string; tier: StoreTier; baskets: number }>
  sku_support: Array<{ sku: string; name: string; baskets: number; support: number }>
  sample_baskets: Basket[]
}

export interface TierDetail {
  tier: StoreTier
  baskets: number
  cooccur: number
  antecedent: number
  consequent: number
  support: number
  lift: number
  ci_low: number
  ci_high: number
  stable: boolean
}

export interface RuleReview {
  id: string
  decision: ReviewDecision
  reason: string
  reviewer: string
  reviewer_email: string
  reviewed_at: string | null
}

export interface Rule {
  id: string
  rule_key: string
  run_id: string
  antecedent: string[]
  consequent: string[]
  antecedent_labels: string[]
  consequent_labels: string[]
  label: string
  support: number
  confidence: number
  lift: number
  conviction: number
  cooccur_count: number
  counterexample_count: number
  status: RuleStatus
  stable: boolean
  tier_lifts: { high: number | null; mid: number | null; low: number | null }
  tier_detail: TierDetail[]
  ci_low: number | null
  ci_high: number | null
  uplift_month: number
  conflict_group: string
  zone: string
  shelf_label: string
  note: string
  reviews?: RuleReview[]
}

export interface RuleDetail extends Rule {
  matrix: {
    skus: Array<{ sku: string; name: string; category: string; baskets: number }>
    matrix: number[][]
    baskets: number
  }
  counterexamples: Basket[]
  run: MiningRun
  uplift_basis: {
    cooccur_count: number
    mean_amount: number | null
    adoption_rate: number | null
    monthly_factor: number
    formula: string
  }
}

export interface RulesResponse {
  run: MiningRun | null
  rules: Rule[]
  total: number
  page: number
  page_size: number
  stats: { total: number; adopted: number; stable: number; candidate: number; total_uplift: number }
}

export interface PlanSlot {
  id: string
  slot_key: string
  position_index: number
  shelf_label: string
  zone: string
  conflict_group: string
  est_uplift: number
  status: SlotStatus
  note: string
  published_at: string | null
  buyer_hint: string
  rule: {
    id: string
    rule_key: string
    antecedent: string[]
    consequent: string[]
    antecedent_labels: string[]
    consequent_labels: string[]
    label: string
    lift: number
    confidence: number
    cooccur_count: number
    stable: boolean
    status: RuleStatus
    uplift_month: number
  } | null
}

export interface PlanBasis {
  mean_amount: number | null
  adoption_rate: number | null
  sample_days: number | null
  monthly_factor: number
  formula: string
}

export interface Plan {
  plan_code: string
  run_label: string
  basis?: PlanBasis
  status: SlotStatus
  slot_count: number
  total_uplift: number
  published_at: string | null
  slots: PlanSlot[]
  skipped: Array<{ rule_key: string; label: string; reason: string }>
  params: RunParams
}

export interface PlanSummary {
  plan_code: string
  status: SlotStatus
  slot_count: number
  total_uplift: number
  published_at: string | null
  run_label: string
}

/* ---------------------------------------------------------------- 换码迁移 ---- */

export type RecodeStatus = 'draft' | 'previewed' | 'running' | 'succeeded' | 'failed'
export type RecodeMappingStatus = 'pending' | 'applied' | 'failed'

export interface RecodeNewSku {
  name: string
  category: string
  price: string | number
  unit: string
  shelf_hint: string
}

export interface RecodePlan {
  id: string
  plan_code: string
  title: string
  status: RecodeStatus
  error: string | null
  mapping_count: number
  applied_count: number
  previewed_at: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface RecodeMapping {
  id: string
  old_code: string
  new_code: string
  old_name: string
  new_name: string
  create_sku: RecodeNewSku | null
  status: RecodeMappingStatus
  affected_baskets: number
  affected_rules: number
  affected_slots: number
  applied_baskets: number
  applied_lines: number
  applied_at: string | null
}

export interface RecodeImpactRule {
  id: string
  rule_key: string
  run_label: string
  label: string
  status: RuleStatus
  lift: number
  cooccur_count: number
}

export interface RecodeImpactSlot {
  slot_key: string
  plan_code: string
  shelf_label: string
  status: SlotStatus
}

export interface RecodeRuleProjection {
  rule_key_before: string
  rule_key_after: string
  before: { support: number; confidence: number; lift: number; cooccur_count: number }
  after: { support: number; confidence: number; lift: number; cooccur_count: number }
}

export interface RecodeImpactMapping {
  old_code: string
  new_code: string
  old_name: string
  new_name: string
  baskets: number
  both_baskets: number
  sample_baskets: string[]
  support: { old: number; new: number; merged: number }
  rules: RecodeImpactRule[]
  slots: RecodeImpactSlot[]
  reviews: number
}

export interface RecodeImpact {
  computed_at: string
  mappings: RecodeImpactMapping[]
  rule_projection: RecodeRuleProjection[]
  totals: { skus: number; baskets: number; rules: number; slots: number; reviews: number }
}

export interface RecodeCheck {
  name: string
  ok: boolean
  detail: string
}

export interface RecodeReconciliation {
  taken_at: string
  baskets_before: number
  baskets_after: number
  lines_before: number
  lines_after: number
  skus_active_before: number
  skus_active_after: number
  skus_deprecated: number
  skus_created: number
  mappings: Array<{
    old_code: string
    new_code: string
    old_name: string
    new_name: string
    old_support_before: number
    old_support_after: number
    new_support_before: number
    new_support_after: number
    both_support_before: number
    baskets_rewritten: number
    lines_rewritten: number
  }>
  groups: Array<{
    new_code: string
    old_codes: string[]
    merged_support_before: number
    new_support_after: number
  }>
  rules: RecodeRuleProjection[]
  preserved: {
    rules: number
    slots: number
    published_slots: number
    reviews: number
    aliases: Array<{ old_code: string; new_code: string }>
  }
  checks: RecodeCheck[]
}

export interface RecodePlanDetail {
  plan: RecodePlan
  mappings: RecodeMapping[]
  aliases: Array<{ old_code: string; new_code: string; created_at: string }>
  impact: RecodeImpact | null
  reconciliation: RecodeReconciliation | null
}
