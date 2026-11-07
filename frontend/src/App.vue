<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";

interface Lead {
  id: number;
  version: number;
  title: string;
  excerpt: string;
  university: string;
  channel: string;
  published_at: string;
  status: string;
  eligibility: string;
  category: string;
  note: string;
  rule_signal: string | null;
  exclusion_reason: string | null;
  source_url: string | null;
  channel_url: string | null;
  amount_fen: number | null;
  feedback?: {
    label: string;
    note: string;
    actor: string;
    created_at: string;
  }[];
}
interface Stats {
  posts: number;
  candidates: number;
  qualified: number;
  revenue_fen: number;
  statuses: Record<string, number>;
  universities: { name: string; posts: number; candidates: number }[];
}
interface Job {
  guild: string;
  day: string;
  channel_name: string;
  pages: number;
  coverage: string;
  posts: number;
}

const authenticated = ref(false);
const restoring = ref(true);
const csrf = ref("");
const loginForm = reactive({ username: "admin", password: "" });
const busy = ref(false);
const tab = ref("leads");
const stats = ref<Stats>({
  posts: 0,
  candidates: 0,
  qualified: 0,
  revenue_fen: 0,
  statuses: {},
  universities: [],
});
const items = ref<Lead[]>([]);
const jobs = ref<Job[]>([]);
const total = ref(0);
const filters = reactive({
  candidate_only: true,
  university: "",
  status: "",
  q: "",
  page: 1,
  page_size: 30,
});
const selected = ref<Lead | null>(null);
const dialog = ref(false);
const reviewForm = reactive({
  version: 1,
  status: "new",
  eligibility: "pending",
  category: "unknown",
  note: "",
  label: "unknown",
  amount_fen: null as number | null,
});
const statusNames: Record<string, string> = {
  new: "待审核",
  qualified: "有效商机",
  contacted: "已人工跟进",
  won: "已成交",
  lost: "未成交",
  ignored: "已忽略",
};
const eligibilityNames: Record<string, string> = {
  pending: "待核实",
  eligible: "可承接",
  excluded: "已排除",
};
const categoryNames: Record<string, string> = {
  unknown: "待分类",
  ppt: "PPT",
  word: "Word",
  excel: "Excel",
  coding: "编程辅导",
  engineering: "工程软件",
  web: "网站开发",
  computer: "电脑使用指导",
  other: "其他技能",
};
const signalNames: Record<string, string> = {
  skill_review: "技能求助信号",
  paid_unclear: "有偿但任务不明",
  assessment_review: "考核性质待核实",
  image_review: "图片需求待审",
};
const coverageNames: Record<string, string> = {
  boundary_reached: "已到日期起点",
  api_end: "接口已返回末页",
  running: "扫描中",
  error: "扫描异常",
  budget_exhausted: "待继续扫描",
};
const completed = computed(
  () =>
    jobs.value.filter((job) =>
      ["boundary_reached", "api_end"].includes(job.coverage),
    ).length,
);
const money = computed({
  get: () =>
    reviewForm.amount_fen === null ? undefined : reviewForm.amount_fen / 100,
  set: (value: number | undefined) => {
    reviewForm.amount_fen =
      value === undefined ? null : Math.round(value * 100);
  },
});
const time = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });

async function api(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (csrf.value) headers.set("X-CSRF-Token", csrf.value);
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) authenticated.value = false;
    throw new Error(
      typeof result.detail === "string" ? result.detail : "请求未通过校验",
    );
  }
  return result;
}
async function loadLeads() {
  const query = new URLSearchParams(
    Object.entries(filters)
      .filter(([, value]) => value !== "")
      .map(([key, value]) => [key, String(value)]),
  );
  const result = await api("/leads?" + query.toString());
  items.value = result.items;
  total.value = result.total;
}
async function refresh() {
  const [dashboard, scans] = await Promise.all([
    api("/dashboard"),
    api("/scan-jobs"),
  ]);
  stats.value = dashboard;
  jobs.value = scans.items;
  await loadLeads();
}
async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  try {
    await action();
  } catch (error) {
    ElMessage.error((error as Error).message);
  } finally {
    busy.value = false;
  }
}
async function login() {
  await perform(async () => {
    const session = await api("/session", {
      method: "POST",
      body: JSON.stringify(loginForm),
    });
    csrf.value = session.csrf_token;
    loginForm.password = "";
    authenticated.value = true;
    await refresh();
  });
}
async function logout() {
  await perform(async () => {
    await api("/session", { method: "DELETE" });
    authenticated.value = false;
    csrf.value = "";
    dialog.value = false;
    selected.value = null;
    items.value = [];
  });
}
async function importData() {
  await perform(async () => {
    const result = await api("/imports/experiments", { method: "POST" });
    ElMessage.success(
      "导入完成，新增 " +
        result.imported +
        " 条，更新 " +
        result.updated +
        " 条",
    );
    await refresh();
  });
}
async function openLead(lead: Lead) {
  await perform(async () => {
    const detail: Lead = await api("/leads/" + lead.id);
    selected.value = detail;
    Object.assign(reviewForm, {
      version: detail.version,
      status: detail.status,
      eligibility: detail.eligibility,
      category: detail.category,
      note: detail.note,
      label: "unknown",
      amount_fen: detail.amount_fen,
    });
    dialog.value = true;
  });
}
async function saveReview() {
  if (!selected.value) return;
  await perform(async () => {
    await api("/leads/" + selected.value!.id + "/feedback", {
      method: "POST",
      body: JSON.stringify(reviewForm),
    });
    ElMessage.success("审核和跟进记录已保存");
    dialog.value = false;
    await refresh();
  });
}
function search() {
  filters.page = 1;
  void perform(loadLeads);
}

onMounted(async () => {
  try {
    const session = await api("/session");
    csrf.value = session.csrf_token;
    authenticated.value = true;
    await refresh();
  } catch {
    authenticated.value = false;
  } finally {
    restoring.value = false;
  }
});
</script>

<template>
  <main v-if="restoring" class="loading">正在恢复工作台会话…</main>
  <main v-else-if="!authenticated" class="login-page">
    <section class="login-intro">
      <span class="eyebrow">CHANNELRADAR</span>
      <h1>校园技能服务<br />获客工作台</h1>
      <p>查看需求来源、审核依据与跟进结果</p>
      <div class="login-flow">发现需求 → 人工核实 → 跟进记录 → 成交反馈</div>
    </section>
    <el-card class="login-card">
      <h2>管理员登录</h2>
      <p class="muted">登录后查看原帖、审核依据与跟进记录</p>
      <el-form label-position="top" @submit.prevent="login">
        <el-form-item label="账号"
          ><el-input v-model="loginForm.username" autocomplete="username"
        /></el-form-item>
        <el-form-item label="密码"
          ><el-input
            v-model="loginForm.password"
            type="password"
            show-password
            autocomplete="current-password"
        /></el-form-item>
        <el-button
          type="primary"
          native-type="submit"
          :loading="busy"
          class="full"
          >进入工作台</el-button
        >
      </el-form>
    </el-card>
  </main>
  <div v-else class="workspace">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">◎</span>
        <div>ChannelRadar<small>校园技能服务获客</small></div>
      </div>
      <nav aria-label="主导航">
        <button :class="{ active: tab === 'leads' }" @click="tab = 'leads'">
          商机审核
        </button>
        <button
          :class="{ active: tab === 'coverage' }"
          @click="tab = 'coverage'"
        >
          采集覆盖
        </button>
      </nav>
      <div class="sidebar-foot">
        <span class="status-dot"></span>人工审核与跟进<br /><small
          >来源、依据、结果可追溯</small
        >
      </div>
    </aside>
    <main class="content">
      <header class="page-header">
        <div>
          <span class="eyebrow">ACQUISITION WORKSPACE</span>
          <h1>{{ tab === "leads" ? "商机审核" : "采集覆盖" }}</h1>
        </div>
        <div class="actions">
          <el-button :loading="busy" @click="importData">导入采集结果</el-button
          ><el-button @click="perform(refresh)">刷新</el-button
          ><el-button text @click="logout">退出</el-button>
        </div>
      </header>
      <div class="metrics">
        <article>
          <span>已采集帖子</span
          ><strong>{{ stats.posts.toLocaleString() }}</strong
          ><small>已导入的完整日实验记录</small>
        </article>
        <article>
          <span>规则候选</span><strong>{{ stats.candidates }}</strong
          ><small>需要核查具体任务与时效</small>
        </article>
        <article>
          <span>人工确认有效</span><strong>{{ stats.qualified }}</strong
          ><small>已确认适合承接的需求</small>
        </article>
        <article>
          <span>已记录成交金额</span
          ><strong>¥{{ (stats.revenue_fen / 100).toFixed(2) }}</strong
          ><small>{{ stats.statuses.won || 0 }} 条成交记录</small>
        </article>
      </div>
      <el-alert
        title="当前候选由规则初筛。请结合原帖、具体用途和解决状态审核；AI 语义识别尚待接入。"
        type="info"
        :closable="false"
        show-icon
      />
      <section v-if="tab === 'leads'" class="panel">
        <div class="panel-heading">
          <div>
            <h2>需求与跟进队列</h2>
            <p>查看候选，也可以切换到全部帖子复核漏筛。</p>
          </div>
          <el-switch
            v-model="filters.candidate_only"
            active-text="仅商机队列"
            @change="search"
          />
        </div>
        <div class="filters">
          <el-input
            v-model="filters.q"
            placeholder="搜索需求内容"
            clearable
            @keyup.enter="search"
          />
          <el-select
            v-model="filters.university"
            placeholder="全部高校"
            clearable
            filterable
            @change="search"
            ><el-option
              v-for="school in stats.universities"
              :key="school.name"
              :label="school.name"
              :value="school.name"
          /></el-select>
          <el-select
            v-model="filters.status"
            placeholder="全部处理状态"
            clearable
            @change="search"
            ><el-option
              v-for="(label, value) in statusNames"
              :key="value"
              :label="label"
              :value="value"
          /></el-select>
          <el-button type="primary" @click="search">筛选</el-button>
        </div>
        <el-table
          :data="items"
          v-loading="busy"
          @row-click="openLead"
          row-class-name="clickable"
          empty-text="当前筛选条件下没有记录，可导入采集结果或查看全部帖子。"
        >
          <el-table-column label="需求内容" min-width="350"
            ><template #default="{ row }"
              ><div class="lead-title">{{ row.title || "图片帖" }}</div>
              <div class="muted excerpt">{{ row.excerpt }}</div>
              <span class="signal">{{
                signalNames[row.rule_signal] || "未命中当前规则"
              }}</span></template
            ></el-table-column
          >
          <el-table-column prop="university" label="高校" min-width="150" />
          <el-table-column label="承接判断" width="110"
            ><template #default="{ row }"
              ><el-tag
                :type="
                  row.eligibility === 'eligible'
                    ? 'success'
                    : row.eligibility === 'excluded'
                      ? 'info'
                      : 'warning'
                "
                >{{ eligibilityNames[row.eligibility] }}</el-tag
              ></template
            ></el-table-column
          >
          <el-table-column label="处理状态" width="120"
            ><template #default="{ row }">{{
              statusNames[row.status]
            }}</template></el-table-column
          >
          <el-table-column label="发布时间" width="175"
            ><template #default="{ row }">{{
              time(row.published_at)
            }}</template></el-table-column
          >
        </el-table>
        <el-pagination
          v-model:current-page="filters.page"
          :page-size="filters.page_size"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="perform(loadLeads)"
        />
      </section>
      <section v-else class="panel">
        <div class="panel-heading">
          <div>
            <h2>完整日采集记录</h2>
            <p>
              已到日期起点 {{ completed }} 项，完整性范围为所选频道的可访问最新
              Feed。
            </p>
          </div>
        </div>
        <el-table :data="jobs" empty-text="还没有完整日采集记录">
          <el-table-column
            prop="channel_name"
            label="来源频道"
            min-width="260"
          />
          <el-table-column prop="day" label="北京时间自然日" width="170" />
          <el-table-column prop="posts" label="日内去重帖子" width="140" />
          <el-table-column prop="pages" label="翻页次数" width="110" />
          <el-table-column label="覆盖状态" min-width="160"
            ><template #default="{ row }"
              ><el-tag
                :type="
                  ['boundary_reached', 'api_end'].includes(row.coverage)
                    ? 'success'
                    : 'warning'
                "
                >{{ coverageNames[row.coverage] || row.coverage }}</el-tag
              ></template
            ></el-table-column
          >
        </el-table>
      </section>
    </main>
    <el-dialog
      v-model="dialog"
      title="核查需求与记录跟进"
      width="min(900px, 95vw)"
      destroy-on-close
    >
      <template v-if="selected">
        <h2 class="detail-title">{{ selected.title }}</h2>
        <p class="muted">
          {{ selected.university }} · {{ selected.channel }} ·
          {{ time(selected.published_at) }}
        </p>
        <p class="post-content">
          {{ selected.excerpt || "该列表记录没有文字摘要，请查看原帖图片。" }}
        </p>
        <div class="source-actions">
          <a
            v-if="selected.source_url"
            :href="selected.source_url"
            target="_blank"
            rel="noopener noreferrer"
            >打开原帖 ↗</a
          ><a
            v-if="selected.channel_url"
            :href="selected.channel_url"
            target="_blank"
            rel="noopener noreferrer"
            >查看来源频道 ↗</a
          ><span v-if="!selected.source_url" class="muted">原帖短链待补充</span>
        </div>
        <el-alert
          v-if="selected.exclusion_reason"
          :title="selected.exclusion_reason"
          type="warning"
          :closable="false"
        />
        <el-form label-position="top" class="review-form">
          <div class="form-grid">
            <el-form-item label="是否适合承接"
              ><el-select v-model="reviewForm.eligibility"
                ><el-option
                  v-for="(label, value) in eligibilityNames"
                  :key="value"
                  :label="label"
                  :value="value" /></el-select
            ></el-form-item>
            <el-form-item label="服务类别"
              ><el-select v-model="reviewForm.category"
                ><el-option
                  v-for="(label, value) in categoryNames"
                  :key="value"
                  :label="label"
                  :value="value" /></el-select
            ></el-form-item>
            <el-form-item label="跟进状态"
              ><el-select v-model="reviewForm.status"
                ><el-option
                  v-for="(label, value) in statusNames"
                  :key="value"
                  :label="label"
                  :value="value" /></el-select
            ></el-form-item>
          </div>
          <div class="form-grid">
            <el-form-item label="筛选反馈"
              ><el-select v-model="reviewForm.label"
                ><el-option label="尚不确定" value="unknown" /><el-option
                  label="有用需求"
                  value="useful" /><el-option
                  label="误报"
                  value="false_positive" /><el-option
                  label="已经解决"
                  value="resolved" /><el-option
                  label="同行广告"
                  value="ad" /><el-option
                  label="考核代做"
                  value="assessment" /></el-select
            ></el-form-item>
            <el-form-item
              v-if="reviewForm.status === 'won'"
              label="成交金额（元）"
              ><el-input-number
                v-model="money"
                :min="0"
                :max="1000000"
                :precision="2"
            /></el-form-item>
          </div>
          <el-form-item label="判断依据或跟进记录（必填）"
            ><el-input
              v-model="reviewForm.note"
              type="textarea"
              :rows="3"
              :maxlength="1000"
              show-word-limit
              placeholder="记录具体用途、截止时间、是否已解决，以及人工跟进结果。"
          /></el-form-item>
        </el-form>
        <div v-if="selected.feedback?.length" class="history">
          <h3>审核历史</h3>
          <div v-for="(entry, index) in selected.feedback" :key="index">
            <small>{{ time(entry.created_at) }} · {{ entry.actor }}</small>
            <p>{{ entry.note }}</p>
          </div>
        </div>
      </template>
      <template #footer
        ><el-button @click="dialog = false">取消</el-button
        ><el-button type="primary" :loading="busy" @click="saveReview"
          >保存审核与跟进</el-button
        ></template
      >
    </el-dialog>
  </div>
</template>
