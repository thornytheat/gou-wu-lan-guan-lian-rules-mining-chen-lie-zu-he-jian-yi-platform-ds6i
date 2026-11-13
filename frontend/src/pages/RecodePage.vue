<template>
  <div class="recode">
    <PageHeader
      eyebrow="04 · 商品主数据换码"
      title="换码迁移"
      description="旧码并入新码后停用：历史小票按新身份合并统计，已发布陈列建议、复核理由与原商品编号全部保留。方案先预览后执行，失败可从断点续跑。"
    >
      <template #actions>
        <button
          v-if="canWrite"
          class="btn btn--quiet"
          type="button"
          data-test="toggle-create"
          @click="toggleCreate"
        >
          {{ form.open ? '收起新建' : '新建方案' }}
        </button>
        <button
          class="btn"
          type="button"
          data-test="preview-plan"
          :disabled="!canPreview"
          :title="canWrite ? '' : '仅品类总监可执行换码'"
          @click="store.preview()"
        >
          生成预览
        </button>
        <button
          class="btn btn--mint"
          type="button"
          data-test="execute-plan"
          :disabled="!canExecute"
          :title="canWrite ? '' : '仅品类总监可执行换码'"
          @click="store.execute()"
        >
          {{ executeLabel }}
        </button>
      </template>
    </PageHeader>

    <div v-if="!canRead" class="notice notice--tag">
      店长账号无换码权限：换码是主数据操作，仅品类总监可建方案与执行，品类运营可查看。
    </div>
    <template v-else>
      <div v-if="store.error" class="notice notice--alert" data-test="recode-error">{{ store.error }}</div>
      <div v-else-if="store.notice" class="notice notice--mint" data-test="recode-notice">{{ store.notice }}</div>

      <div class="columns">
        <section class="col">
          <ShelfBand index="01" title="换码方案" caption="同一方案重跑不新增映射、不重复重算">
            <div v-if="!store.plans.length" class="muted">还没有换码方案。</div>
            <table v-else class="grid-table" data-test="plan-list">
              <thead>
                <tr>
                  <th>方案</th>
                  <th>标题</th>
                  <th>状态</th>
                  <th class="ta-r">映射进度</th>
                  <th>创建时间</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="plan in store.plans"
                  :key="plan.id"
                  :class="{ 'is-current': plan.id === current?.plan.id }"
                  @click="store.openPlan(plan.id)"
                >
                  <td class="mono">{{ plan.plan_code }}</td>
                  <td>{{ plan.title || '—' }}</td>
                  <td>
                    <span :class="['chip', statusChip(plan.status)]">{{ RECODE_STATUS_LABELS[plan.status] }}</span>
                  </td>
                  <td class="ta-r is-num">{{ plan.applied_count }}/{{ plan.mapping_count }}</td>
                  <td class="mono">{{ formatDateTime(plan.created_at) }}</td>
                </tr>
              </tbody>
            </table>
          </ShelfBand>

          <ShelfBand v-if="form.open" index="—" title="新建换码方案" caption="新旧身份未对齐会整体拒绝，不落库">
            <div class="create">
              <label class="param">
                <span class="label">方案标题</span>
                <input v-model="form.title" class="field" placeholder="例：2026 秋 · 零食线条码焕新" data-test="form-title" />
              </label>
              <div v-for="(row, index) in form.rows" :key="index" class="maprow">
                <select v-model="row.old_code" class="field maprow__old" data-test="form-old">
                  <option value="" disabled>选择旧码（在售）</option>
                  <option v-for="sku in activeSkus" :key="sku.sku" :value="sku.sku">
                    {{ sku.sku }} · {{ sku.name }}
                  </option>
                </select>
                <span class="maprow__arrow">→</span>
                <input v-model.trim="row.new_code" class="field maprow__new" placeholder="新码，如 N12" data-test="form-new" />
                <label class="maprow__create">
                  <input v-model="row.create" type="checkbox" />
                  <span>创建新商品</span>
                </label>
                <template v-if="row.create">
                  <input v-model.trim="row.name" class="field" placeholder="新商品名称" />
                  <input v-model.trim="row.category" class="field" placeholder="品类" />
                  <input v-model.trim="row.price" class="field" placeholder="单价" type="number" step="0.01" min="0" />
                </template>
                <button class="btn btn--quiet btn--sm" type="button" @click="removeRow(index)">删除</button>
              </div>
              <div class="create__actions">
                <button class="btn btn--quiet btn--sm" type="button" @click="addRow">+ 加一条映射</button>
                <button
                  class="btn btn--ink btn--sm"
                  type="button"
                  data-test="submit-create"
                  :disabled="store.working || !formValid"
                  @click="submitCreate"
                >
                  创建方案（草稿）
                </button>
              </div>
              <p class="param__hint">
                校验口径：旧码必须在售、新码已存在或由方案声明创建、不允许链式换码（A→B→C 需拍平）；多个旧码可并入同一新码。
              </p>
            </div>
          </ShelfBand>

          <ShelfBand
            index="02"
            title="换码映射"
            :caption="current ? `${current.plan.plan_code} · ${current.mappings.length} 条映射` : '先选择方案'"
          >
            <div v-if="!current" class="muted">选择左侧方案查看映射。</div>
            <table v-else class="grid-table" data-test="mapping-list">
              <thead>
                <tr>
                  <th>旧码 → 新码</th>
                  <th>旧商品</th>
                  <th>新商品</th>
                  <th>状态</th>
                  <th class="ta-r">影响小票</th>
                  <th class="ta-r">已改写行</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="mapping in current.mappings" :key="mapping.id">
                  <td class="mono">{{ mapping.old_code }} → {{ mapping.new_code }}</td>
                  <td>{{ mapping.old_name }}</td>
                  <td>
                    {{ mapping.new_name }}
                    <span v-if="mapping.create_sku" class="chip chip--tag">方案新建</span>
                  </td>
                  <td>
                    <span :class="['chip', mapping.status === 'applied' ? 'chip--mint' : mapping.status === 'failed' ? 'chip--alert' : '']">
                      {{ RECODE_MAPPING_STATUS_LABELS[mapping.status] }}
                    </span>
                  </td>
                  <td class="ta-r is-num">{{ mapping.affected_baskets || '—' }}</td>
                  <td class="ta-r is-num">{{ mapping.applied_lines || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </ShelfBand>

          <ShelfBand
            index="03"
            title="影响预览"
            :caption="impact ? `受影响的商品 / 小票 / 规则 / 建议位 · 生成于 ${formatDateTime(impact.computed_at)}` : '先「生成预览」'"
          >
            <div v-if="!impact" class="muted">预览只读计算影响面，不改任何数据；方案开始执行后预览冻结。</div>
            <template v-else>
              <div class="strip">
                <StatSlip :items="impactStats" />
              </div>
              <article v-for="item in impact.mappings" :key="item.old_code" class="impact">
                <header class="impact__head">
                  <span class="mono impact__codes">{{ item.old_code }} → {{ item.new_code }}</span>
                  <span class="impact__names">{{ item.old_name }} → {{ item.new_name }}</span>
                  <span class="chip">{{ item.baskets }} 张小票</span>
                  <span v-if="item.both_baskets" class="chip chip--tag">新旧同票 {{ item.both_baskets }} 张</span>
                </header>
                <div class="impact__grid">
                  <div>
                    <div class="label">受影响小票（样本）</div>
                    <div class="impact__baskets">
                      <span v-for="no in item.sample_baskets" :key="no" class="mono chip">{{ no }}</span>
                      <span v-if="item.baskets > item.sample_baskets.length" class="impact__more">
                        等 {{ item.baskets }} 张
                      </span>
                    </div>
                    <div class="label impact__sublabel">支持度合并</div>
                    <div class="impact__support">
                      旧码 {{ item.support.old }} 张 ＋ 新码 {{ item.support.new }} 张
                      <template v-if="item.both_baskets"> − 同票 {{ item.both_baskets }} 张</template>
                      → 合并后 <b>{{ item.support.merged }}</b> 张
                    </div>
                  </div>
                  <div>
                    <div class="label">受影响规则（{{ item.rules.length }}）· 复核理由 {{ item.reviews }} 条保留</div>
                    <table v-if="item.rules.length" class="grid-table">
                      <tbody>
                        <tr v-for="rule in item.rules" :key="rule.id">
                          <td>{{ rule.label }}</td>
                          <td class="mono">{{ rule.run_label }}</td>
                          <td><span class="chip">{{ RULE_STATUS_LABELS[rule.status] }}</span></td>
                          <td class="ta-r is-num">lift {{ rule.lift.toFixed(2) }}</td>
                        </tr>
                      </tbody>
                    </table>
                    <div v-else class="muted">不涉及历史规则。</div>
                    <div class="label impact__sublabel">受影响建议位（{{ item.slots.length }}，原样保留）</div>
                    <table v-if="item.slots.length" class="grid-table">
                      <tbody>
                        <tr v-for="slot in item.slots" :key="slot.slot_key">
                          <td class="mono">{{ slot.slot_key }}</td>
                          <td>{{ slot.shelf_label }}</td>
                          <td>
                            <span :class="['chip', slot.status === 'published' ? 'chip--mint' : '']">
                              {{ SLOT_STATUS_LABELS[slot.status] }}
                            </span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                    <div v-else class="muted">不涉及陈列建议位。</div>
                  </div>
                </div>
              </article>

              <div v-if="impact.rule_projection.length" class="projection">
                <div class="label">规则结果投影（最新批次 · 合并后身份重算）</div>
                <table class="grid-table" data-test="rule-projection">
                  <thead>
                    <tr>
                      <th>规则（迁移前）</th>
                      <th>规则（迁移后）</th>
                      <th class="ta-r">共现 前→后</th>
                      <th class="ta-r">lift 前→后</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in impact.rule_projection" :key="row.rule_key_before">
                      <td class="mono">{{ row.rule_key_before }}</td>
                      <td class="mono">{{ row.rule_key_after }}</td>
                      <td class="ta-r is-num">{{ row.before.cooccur_count }} → {{ row.after.cooccur_count }}</td>
                      <td class="ta-r is-num">{{ row.before.lift.toFixed(2) }} → {{ row.after.lift.toFixed(2) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </ShelfBand>
        </section>

        <aside class="col col--side">
          <ShelfBand index="04" title="执行状态" caption="每条映射一个断点，失败可续跑">
            <div v-if="!current" class="muted">未选择方案。</div>
            <div v-else class="runstate" data-test="run-state">
              <div class="runstate__row">
                <span>方案状态</span>
                <span :class="['chip', statusChip(current.plan.status)]">
                  {{ RECODE_STATUS_LABELS[current.plan.status] }}
                </span>
              </div>
              <div class="runstate__row">
                <span>映射进度</span>
                <span class="tag-num">{{ current.plan.applied_count }} / {{ current.plan.mapping_count }}</span>
              </div>
              <div class="runstate__row">
                <span>预览时间</span>
                <span class="mono">{{ formatDateTime(current.plan.previewed_at) }}</span>
              </div>
              <div class="runstate__row">
                <span>完成时间</span>
                <span class="mono">{{ formatDateTime(current.plan.finished_at) }}</span>
              </div>
              <p v-if="current.plan.error" class="runstate__error">{{ current.plan.error }}</p>
              <p class="runstate__hint">
                执行前会对当前主数据重跑对齐校验；新旧身份未对齐时整单拒绝、零写入。
              </p>
            </div>
          </ShelfBand>

          <ShelfBand index="05" title="迁移核对" caption="迁移前后小票数 / 商品数 / 规则结果逐项对照">
            <div v-if="!recon" class="muted">方案完成后生成核对表。</div>
            <div v-else class="recon" data-test="reconciliation">
              <div class="strip">
                <StatSlip :items="reconStats" />
              </div>
              <ul class="checks">
                <li v-for="check in recon.checks" :key="check.name" :class="{ 'is-bad': !check.ok }">
                  <span class="checks__mark">{{ check.ok ? '✓' : '✗' }}</span>
                  <span>{{ check.detail }}</span>
                </li>
              </ul>

              <div v-if="recon.rules.length" class="label">规则结果对照</div>
              <table v-if="recon.rules.length" class="grid-table">
                <thead>
                  <tr>
                    <th>规则 前→后</th>
                    <th class="ta-r">共现 前→后</th>
                    <th class="ta-r">lift 前→后</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in recon.rules" :key="row.rule_key_before">
                    <td class="mono">{{ row.rule_key_before }} → {{ row.rule_key_after }}</td>
                    <td class="ta-r is-num">{{ row.before.cooccur_count }} → {{ row.after.cooccur_count }}</td>
                    <td class="ta-r is-num">{{ row.before.lift.toFixed(2) }} → {{ row.after.lift.toFixed(2) }}</td>
                  </tr>
                </tbody>
              </table>

              <div class="label">历史结论与原编号保留</div>
              <div class="preserved">
                <div class="preserved__row">
                  <span>历史规则（含已采纳结论）</span>
                  <span class="tag-num">{{ recon.preserved.rules }} 条保留</span>
                </div>
                <div class="preserved__row">
                  <span>已发布建议位</span>
                  <span class="tag-num">{{ recon.preserved.published_slots }} / {{ recon.preserved.slots }} 个保留</span>
                </div>
                <div class="preserved__row">
                  <span>复核理由</span>
                  <span class="tag-num">{{ recon.preserved.reviews }} 条保留</span>
                </div>
                <div class="preserved__row">
                  <span>原商品编号（别名）</span>
                  <span class="tag-num">{{ recon.preserved.aliases.length }} 个保留</span>
                </div>
                <div class="preserved__aliases">
                  <span v-for="alias in recon.preserved.aliases" :key="alias.old_code" class="mono chip chip--tag">
                    {{ alias.old_code }} → {{ alias.new_code }}
                  </span>
                </div>
              </div>
            </div>
          </ShelfBand>
        </aside>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '../components/common/PageHeader.vue'
import ShelfBand from '../components/common/ShelfBand.vue'
import StatSlip, { type SlipItem } from '../components/common/StatSlip.vue'
import { useRecodeStore } from '../stores/recodeStore'
import { useAuthStore } from '../stores/authStore'
import { fetchDataset } from '../api/mining'
import {
  RECODE_MAPPING_STATUS_LABELS,
  RECODE_STATUS_LABELS,
  RULE_STATUS_LABELS,
  SLOT_STATUS_LABELS,
} from '../constants/enums'
import { formatDateTime, formatInteger } from '../utils/format'
import type { RecodeStatus } from '../types/domain'

const store = useRecodeStore()
const auth = useAuthStore()

const canRead = computed(() => auth.can('recode:read'))
const canWrite = computed(() => auth.can('recode:write'))
const current = computed(() => store.current)
const impact = computed(() => current.value?.impact ?? null)
const recon = computed(() => current.value?.reconciliation ?? null)

const canPreview = computed(
  () =>
    canWrite.value &&
    !store.working &&
    !!current.value &&
    (current.value.plan.status === 'draft' || current.value.plan.status === 'previewed'),
)
const canExecute = computed(
  () =>
    canWrite.value &&
    !store.working &&
    !!current.value &&
    (current.value.plan.status === 'previewed' || current.value.plan.status === 'failed'),
)
const executeLabel = computed(() => {
  if (!current.value) return '执行迁移'
  if (current.value.plan.status === 'failed') return '从断点续跑'
  if (current.value.plan.status === 'succeeded') return '已完成'
  if (current.value.plan.status === 'running') return '执行中…'
  return '执行迁移'
})

function statusChip(status: RecodeStatus): string {
  if (status === 'succeeded') return 'chip--mint'
  if (status === 'failed') return 'chip--alert'
  if (status === 'running') return 'chip--tag'
  return ''
}

const impactStats = computed<SlipItem[]>(() => {
  const totals = impact.value?.totals
  if (!totals) return []
  return [
    { label: '受影响商品', value: totals.skus, unit: '个' },
    { label: '受影响小票', value: formatInteger(totals.baskets), unit: '张' },
    { label: '受影响规则', value: totals.rules, unit: '条' },
    { label: '受影响建议位', value: totals.slots, unit: '个' },
    { label: '复核理由保留', value: totals.reviews, unit: '条', tone: 'mint' },
  ]
})

const reconStats = computed<SlipItem[]>(() => {
  const value = recon.value
  if (!value) return []
  return [
    { label: '小票数', value: `${formatInteger(value.baskets_before)} → ${formatInteger(value.baskets_after)}`, unit: '张' },
    { label: '在售商品', value: `${value.skus_active_before} → ${value.skus_active_after}`, unit: '个' },
    { label: '明细行数', value: `${formatInteger(value.lines_before)} → ${formatInteger(value.lines_after)}`, unit: '行' },
    {
      label: '改写明细行',
      value: formatInteger(value.mappings.reduce((sum, row) => sum + row.lines_rewritten, 0)),
      unit: '行',
      tone: 'mint',
    },
  ]
})

/* ---------------- 新建方案表单 ---------------- */

const activeSkus = ref<Array<{ sku: string; name: string }>>([])
const form = reactive({
  open: false,
  title: '',
  rows: [] as Array<{
    old_code: string
    new_code: string
    create: boolean
    name: string
    category: string
    price: string
  }>,
})

function blankRow() {
  return { old_code: '', new_code: '', create: true, name: '', category: '', price: '' }
}

async function toggleCreate() {
  form.open = !form.open
  if (form.open && !form.rows.length) form.rows.push(blankRow())
  if (form.open && !activeSkus.value.length) {
    try {
      const dataset = await fetchDataset()
      activeSkus.value = dataset.sku_support.map((item) => ({ sku: item.sku, name: item.name }))
    } catch {
      /* 无 baskets:read 时留空，后端仍会校验 */
    }
  }
}

function addRow() {
  form.rows.push(blankRow())
}

function removeRow(index: number) {
  form.rows.splice(index, 1)
}

const formValid = computed(
  () =>
    form.rows.length > 0 &&
    form.rows.every(
      (row) =>
        row.old_code &&
        row.new_code &&
        row.old_code !== row.new_code &&
        (!row.create || (row.name && row.category && Number(row.price) > 0)),
    ),
)

async function submitCreate() {
  try {
    await store.createPlan({
      title: form.title,
      mappings: form.rows.map((row) => ({
        old_code: row.old_code,
        new_code: row.new_code,
        create_sku: row.create
          ? {
              name: row.name,
              category: row.category,
              price: row.price,
              unit: '件',
              shelf_hint: '',
            }
          : null,
      })),
    })
    form.open = false
    form.title = ''
    form.rows = [blankRow()]
  } catch {
    /* 错误已写入 store（含后端返回的对齐错误清单） */
  }
}

onMounted(async () => {
  if (canRead.value) {
    await store.loadPlans()
  }
})
</script>

<style scoped>
.recode {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.notice {
  margin-top: 12px;
  padding: 8px 12px;
  font-size: 12px;
  border: 1px dashed var(--shelf);
  background: var(--paper-2);
}
.notice--tag {
  border-color: var(--tag-deep);
  background: var(--tag-pale);
}
.notice--mint {
  border-color: var(--mint-deep);
  background: var(--mint-pale);
  color: var(--mint-ink);
}
.notice--alert {
  border-color: var(--alert);
  background: var(--alert-pale);
  color: var(--alert);
}
.columns {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(310px, 0.85fr);
  gap: 30px;
  align-items: start;
}
.col {
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.col--side {
  position: sticky;
  top: 58px;
}
.strip {
  margin: 4px 0 12px;
}
.mono {
  font-family: var(--tag-font);
  font-size: 11.5px;
  letter-spacing: 0.01em;
}
.ta-r {
  text-align: right;
}
tr.is-current td {
  background: color-mix(in oklch, var(--mint-pale) 70%, var(--paper));
}
tbody tr {
  cursor: pointer;
}
.muted {
  font-size: 12px;
  color: var(--ink-faint);
  padding: 8px 0;
}
.create {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.param {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.param__hint {
  font-size: 10px;
  color: var(--ink-faint);
}
.maprow {
  display: flex;
  gap: 7px;
  align-items: center;
  flex-wrap: wrap;
  border-bottom: 1px dotted var(--shelf-soft);
  padding-bottom: 8px;
}
.maprow__old {
  width: 190px;
}
.maprow__new {
  width: 110px;
}
.maprow__arrow {
  color: var(--ink-faint);
}
.maprow__create {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  font-size: 11px;
  color: var(--ink-soft);
}
.maprow .field:not(.maprow__old):not(.maprow__new) {
  width: 130px;
}
.create__actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.impact {
  border: 1px solid var(--shelf-soft);
  background: var(--paper-2);
  padding: 10px 12px;
  margin-bottom: 12px;
}
.impact__head {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.impact__codes {
  font-weight: 600;
}
.impact__names {
  font-size: 12px;
  color: var(--ink-soft);
}
.impact__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
  gap: 16px;
}
.impact__baskets {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 4px;
}
.impact__more {
  font-size: 10.5px;
  color: var(--ink-faint);
  align-self: center;
}
.impact__sublabel {
  margin-top: 10px;
}
.impact__support {
  font-size: 11.5px;
  color: var(--ink-soft);
  margin-top: 3px;
}
.projection {
  margin-top: 6px;
}
.runstate {
  display: flex;
  flex-direction: column;
}
.runstate__row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dotted var(--shelf-soft);
  font-size: 12px;
}
.runstate__error {
  margin-top: 8px;
  font-size: 11px;
  color: var(--alert);
  border: 1px dashed var(--alert);
  background: var(--alert-pale);
  padding: 6px 8px;
}
.runstate__hint {
  margin-top: 8px;
  font-size: 10.5px;
  color: var(--ink-faint);
}
.recon {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.checks {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
}
.checks li {
  display: flex;
  gap: 7px;
  align-items: baseline;
}
.checks__mark {
  font-family: var(--tag-font);
  color: var(--mint-ink);
  font-weight: 700;
}
.checks li.is-bad .checks__mark,
.checks li.is-bad {
  color: var(--alert);
}
.preserved {
  display: flex;
  flex-direction: column;
}
.preserved__row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 5px 0;
  border-bottom: 1px dotted var(--shelf-soft);
  font-size: 12px;
}
.preserved__aliases {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}
@media (max-width: 1279px) {
  .columns {
    grid-template-columns: minmax(0, 1fr);
  }
  .col--side {
    position: static;
  }
}
@media (max-width: 767px) {
  .impact__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
