<template>
  <section class="page" data-module="inflow">
    <header class="page-head">
      <div>
        <h2>进水监测管理</h2>
        <p class="page-desc">维护进水记录，围绕监测编号、采样时间、进水流量、化学需氧量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记进水记录</button>
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

    <section v-if="backfillRows.length" class="backfill-panel">
      <header class="backfill-head">
        <h3>化验结果批量回填</h3>
        <p class="page-desc">
          为选中的 {{ backfillRows.length }} 条记录填写化学需氧量、氨氮浓度、悬浮物与酸碱度；
          酸碱度需在 0~14 之间、进水流量需合理，不合格的记录只标记原因不落库。
        </p>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>监测编号</th>
            <th>化学需氧量</th>
            <th>氨氮浓度</th>
            <th>悬浮物</th>
            <th>酸碱度</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in backfillRows" :key="String(row.id)">
            <td>{{ row.监测编号 }}</td>
            <td v-for="field in labFields" :key="field">
              <input
                v-model="backfillValues[String(row.id)][field]"
                :placeholder="`填写${field}`"
              />
            </td>
            <td><button class="link" type="button" @click="removeFromBackfill(row)">移出</button></td>
          </tr>
        </tbody>
      </table>
      <div class="backfill-actions">
        <button class="btn primary" type="button" :disabled="submitting" @click="submitBackfill">
          {{ submitting ? '正在提交…' : '提交批量回填' }}
        </button>
        <button class="btn ghost" type="button" @click="clearBackfill">清空待回填</button>
        <span v-if="backfillSummary" class="backfill-summary">{{ backfillSummary }}</span>
      </div>
      <ul v-if="backfillResults.length" class="backfill-results">
        <li v-for="item in backfillResults" :key="item.key" :class="item.ok ? 'ok-text' : 'error-text'">
          {{ item.label }}：{{ item.message }}
        </li>
      </ul>
    </section>

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
            <button
              class="link"
              type="button"
              :disabled="Boolean(row.lab_filled) || inBackfill(row)"
              @click="addToBackfill(row)"
            >
              {{ row.lab_filled ? '已回填' : inBackfill(row) ? '已加入回填' : '化验回填' }}
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
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type LabValues = Record<string, string>
type BackfillReport = { key: string; label: string; ok: boolean; message: string }

const ENDPOINT = '/api/inflow'
const columns = ["监测编号", "采样时间", "进水流量", "化学需氧量", "氨氮浓度", "悬浮物", "酸碱度", "监测状态"]
const actions = ["开始检测", "确认记录", "作废记录"]
const statuses = ["待检测", "检测中", "已记录", "已作废"]
const stats = [{"label": "今日进水量", "value": 0}, {"label": "进水氨氮均值", "value": 0}, {"label": "待记录批次", "value": 0}]
const labFields = ["化学需氧量", "氨氮浓度", "悬浮物", "酸碱度"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const backfillRows = ref<Row[]>([])
const backfillValues = ref<Record<string, LabValues>>({})
const backfillResults = ref<BackfillReport[]>([])
const backfillSummary = ref('')
const submitting = ref(false)

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

function inBackfill(row: Row) {
  return backfillRows.value.some((item) => String(item.id) === String(row.id))
}

function addToBackfill(row: Row) {
  errorMessage.value = ''
  if (row.lab_filled) {
    errorMessage.value = `进水记录 ${row.监测编号 ?? row.id} 已回填过化验结果，不能重复回填`
    return
  }
  if (inBackfill(row)) {
    return
  }
  backfillRows.value.push(row)
  backfillValues.value[String(row.id)] = { 化学需氧量: '', 氨氮浓度: '', 悬浮物: '', 酸碱度: '' }
}

function removeFromBackfill(row: Row) {
  backfillRows.value = backfillRows.value.filter((item) => String(item.id) !== String(row.id))
  delete backfillValues.value[String(row.id)]
  backfillResults.value = backfillResults.value.filter((item) => item.key !== String(row.id))
}

function clearBackfill() {
  backfillRows.value = []
  backfillValues.value = {}
  backfillResults.value = []
  backfillSummary.value = ''
}

function buildLabValues(row: Row): LabValues {
  const raw = backfillValues.value[String(row.id)] ?? {}
  const values: LabValues = {
    悬浮物: String(raw.悬浮物 ?? '').trim(),
    酸碱度: String(raw.酸碱度 ?? '').trim(),
  }
  // 化学需氧量、氨氮浓度留空时不覆盖原值；悬浮物、酸碱度必须随批次提交以便后端逐条校验
  if (String(raw.化学需氧量 ?? '').trim()) {
    values.化学需氧量 = String(raw.化学需氧量).trim()
  }
  if (String(raw.氨氮浓度 ?? '').trim()) {
    values.氨氮浓度 = String(raw.氨氮浓度).trim()
  }
  return values
}

function labelFor(entryId: unknown): string {
  const row = rows.value.find((item) => String(item.id) === String(entryId))
    ?? backfillRows.value.find((item) => String(item.id) === String(entryId))
  return row ? String(row.监测编号 ?? `记录 ${entryId}`) : `记录 ${entryId}`
}

async function submitBackfill() {
  errorMessage.value = ''
  backfillSummary.value = ''
  submitting.value = true
  try {
    const items = backfillRows.value.map((row) => ({
      entry_id: Number(row.id),
      values: buildLabValues(row),
    }))
    const response = await request(`${ENDPOINT}/lab-results`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    })
    if (!response.ok) {
      throw new Error('批量回填接口返回异常，请稍后重试')
    }
    const payload = await response.json()
    const reports = Array.isArray(payload.results) ? payload.results : []
    backfillResults.value = reports.map((item: { entry_id?: number; ok?: boolean; message?: string }) => ({
      key: String(item.entry_id),
      label: labelFor(item.entry_id),
      ok: Boolean(item.ok),
      message: String(item.message ?? ''),
    }))
    backfillSummary.value = String(payload.message ?? '')
    // 已写入的记录移出待回填列表；未通过校验的留在列表里，方便修正后随下一批重新提交
    const failedIds = new Set(reports.filter((item: { ok?: boolean }) => !item.ok).map((item: { entry_id?: number }) => String(item.entry_id)))
    backfillRows.value = backfillRows.value.filter((row) => failedIds.has(String(row.id)))
    if (!reports.length && payload.message) {
      errorMessage.value = String(payload.message)
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量回填失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('进水监测动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '进水监测动作未生效，请稍后重试')
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

onMounted(reload)
</script>
