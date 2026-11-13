import { defineStore } from 'pinia'
import {
  createRecodePlan,
  executeRecodePlan,
  fetchRecodePlan,
  fetchRecodePlans,
  previewRecodePlan,
  type RecodePlanCreatePayload,
} from '../api/recode'
import type { RecodePlan, RecodePlanDetail } from '../types/domain'

interface RecodeState {
  plans: RecodePlan[]
  current: RecodePlanDetail | null
  loading: boolean
  working: boolean
  error: string
  notice: string
}

export const useRecodeStore = defineStore('recode', {
  state: (): RecodeState => ({
    plans: [],
    current: null,
    loading: false,
    working: false,
    error: '',
    notice: '',
  }),
  actions: {
    async loadPlans(selectFirst = true) {
      this.loading = true
      this.error = ''
      try {
        const result = await fetchRecodePlans()
        this.plans = result.plans
        if (selectFirst && this.plans.length && !this.current) {
          await this.openPlan(this.plans[0].id)
        }
      } catch (error) {
        this.error = (error as Error).message
      } finally {
        this.loading = false
      }
    },
    async openPlan(planId: string) {
      this.error = ''
      this.notice = ''
      try {
        this.current = await fetchRecodePlan(planId)
      } catch (error) {
        this.error = (error as Error).message
      }
    },
    async createPlan(payload: RecodePlanCreatePayload) {
      this.working = true
      this.error = ''
      this.notice = ''
      try {
        const detail = await createRecodePlan(payload)
        this.current = detail
        await this.loadPlans(false)
        this.plans = [detail.plan, ...this.plans.filter((item) => item.id !== detail.plan.id)]
        this.notice = `方案 ${detail.plan.plan_code} 已创建，请先生成预览再执行。`
        return detail
      } catch (error) {
        this.error = (error as Error).message
        throw error
      } finally {
        this.working = false
      }
    },
    async preview() {
      if (!this.current) return
      this.working = true
      this.error = ''
      this.notice = ''
      try {
        this.current = await previewRecodePlan(this.current.plan.id)
        await this.loadPlans(false)
        this.notice = '预览已生成：受影响商品 / 小票 / 规则 / 建议位如下，确认无误后执行。'
      } catch (error) {
        this.error = (error as Error).message
      } finally {
        this.working = false
      }
    },
    async execute() {
      if (!this.current) return
      this.working = true
      this.error = ''
      this.notice = ''
      try {
        this.current = await executeRecodePlan(this.current.plan.id)
        await this.loadPlans(false)
        if (this.current.plan.status === 'succeeded') {
          this.notice = '迁移完成：小票数 / 商品数 / 规则结果已逐项核对，历史结论与原商品编号全部保留。'
        } else if (this.current.plan.status === 'failed') {
          this.error = this.current.plan.error ?? '执行失败，可从断点续跑。'
        }
      } catch (error) {
        this.error = (error as Error).message
      } finally {
        this.working = false
      }
    },
  },
})
