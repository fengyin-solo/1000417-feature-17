<template>
  <section class="page" data-module="inflow">
    <header class="page-head">
      <div>
        <h2>进水监测管理</h2>
        <p class="page-desc">维护进水记录，围绕监测编号、采样时间、进水流量、化学需氧量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记进水记录</button>
        <button class="btn" type="button" @click="openBackfill">化验结果批量回填</button>
        <button class="btn" type="button" @click="exportRows">导出进水监测清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无进水监测数据，可先登记进水记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条进水监测记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="backfillOpen" class="modal-mask" @click.self="closeBackfill">
      <div class="modal" role="dialog" aria-modal="true" aria-label="化验结果批量回填">
        <div class="modal-head">
          <h3>化验结果批量回填</h3>
          <button class="link" type="button" @click="closeBackfill">关闭</button>
        </div>
        <p class="modal-tip">
          一次为多条记录填写化学需氧量、氨氮浓度、悬浮物与酸碱度；
          酸碱度需在 0-14 之间，悬浮物不能为空，系统逐条校验，不合格的值只标记不落库。
        </p>

        <div v-if="!backfillResults.length" class="modal-body">
          <table class="data-table backfill-table">
            <thead>
              <tr>
                <th>监测编号</th>
                <th>进水流量(m³/d)</th>
                <th v-for="field in labFields" :key="field">
                  {{ field }}<em v-if="field === '酸碱度'">(0-14)</em>
                </th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="draft in backfillDrafts" :key="String(draft.id)">
                <td>{{ draft.code }}</td>
                <td>{{ draft.flow }}</td>
                <td v-for="field in labFields" :key="field">
                  <input
                    v-model="draft.values[field]"
                    :disabled="draft.backfilled"
                    :placeholder="draft.backfilled ? '已回填' : '必填'"
                    inputmode="decimal"
                  />
                </td>
                <td>
                  <span v-if="draft.backfilled" class="tag done">已回填</span>
                  <span v-else class="tag">待回填</span>
                </td>
              </tr>
              <tr v-if="!backfillDrafts.length">
                <td :colspan="labFields.length + 3" class="empty-state">暂无可回填的进水记录</td>
              </tr>
            </tbody>
          </table>
          <p v-if="backfillError" class="error-text">{{ backfillError }}</p>
        </div>

        <div v-else class="modal-body">
          <p class="batch-summary" :class="{ partial: batch.failed > 0 }">{{ batch.message }}</p>
          <table class="data-table backfill-table">
            <thead>
              <tr>
                <th>监测编号</th>
                <th v-for="field in labFields" :key="field">{{ field }}</th>
                <th>回填结果</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="result in backfillResults" :key="resultIndex(result)">
                <td>{{ result.code ?? `#${result.id ?? '?'}` }}</td>
                <td v-for="field in labFields" :key="field">{{ result.values[field] || '—' }}</td>
                <td>
                  <span v-if="result.ok" class="tag done">已落库</span>
                  <span v-else class="tag fail">未落库：{{ result.reason }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <footer class="modal-foot">
          <button class="btn ghost" type="button" @click="closeBackfill">
            {{ backfillResults.length ? '完成并刷新列表' : '取消' }}
          </button>
          <button
            v-if="!backfillResults.length"
            class="btn primary"
            type="button"
            :disabled="backfillSubmitting || !submittableDrafts.length"
            @click="submitBackfill"
          >
            {{ backfillSubmitting ? '提交中…' : `提交回填（${submittableDrafts.length} 条）` }}
          </button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

interface BackfillDraft {
  id: number
  code: string
  flow: string | number | null
  backfilled: boolean
  values: Record<string, string>
}

interface BackfillItemResult {
  id: number | null
  code: string | null
  ok: boolean
  reason: string
  values: Record<string, string>
  entry: Row | null
}

interface BatchSummary {
  message: string
  succeeded: number
  failed: number
}

const ENDPOINT = '/api/inflow'
const columns = ["监测编号", "采样时间", "进水流量", "化学需氧量", "氨氮浓度", "悬浮物", "酸碱度", "监测状态"]
const labFields = ["化学需氧量", "氨氮浓度", "悬浮物", "酸碱度"]
const actions = ["开始检测", "确认记录", "作废记录"]
const statuses = ["待检测", "检测中", "已记录", "已作废"]
const stats = [{"label": "今日进水量", "value": 0}, {"label": "进水氨氮均值", "value": 0}, {"label": "待记录批次", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const backfillOpen = ref(false)
const backfillSubmitting = ref(false)
const backfillError = ref('')
const backfillDrafts = ref<BackfillDraft[]>([])
const backfillResults = ref<BackfillItemResult[]>([])
const batch = ref<BatchSummary>({ message: '', succeeded: 0, failed: 0 })

const submittableDrafts = computed(() =>
  backfillDrafts.value.filter(
    (draft) => !draft.backfilled && labFields.some((field) => draft.values[field]?.trim()),
  ),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '进水记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('进水监测动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '进水监测操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('进水记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '进水监测列表读取失败'
  }
}

async function openBackfill() {
  backfillError.value = ''
  backfillResults.value = []
  batch.value = { message: '', succeeded: 0, failed: 0 }
  backfillOpen.value = true
  try {
    // 批量面板需要看到全部记录，分页上限内一次性拉取
    const response = await request(`${ENDPOINT}?page=1&size=200`)
    if (!response.ok) {
      throw new Error('进水记录读取失败')
    }
    const payload = await response.json()
    const list: Row[] = payload.items ?? []
    backfillDrafts.value = list.map((row) => ({
      id: Number(row.id),
      code: String(row['监测编号'] ?? ''),
      flow: (row['进水流量'] as string | number | null) ?? null,
      backfilled: Boolean(row.labBackfilled),
      values: Object.fromEntries(
        labFields.map((field) => [field, row[field] == null ? '' : String(row[field])]),
      ),
    }))
  } catch (error) {
    backfillError.value = error instanceof Error ? error.message : '进水记录读取失败'
    backfillDrafts.value = []
  }
}

async function submitBackfill() {
  backfillError.value = ''
  backfillSubmitting.value = true
  const items = submittableDrafts.value.map((draft) => ({
    id: draft.id,
    values: Object.fromEntries(labFields.map((field) => [field, draft.values[field]?.trim() ?? ''])),
  }))
  try {
    const response = await request(`${ENDPOINT}/batch-backfill`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    })
    if (!response.ok) {
      throw new Error('批量回填请求未生效，请稍后重试')
    }
    const payload = await response.json()
    backfillResults.value = payload.items ?? []
    batch.value = {
      message: payload.message ?? '',
      succeeded: payload.succeeded ?? 0,
      failed: payload.failed ?? 0,
    }
  } catch (error) {
    backfillError.value = error instanceof Error ? error.message : '批量回填提交失败'
  } finally {
    backfillSubmitting.value = false
  }
}

function closeBackfill() {
  backfillOpen.value = false
  backfillDrafts.value = []
  backfillResults.value = []
  backfillError.value = ''
  // 关闭面板后重新拉取列表，保证页面与接口返回的落库结果一致
  void reload()
}

function resultIndex(result: BackfillItemResult): string {
  return String(result.id ?? `code-${result.code ?? Math.random()}`)
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: min(960px, 92vw);
  max-height: 86vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 16px 18px;
}
.modal-head { display: flex; justify-content: space-between; align-items: center; }
.modal-head h3 { margin: 0; font-size: 16px; }
.modal-tip { color: var(--muted); font-size: 12px; margin: 8px 0 12px; }
.backfill-table th em { font-style: normal; color: var(--muted); font-size: 11px; }
.backfill-table input { width: 92px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px; }
.backfill-table input:disabled { background: #f1f5f9; color: var(--muted); }
.tag { display: inline-block; font-size: 12px; color: var(--muted); }
.tag.done { color: #067647; }
.tag.fail { color: #b42318; }
.batch-summary { margin: 0 0 10px; font-size: 13px; color: #067647; }
.batch-summary.partial { color: #b54708; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
</style>
