import http from './http'
import type { RecodePlan, RecodePlanDetail, RecodeNewSku } from '../types/domain'

export interface RecodePlanCreatePayload {
  plan_code?: string
  title: string
  mappings: Array<{ old_code: string; new_code: string; create_sku?: RecodeNewSku | null }>
}

export async function fetchRecodePlans(): Promise<{ plans: RecodePlan[]; count: number }> {
  const { data } = await http.get('/recode/plans')
  return data
}

export async function createRecodePlan(payload: RecodePlanCreatePayload): Promise<RecodePlanDetail> {
  const { data } = await http.post<RecodePlanDetail>('/recode/plans', payload)
  return data
}

export async function fetchRecodePlan(planId: string): Promise<RecodePlanDetail> {
  const { data } = await http.get<RecodePlanDetail>(`/recode/plans/${planId}`)
  return data
}

export async function previewRecodePlan(planId: string): Promise<RecodePlanDetail> {
  const { data } = await http.post<RecodePlanDetail>(`/recode/plans/${planId}/preview`)
  return data
}

export async function executeRecodePlan(planId: string): Promise<RecodePlanDetail> {
  const { data } = await http.post<RecodePlanDetail>(`/recode/plans/${planId}/execute`)
  return data
}
