<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";

import AppPagination from "@/AppPagination.vue";
import AppFilterTags from "@/AppFilterTags.vue";
import AppListFilter from "@/AppListFilter.vue";
import AppSelect, { type SelectOption } from "@/AppSelect.vue";
import {
  addMember, createIdentity, listIdentity, listMembers, listProjectKeys, organizationTree,
  removeMember, resetUserPassword, updateIdentity, updateMember,
  type IdentityKind, type IdentityPayload, type IdentityRecord, type ProjectKeySummary,
} from "@/api/identity";
import { t } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import type { FilterGroup } from "@/types/filter";
import { listFilterFields, matchesFilterGroup } from "@/utils/listFilterFields";
import { showToast } from "@/utils/toast";

const route = useRoute();
const auth = useAuthStore();
const platformAdmin = computed(() => auth.userInfo?.roles.includes("platform_admin") ?? false);
const kind = computed(() => route.path.slice(1) as IdentityKind);
const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const settings: Record<IdentityKind, { title: string; intro: string; primary: string; columns: string[] }> = {
  users: { title: "用户管理", intro: "管理平台账户、登录状态和用户身份。", primary: "username", columns: ["username", "email", "nickname", "is_platform_admin"] },
  "user-groups": { title: "用户组", intro: "独立管理用户组及成员，不关联组织权限。", primary: "group_name", columns: ["group_name", "group_code"] },
  organizations: { title: "组织管理", intro: "构建多级组织架构，管理成员及组织归属。", primary: "name", columns: ["name", "code", "owner_user_id"] },
  projects: { title: "项目管理", intro: "管理项目及其所有 Key 共享的累计人民币预算。", primary: "name", columns: ["name", "code", "organization_id", "environment", "owner_user_id", "amount_budget"] },
};
const labels: Record<string, string> = {
  username: "用户名", email: "邮箱", nickname: "昵称", password: "初始密码",
  group_name: "用户组名称", group_code: "用户组编码", name: "名称", code: "编码",
  organization_id: "所属组织", parent_id: "上级组织", owner_user_id: "负责人",
  environment: "环境", role: "默认角色", description: "描述", status: "状态",
  amount_budget: "项目累计预算（人民币元）",
  is_platform_admin: "用户权限",
};
const columns = computed(() => settings[kind.value].columns);
const records = ref<IdentityRecord[]>([]);
const tree = ref<IdentityRecord[]>([]);
const collapsedOrgIds = ref(new Set<number>());
const users = ref<IdentityRecord[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const keyword = ref("");
const filterOrg = ref<string | number>("");
const filters = ref<FilterGroup>({ mode: "and", conditions: [] });
const loading = ref(false);
const busy = ref(false);
const editing = ref<IdentityRecord | null>(null);
const formOpen = ref(false);
const form = ref<IdentityPayload>({});
const memberTarget = ref<IdentityRecord | null>(null);
const keyTarget = ref<IdentityRecord | null>(null);
const projectKeys = ref<ProjectKeySummary[]>([]);
const keyPage = ref(1);
const keyTotal = ref(0);
const projectCost = ref(0);
const projectBudget = ref<number | null>(null);
const keysLoading = ref(false);
const members = ref<IdentityRecord[]>([]);
const addedMemberIds = ref(new Set<number>());
const memberCandidates = ref<IdentityRecord[]>([]);
const candidateFilters = ref<FilterGroup>({ mode: "and", conditions: [] });
const memberFilters = ref<FilterGroup>({ mode: "and", conditions: [] });
const visibleMembers = computed(() => members.value.filter((member) =>
  matchesFilterGroup(member as unknown as Record<string, unknown>, memberFilters.value)));
const memberQuery = ref("");
const candidatePage = ref(1);
const candidateTotal = ref(0);
const candidateLoading = ref(false);
const membersLoading = ref(false);
const memberRole = ref("member");
const passwordTarget = ref<IdentityRecord | null>(null);
const newPassword = ref("");
const confirmation = ref<{ type: "status" | "member"; item: IdentityRecord } | null>(null);
let requestId = 0;
let userRequestId = 0;
let candidateRequestId = 0;
let memberRequestId = 0;
let keyRequestId = 0;
let candidateTimer: ReturnType<typeof setTimeout> | undefined;

const orgOptions = computed(() => {
  const result: { id: number; name: string }[] = [];
  function visit(items: IdentityRecord[], depth: number) {
    for (const item of items) {
      if (item.status === 1) result.push({ id: item.id, name: `${"  ".repeat(depth)}${item.name}` });
      visit(item.children ?? [], depth + 1);
    }
  }
  visit(tree.value, 0);
  return result;
});
const orgSelectOptions = computed<SelectOption[]>(() => orgOptions.value.map((org) => ({ label: org.name, value: org.id })));
const parentSelectOptions = computed<SelectOption[]>(() => {
  const result: SelectOption[] = [{ label: t("顶级组织"), value: "" }];
  result.push(...orgOptions.value.filter((org) => org.id !== editing.value?.id && !descendantIds.value.has(org.id))
    .map((org) => ({ label: org.name, value: org.id })));
  const parentId = editing.value?.parent_id;
  if (parentId && !result.some((option) => option.value === parentId)) {
    result.push({ label: orgNames.value.get(parentId) ?? `#${parentId}`, value: parentId });
  }
  return result;
});
const ownerSelectOptions = computed<SelectOption[]>(() => [
  ...(!editing.value ? [{ label: t("默认当前管理员"), value: 0 }] : []),
  ...users.value.map((user) => ({ label: user.username ?? `#${user.id}`, value: user.id })),
  ...(editing.value?.owner_user_id && !users.value.some((user) => user.id === editing.value?.owner_user_id)
    ? [{ label: `#${editing.value.owner_user_id}`, value: editing.value.owner_user_id }] : []),
]);
const descendantIds = computed(() => {
  const ids = new Set<number>();
  if (kind.value !== "organizations" || !editing.value) return ids;
  function visit(items: IdentityRecord[], inside: boolean) {
    for (const item of items) {
      if (inside) ids.add(item.id);
      visit(item.children ?? [], inside || item.id === editing.value?.id);
    }
  }
  visit(tree.value, false);
  return ids;
});
const orgNames = computed(() => {
  const names = new Map<number, string>();
  function visit(items: IdentityRecord[]) {
    for (const item of items) {
      names.set(item.id, item.name ?? "");
      visit(item.children ?? []);
    }
  }
  visit(tree.value);
  return names;
});
const visibleRows = computed(() => {
  if (kind.value !== "organizations") return records.value.map((item) => ({ item, depth: 0 }));
  const rows: { item: IdentityRecord; depth: number }[] = [];
  const query = keyword.value.trim().toLowerCase();
  function visit(items: IdentityRecord[], depth: number): boolean {
    let hasMatch = false;
    for (const item of items) {
      const index = rows.length;
      rows.push({ item, depth });
      const matches = `${item.name ?? ""} ${item.code ?? ""}`.toLowerCase().includes(query);
      const childMatches = (!query && collapsedOrgIds.value.has(item.id))
        ? false : visit(item.children ?? [], depth + 1);
      if (query && !matches && !childMatches) rows.splice(index, 1);
      else hasMatch = true;
    }
    return hasMatch;
  }
  visit(tree.value, 0);
  return rows;
});

function toggleOrg(id: number) {
  const next = new Set(collapsedOrgIds.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  collapsedOrgIds.value = next;
}

function messageFrom(errorValue: unknown): string {
  const detail = (errorValue as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail || (errorValue instanceof Error ? errorValue.message : "操作失败，请重试");
}

function showError(reason: unknown) {
  showToast("error", t(messageFrom(reason)));
}

async function load() {
  const id = ++requestId;
  loading.value = true;
  records.value = [];
  const needsOrganizations = kind.value === "organizations" || kind.value === "projects";
  try {
    const [result, hierarchy] = await Promise.all([
      kind.value === "organizations"
        ? Promise.resolve(null)
        : listIdentity(kind.value, {
          page: page.value, page_size: pageSize.value, keyword: keyword.value.trim(),
          filters: filters.value,
          ...(filterOrg.value === "platform" ? { scope: "platform" }
            : filterOrg.value ? { organization_id: Number(filterOrg.value) } : {}),
        }),
      needsOrganizations ? organizationTree(kind.value === "organizations" ? filters.value : undefined) : Promise.resolve([]),
    ]);
    if (id !== requestId) return;
    tree.value = hierarchy;
    if (kind.value === "organizations") {
      const existing = new Set<number>();
      function collect(items: IdentityRecord[]) {
        for (const item of items) {
          existing.add(item.id);
          collect(item.children ?? []);
        }
      }
      collect(hierarchy);
      collapsedOrgIds.value = new Set([...collapsedOrgIds.value].filter((orgId) => existing.has(orgId)));
    }
    records.value = result?.items ?? [];
    total.value = result?.total ?? hierarchy.length;
  } catch (reason) {
    if (id === requestId) showError(reason);
  } finally {
    if (id === requestId) loading.value = false;
  }
}

async function searchUsers(term = "") {
  const id = ++userRequestId;
  try {
    const response = await listIdentity("users", { page_size: 100, keyword: term });
    if (id === userRequestId) users.value = response.items.filter((user) => user.status === 1);
  } catch (reason) {
    if (id === userRequestId) showError(reason);
  }
}

async function searchMemberCandidates(pageNumber = 1) {
  const id = ++candidateRequestId;
  candidateLoading.value = true;
  try {
    const result = await listIdentity("users", {
      page: pageNumber, page_size: 100, keyword: memberQuery.value.trim(), status: 1,
      filters: candidateFilters.value,
    });
    if (id !== candidateRequestId || !memberTarget.value) return;
    memberCandidates.value = pageNumber === 1 ? result.items : [...memberCandidates.value, ...result.items];
    candidatePage.value = pageNumber;
    candidateTotal.value = result.total;
  } catch (reason) {
    if (id === candidateRequestId) showError(reason);
  } finally {
    if (id === candidateRequestId) candidateLoading.value = false;
  }
}

function scheduleMemberSearch() {
  clearTimeout(candidateTimer);
  ++candidateRequestId;
  candidateLoading.value = true;
  memberCandidates.value = [];
  candidatePage.value = 1;
  candidateTotal.value = 0;
  candidateTimer = setTimeout(() => { void searchMemberCandidates(); }, 250);
}

function closeMembers() {
  clearTimeout(candidateTimer);
  ++candidateRequestId;
  ++memberRequestId;
  if (confirmation.value?.type === "member") confirmation.value = null;
  memberTarget.value = null;
  members.value = [];
  addedMemberIds.value = new Set();
  memberCandidates.value = [];
  memberQuery.value = "";
  candidateFilters.value = { mode: "and", conditions: [] };
  memberFilters.value = { mode: "and", conditions: [] };
  candidateLoading.value = false;
  membersLoading.value = false;
}

function closeKeys() {
  ++keyRequestId;
  keyTarget.value = null;
  projectKeys.value = [];
  keyPage.value = 1;
  keyTotal.value = 0;
  projectCost.value = 0;
  projectBudget.value = null;
  keysLoading.value = false;
}

async function loadKeys() {
  if (!keyTarget.value) return;
  const id = ++keyRequestId;
  const projectId = keyTarget.value.id;
  projectKeys.value = [];
  keysLoading.value = true;
  try {
    const result = await listProjectKeys(projectId, keyPage.value, DEFAULT_PAGE_SIZE);
    if (id !== keyRequestId || keyTarget.value?.id !== projectId) return;
    projectKeys.value = result.items;
    keyTotal.value = result.total;
    projectCost.value = result.project_total_cost;
    projectBudget.value = result.project_amount_budget;
  } catch (reason) {
    if (id === keyRequestId) showError(reason);
  } finally {
    if (id === keyRequestId) keysLoading.value = false;
  }
}

function openKeys(item: IdentityRecord) {
  closeKeys();
  keyTarget.value = item;
  projectBudget.value = item.amount_budget ?? null;
  void loadKeys();
}

function money(value: number): string {
  return `¥${Number(value).toFixed(2)}`;
}

function openForm(item: IdentityRecord | null = null, parentId?: number) {
  editing.value = item;
  form.value = item
    ? {
      ...(kind.value === "users"
        ? { email: item.email ?? "", nickname: item.nickname ?? "", is_platform_admin: item.is_platform_admin ?? 0 }
        : {}),
      ...(kind.value === "user-groups" ? { group_name: item.group_name ?? "" } : {}),
      ...(kind.value === "organizations" ? { name: item.name ?? "", parent_id: item.parent_id ?? "" } : {}),
      ...(kind.value === "projects" ? {
        name: item.name ?? "", environment: item.environment ?? "dev",
        owner_user_id: item.owner_user_id ?? "", amount_budget: item.amount_budget ?? null,
      } : {}),
      description: item.description ?? "",
      status: item.status,
    }
    : {
      status: 1,
      ...(kind.value === "users" ? { is_platform_admin: 0 } : {}),
      ...(kind.value === "organizations" ? { parent_id: parentId ?? "" } : {}),
      ...(kind.value === "projects" ? { organization_id: "", environment: "dev", owner_user_id: 0, amount_budget: null } : {}),
    };
  formOpen.value = true;
  if (kind.value === "projects") void searchUsers();
}

const fields = computed(() => {
  if (kind.value === "users") return editing.value
    ? ["email", "nickname", "is_platform_admin", "status"]
    : ["username", "email", "nickname", "password", "is_platform_admin", "status"];
  if (kind.value === "user-groups") return editing.value
    ? ["group_name", "description", "status"]
    : ["group_name", "group_code", "description", "status"];
  if (kind.value === "organizations") return editing.value
    ? ["name", "parent_id", "description", "status"]
    : ["name", "code", "parent_id", "description", "status"];
  return editing.value
    ? ["name", "environment", "owner_user_id", "amount_budget", "description", "status"]
    : ["organization_id", "name", "code", "environment", "owner_user_id", "amount_budget", "description", "status"];
});
const requiredFields = computed(() => {
  if (kind.value === "users") return editing.value ? ["email"] : ["username", "email", "password"];
  if (kind.value === "user-groups") return ["group_name"];
  if (kind.value === "organizations") return ["name"];
  return editing.value ? ["name", "owner_user_id"] : ["name"];
});

async function submitForm() {
  if (kind.value === "projects" && editing.value && !form.value.owner_user_id) {
    showToast("error", t("请选择负责人"));
    return;
  }
  busy.value = true;
  try {
    const payload = Object.fromEntries(
      fields.value
        .filter((field) => form.value[field] !== undefined)
        .map((field) => [field, form.value[field]]),
    ) as IdentityPayload;
    if (kind.value === "organizations" && payload.parent_id === "") payload.parent_id = null;
    if (kind.value === "projects" && !editing.value && payload.organization_id === "") {
      delete payload.organization_id;
    }
    if (kind.value === "projects" && payload.amount_budget === "") payload.amount_budget = null;
    for (const key of ["organization_id", "owner_user_id", "parent_id"]) {
      if (payload[key] !== undefined && payload[key] !== null && payload[key] !== "") {
        payload[key] = Number(payload[key]);
      }
    }
    if (!editing.value && kind.value === "projects" && !payload.owner_user_id) delete payload.owner_user_id;
    if (editing.value && kind.value === "projects" && payload.owner_user_id === editing.value.owner_user_id) {
      delete payload.owner_user_id;
    }
    if (editing.value && kind.value === "organizations" && payload.parent_id === editing.value.parent_id) {
      delete payload.parent_id;
    }
    if (editing.value) await updateIdentity(kind.value, editing.value.id, payload);
    else await createIdentity(kind.value, payload);
    if (kind.value === "users" && editing.value?.id === auth.userInfo?.id) {
      await auth.fetchMe();
    }
    formOpen.value = false;
    showToast("success", t(editing.value ? "已保存更改" : "创建成功"));
    await load();
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}

async function confirmAction() {
  const pending = confirmation.value;
  if (!pending) return;
  busy.value = true;
  try {
    if (pending.type === "status") {
      await updateIdentity(kind.value, pending.item.id, { status: pending.item.status === 1 ? 0 : 1 });
      showToast("success", t("状态已更新"));
      await load();
    } else if (memberTarget.value) {
      await removeMember(kind.value, memberTarget.value.id, pending.item.id);
      addedMemberIds.value = new Set([...addedMemberIds.value].filter((id) => id !== pending.item.id));
      members.value = members.value.filter((member) => member.id !== pending.item.id);
      showToast("success", t("成员已移除"));
      await refreshMembers();
    }
    confirmation.value = null;
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}

async function openMembers(item: IdentityRecord) {
  closeMembers();
  memberTarget.value = item;
  memberRole.value = kind.value === "projects" ? "developer" : "member";
  await Promise.all([refreshMembers(), searchMemberCandidates()]);
}

async function refreshMembers() {
  if (!memberTarget.value) return;
  const id = ++memberRequestId;
  const targetId = memberTarget.value.id;
  membersLoading.value = true;
  try {
    const result = await listMembers(kind.value, targetId);
    if (id === memberRequestId && memberTarget.value?.id === targetId) members.value = result;
  } catch (reason) {
    if (id === memberRequestId) showError(reason);
  } finally {
    if (id === memberRequestId) membersLoading.value = false;
  }
}

async function submitMember(user: IdentityRecord) {
  if (!memberTarget.value || busy.value || membersLoading.value || memberIds.value.has(user.id)) return;
  const targetId = memberTarget.value.id;
  const targetKind = kind.value;
  busy.value = true;
  try {
    await addMember(targetKind, targetId, user.id,
      targetKind === "user-groups" ? undefined : memberRole.value);
    if (memberTarget.value?.id === targetId && kind.value === targetKind) {
      addedMemberIds.value = new Set([...addedMemberIds.value, user.id]);
    }
    showToast("success", t("成员已添加"));
    if (memberTarget.value?.id === targetId && kind.value === targetKind) await refreshMembers();
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}

async function changeMemberRole(member: IdentityRecord, role: string) {
  if (!memberTarget.value) return;
  busy.value = true;
  try {
    await updateMember(kind.value, memberTarget.value.id, member.id, role);
    showToast("success", t("角色已更新"));
    await refreshMembers();
  } catch (reason) {
    await refreshMembers();
    showError(reason);
  } finally {
    busy.value = false;
  }
}

async function submitPassword() {
  if (!passwordTarget.value) return;
  busy.value = true;
  try {
    await resetUserPassword(passwordTarget.value.id, newPassword.value);
    passwordTarget.value = null;
    newPassword.value = "";
    showToast("success", t("密码已重置"));
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}

function display(item: IdentityRecord, key: string): string {
  const value = item[key as keyof IdentityRecord];
  if (key === "is_platform_admin") return Number(value) === 1 ? t("平台管理员") : t("普通用户");
  if (key === "amount_budget") return value == null ? "不限" : `¥${Number(value).toFixed(2)}`;
  if (key === "organization_id" && value == null && kind.value === "projects") return t("平台级项目");
  if (key === "organization_id" || key === "parent_id") return orgNames.value.get(Number(value)) ?? "-";
  if (key === "owner_user_id") return users.value.find((user) => user.id === value)?.username ?? `#${value}`;
  if (key === "environment") return ({ dev: "开发", test: "测试", prod: "生产" } as Record<string, string>)[String(value)] ?? String(value);
  if (key === "role") return roleLabel(String(value));
  return value == null || value === "" ? "-" : String(value);
}

function roleLabel(role: string) {
  return ({ org_admin: "组织管理员", member: "成员", readonly: "只读", project_admin: "项目管理员",
    developer: "开发者", viewer: "观察者" } as Record<string, string>)[role] ?? role;
}

function reloadFirstPage() {
  if (page.value === 1) {
    void load();
    return;
  }

  page.value = 1;
}

const availableRoles = computed(() => kind.value === "projects"
  ? ["project_admin", "developer", "viewer"] : ["org_admin", "member", "readonly"]);
const roleOptions = computed<SelectOption[]>(() => availableRoles.value.map((role) => ({ label: t(roleLabel(role)), value: role })));
const memberIds = computed(() => new Set([...members.value.map((member) => member.id), ...addedMemberIds.value]));

watch(() => route.path, () => {
  ++requestId;
  closeMembers();
  closeKeys();
  collapsedOrgIds.value = new Set();
  formOpen.value = false;
  passwordTarget.value = null;
  confirmation.value = null;
  page.value = 1;
  pageSize.value = DEFAULT_PAGE_SIZE;
  keyword.value = "";
  filterOrg.value = "";
  filters.value = { mode: "and", conditions: [] };
  void load();
  if (kind.value === "organizations" || kind.value === "projects") void searchUsers();
}, { immediate: true });
watch(page, () => { void load(); });
watch(keyPage, () => { if (keyTarget.value && !keysLoading.value) void loadKeys(); });
watch(pageSize, () => { reloadFirstPage(); });
watch(filterOrg, () => { reloadFirstPage(); });
function applyFilters(value: FilterGroup) {
  filters.value = value;
  reloadFirstPage();
}
</script>

<template>
  <section class="page-stack identity-page">
    <header class="identity-hero page-card">
      <div>
        <p class="identity-eyebrow">{{ t("IDENTITY & ACCESS") }}</p>
        <h1>{{ t(settings[kind].title) }}</h1>
        <p class="page-card__description">{{ t(settings[kind].intro) }}</p>
      </div>
      <button v-if="(kind !== 'users' && kind !== 'user-groups') || platformAdmin" class="page-action identity-primary" type="button" @click="openForm()">{{ t("＋ 新建") }}{{ t(settings[kind].title) }}</button>
    </header>

    <div class="page-card identity-card">
      <div class="identity-toolbar">
        <div>
          <h2>{{ t(kind === "organizations" ? "组织架构" : "资源列表") }}</h2>
          <p>{{ t(kind === "organizations" ? "支持多级组织与下级部门" : `共 ${total} 条记录`) }}</p>
        </div>
        <AppFilterTags :fields="listFilterFields[kind]" :model-value="filters" @apply="applyFilters" />
        <div class="identity-filters">
          <input v-model="keyword" :aria-label="t('搜索')" :placeholder="t('搜索名称或编码')" @keyup.enter="reloadFirstPage()" />
          <AppSelect v-if="kind === 'projects'" v-model="filterOrg" :options="[{ label: t('全部组织'), value: '' }, { label: t('平台级项目'), value: 'platform' }, ...orgSelectOptions]" :placeholder="t('全部组织')" :aria-label="t('筛选组织')" />
          <button class="identity-btn" type="button" :disabled="loading" @click="reloadFirstPage()">{{ t("查询") }}</button>
          <button class="identity-btn" type="button" :disabled="loading" @click="load()">{{ t("刷新") }}</button>
          <AppListFilter :fields="listFilterFields[kind]" :model-value="filters" hide-tags @apply="applyFilters" />
        </div>
      </div>
      <div class="identity-scroll">
        <table class="identity-table">
          <thead><tr><th v-for="key in columns" :key="key">{{ t(labels[key]) }}</th><th>{{ t("状态") }}</th><th>{{ t("操作") }}</th></tr></thead>
          <tbody>
            <tr v-for="{ item, depth } in visibleRows" :key="item.id">
              <td v-for="key in columns" :key="key">
                <span v-if="key === settings[kind].primary" class="identity-name" :style="{ paddingLeft: `${depth * 24}px` }">
                  <template v-if="kind === 'organizations'">
                    <button v-if="item.children?.length && !keyword.trim()" class="identity-node-toggle" type="button"
                      :aria-label="t(collapsedOrgIds.has(item.id) ? '展开下级组织' : '收起下级组织')"
                      :aria-expanded="!collapsedOrgIds.has(item.id)" @click="toggleOrg(item.id)">
                      {{ collapsedOrgIds.has(item.id) ? "▸" : "▾" }}
                    </button>
                    <span v-else class="identity-node-spacer" aria-hidden="true"></span>
                  </template>
                  {{ display(item, key) }}
                </span>
                <span v-else>{{ display(item, key) }}</span>
              </td>
              <td><span class="identity-status" :class="{ 'is-off': item.status !== 1 }">{{ t(item.status === 1 ? "启用" : "停用") }}</span></td>
              <td><div class="identity-actions">
                <button v-if="(kind !== 'users' && kind !== 'user-groups') || platformAdmin" type="button" @click="openForm(item)">{{ t("编辑") }}</button>
                <button v-if="kind !== 'users' && (kind !== 'user-groups' || platformAdmin)" type="button" @click="openMembers(item)">{{ t("成员") }}</button>
                <button v-if="kind === 'projects'" type="button" @click="openKeys(item)">{{ t("查看 Key") }}</button>
                <button v-if="kind === 'organizations'" type="button" @click="openForm(null, item.id)">{{ t("新增下级") }}</button>
                <button v-if="kind === 'users' && platformAdmin" type="button" @click="passwordTarget = item; newPassword = ''">{{ t("重置密码") }}</button>
                <button v-if="(kind !== 'users' && kind !== 'user-groups') || platformAdmin" type="button" :class="{ 'is-danger': item.status === 1 }" :disabled="busy" @click="confirmation = { type: 'status', item }">{{ t(item.status === 1 ? "停用" : "启用") }}</button>
              </div></td>
            </tr>
            <tr v-if="!visibleRows.length"><td :colspan="columns.length + 2" class="identity-empty">{{ t(loading ? "正在加载数据..." : "暂无匹配记录") }}</td></tr>
          </tbody>
        </table>
      </div>
      <AppPagination
        v-if="kind !== 'organizations' && total > 0"
        v-model="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-size-options="PAGE_SIZE_OPTIONS"
        :disabled="loading"
      />
    </div>

    <div v-if="formOpen" class="app-modal-overlay" @click.self="formOpen = false">
      <form class="app-modal-panel identity-dialog" role="dialog" aria-modal="true" :aria-label="t(editing ? '编辑' : '新建') + t(settings[kind].title)" @submit.prevent="submitForm">
        <div class="identity-dialog__head"><div><p>{{ t("用户与权限") }}</p><h2>{{ t(editing ? "编辑" : "新建") }}{{ t(settings[kind].title) }}</h2></div><button type="button" aria-label="关闭" @click="formOpen = false">×</button></div>
        <div class="identity-fields">
          <label v-for="field in fields" :key="field">
            <span>{{ t(labels[field]) }}<span v-if="requiredFields.includes(field)" class="identity-required" aria-hidden="true"> *</span></span>
            <AppSelect v-if="field === 'organization_id' || field === 'parent_id'" v-model="form[field]" :options="field === 'parent_id' ? parentSelectOptions : [{ label: t('不关联组织（平台级）'), value: '' }, ...orgSelectOptions]" :placeholder="t(field === 'parent_id' ? '顶级组织' : '不关联组织（平台级）')" />
            <AppSelect v-else-if="field === 'owner_user_id'" v-model="form[field]" :options="ownerSelectOptions" :placeholder="t('请选择负责人')" />
            <AppSelect v-else-if="field === 'is_platform_admin'" v-model="form[field]" :options="[{ label: t('普通用户'), value: 0 }, { label: t('平台管理员'), value: 1 }]" />
            <AppSelect v-else-if="field === 'status'" v-model="form[field]" :options="[{ label: t('启用'), value: 1 }, { label: t('停用'), value: 0 }]" />
            <AppSelect v-else-if="field === 'environment'" v-model="form[field]" :options="[{ label: t('开发'), value: 'dev' }, { label: t('测试'), value: 'test' }, { label: t('生产'), value: 'prod' }]" />
            <textarea v-else-if="field === 'description'" v-model="form[field]" maxlength="255" rows="3" :placeholder="t('选填')" />
            <input v-else v-model.trim="form[field]" :type="field === 'amount_budget' ? 'number' : field === 'password' ? 'password' : field === 'email' ? 'email' : 'text'" :step="field === 'amount_budget' ? '0.01' : undefined" :min="field === 'amount_budget' ? '0.01' : undefined" :minlength="field === 'password' ? 8 : undefined" :maxlength="field === 'email' ? 128 : 64" :placeholder="field === 'amount_budget' ? '留空为不限' : ['group_code', 'code'].includes(field) ? t('留空自动生成') : undefined" :required="requiredFields.includes(field)" />
          </label>
        </div>
        <footer class="identity-dialog__footer"><button type="button" class="identity-btn" @click="formOpen = false">{{ t("取消") }}</button><button type="submit" class="identity-btn identity-primary" :disabled="busy">{{ t(busy ? "保存中..." : "保存") }}</button></footer>
      </form>
    </div>

    <div v-if="keyTarget" class="app-modal-overlay" @click.self="closeKeys">
      <div class="app-modal-panel identity-dialog identity-dialog--keys" role="dialog" aria-modal="true" :aria-label="`${keyTarget.name} 的 API Key`">
        <div class="identity-dialog__head">
          <div><p>{{ t("项目 API Key") }}</p><h2>{{ keyTarget.name }}</h2></div>
          <button type="button" :aria-label="t('关闭')" @click="closeKeys">×</button>
        </div>
        <p v-if="!keysLoading || projectKeys.length" class="identity-key-summary">
          {{ t("项目累计用量") }}：{{ money(projectCost) }} / {{ projectBudget == null ? t("不限额") : money(projectBudget) }}
          <span>（{{ t("所有 Key 共享，费用仅统计人民币") }}）</span>
        </p>
        <div class="identity-scroll identity-key-scroll">
          <table class="identity-table">
            <thead><tr>
              <th>{{ t("API Key") }}</th><th>{{ t("归属人") }}</th><th>{{ t("创建人") }}</th><th>{{ t("状态") }}</th>
              <th>{{ t("累计用量") }}</th><th>{{ t("周期用量 / 限额") }}</th><th>TPM / QPS</th>
            </tr></thead>
            <tbody>
              <tr v-for="key in projectKeys" :key="key.id">
                <td><strong>{{ key.name }}</strong><br /><code>{{ key.key_prefix }}…</code></td>
                <td>{{ key.owner_name ?? (key.user_id ? `#${key.user_id}` : t("未指定")) }}</td>
                <td>{{ key.creator_name ?? `#${key.created_by}` }}</td>
                <td><span class="identity-status" :class="{ 'is-off': key.status !== 1 || (key.expires_at && Date.parse(key.expires_at) <= Date.now()) }">{{ t(key.status !== 1 ? "停用" : key.expires_at && Date.parse(key.expires_at) <= Date.now() ? "已过期" : "启用") }}</span></td>
                <td>{{ key.total_tokens.toLocaleString() }} Token<br />{{ money(key.total_cost) }}</td>
                <td v-if="key.budget_period">
                  {{ t(key.budget_period === "week" ? "本周" : "本月") }}：{{ key.period_tokens.toLocaleString() }} / {{ key.token_budget?.toLocaleString() ?? t("不限") }} Token
                  <br />{{ money(key.period_cost) }} / {{ key.amount_budget == null ? t("不限额") : money(key.amount_budget) }}
                </td>
                <td v-else>{{ t("未设置周期限额") }}</td>
                <td>{{ key.tpm_limit?.toLocaleString() ?? t("不限") }} / {{ key.qps_limit ?? t("不限") }}</td>
              </tr>
              <tr v-if="!projectKeys.length"><td colspan="7" class="identity-empty">{{ t(keysLoading ? "正在加载数据..." : "暂无 Key") }}</td></tr>
            </tbody>
          </table>
        </div>
        <AppPagination v-if="keyTotal > DEFAULT_PAGE_SIZE" v-model="keyPage" :total="keyTotal" :page-size="DEFAULT_PAGE_SIZE" :disabled="keysLoading" />
        <footer class="identity-dialog__footer"><button type="button" class="identity-btn" @click="closeKeys">{{ t("关闭") }}</button></footer>
      </div>
    </div>

    <div v-if="memberTarget" class="app-modal-overlay" @click.self="closeMembers">
      <div class="app-modal-panel identity-dialog identity-dialog--wide" role="dialog" aria-modal="true" :aria-label="t('成员管理')">
        <div class="identity-dialog__head"><div><p>{{ t("成员管理") }}</p><h2>{{ display(memberTarget, settings[kind].primary) }}</h2></div><button type="button" aria-label="关闭" @click="closeMembers">×</button></div>
        <div class="identity-member-columns">
          <section class="identity-member-column">
            <div class="identity-member-column__head"><h3>{{ t("添加成员") }}</h3><span>{{ t("搜索用户并点击添加") }}</span>
              <AppListFilter :fields="listFilterFields.users" :model-value="candidateFilters" @apply="candidateFilters = $event; searchMemberCandidates(1)" />
            </div>
            <input v-model="memberQuery" class="identity-member-search" :placeholder="t('按用户名或邮箱搜索用户')" :aria-label="t('搜索可添加用户')" @input="scheduleMemberSearch" />
            <AppSelect v-if="kind !== 'user-groups'" v-model="memberRole" :options="roleOptions" :aria-label="t('新成员角色')" />
            <div class="identity-member-list">
              <div v-for="user in memberCandidates" :key="user.id" class="identity-member">
                <span class="identity-avatar">{{ (user.nickname || user.username || "?").slice(0, 1).toUpperCase() }}</span>
                <span class="identity-member__info"><strong>{{ user.nickname || user.username }}</strong><small>{{ user.email }}</small></span>
                <button type="button" class="identity-member__add" :disabled="busy || membersLoading || memberIds.has(user.id)" @click="submitMember(user)">{{ t(memberIds.has(user.id) ? "已添加" : "添加") }}</button>
              </div>
              <p v-if="candidateLoading && !memberCandidates.length" class="identity-empty">{{ t("正在加载数据...") }}</p>
              <p v-else-if="!memberCandidates.length" class="identity-empty">{{ t("暂无匹配用户") }}</p>
              <button v-if="candidatePage * 100 < candidateTotal" type="button" class="identity-member-more" :disabled="candidateLoading" @click="searchMemberCandidates(candidatePage + 1)">{{ t(candidateLoading ? "正在加载数据..." : "加载更多") }}</button>
            </div>
          </section>
          <section class="identity-member-column">
            <div class="identity-member-column__head"><h3>{{ t("当前成员") }}</h3><span>{{ visibleMembers.length }}</span>
              <AppListFilter :fields="listFilterFields.members" :model-value="memberFilters" @apply="memberFilters = $event" />
            </div>
            <div class="identity-member-list">
              <div v-for="member in visibleMembers" :key="member.id" class="identity-member">
                <span class="identity-avatar">{{ (member.nickname || member.username || "?").slice(0, 1).toUpperCase() }}</span>
                <span class="identity-member__info"><strong>{{ member.nickname || member.username }}</strong><small>{{ member.email }}</small></span>
                <AppSelect v-if="kind !== 'user-groups'" :model-value="member.role" :options="roleOptions" :disabled="busy" @change="changeMemberRole(member, String($event))" />
                <span v-else class="identity-status">{{ t("成员") }}</span>
                <button type="button" :disabled="busy" @click="confirmation = { type: 'member', item: member }">{{ t("移除") }}</button>
              </div>
              <p v-if="membersLoading && !members.length" class="identity-empty">{{ t("正在加载数据...") }}</p>
              <p v-else-if="!visibleMembers.length" class="identity-empty">{{ t("暂无匹配成员") }}</p>
            </div>
          </section>
        </div>
      </div>
    </div>

    <div v-if="passwordTarget" class="app-modal-overlay" @click.self="passwordTarget = null">
      <form class="app-modal-panel identity-dialog" role="dialog" aria-modal="true" :aria-label="t('重置密码')" @submit.prevent="submitPassword">
        <div class="identity-dialog__head"><div><p>{{ passwordTarget.username }}</p><h2>{{ t("重置密码") }}</h2></div><button type="button" aria-label="关闭" @click="passwordTarget = null">×</button></div>
        <div class="identity-fields"><label><span>{{ t("新密码（至少 8 位）") }}<span class="identity-required" aria-hidden="true"> *</span></span><input v-model="newPassword" type="password" minlength="8" maxlength="128" required autocomplete="new-password" /></label></div>
        <footer class="identity-dialog__footer"><button type="button" class="identity-btn" @click="passwordTarget = null">{{ t("取消") }}</button><button class="identity-btn identity-primary" type="submit" :disabled="busy">{{ t("确认重置") }}</button></footer>
      </form>
    </div>

    <div v-if="confirmation" class="app-modal-overlay app-modal-overlay--confirmation" @click.self="!busy && (confirmation = null)">
      <div class="app-modal-panel identity-dialog identity-dialog--confirm" role="alertdialog" aria-modal="true" :aria-label="t('确认操作')">
        <div class="identity-dialog__head"><div><p>{{ t("用户与权限") }}</p><h2>{{ t("确认操作") }}</h2></div><button type="button" aria-label="关闭" :disabled="busy" @click="confirmation = null">×</button></div>
        <p class="identity-confirm-message">{{ t(confirmation.type === "status" ? `确定${confirmation.item.status === 1 ? "停用" : "启用"}该记录吗？` : `确定移除 ${confirmation.item.username} 吗？`) }}</p>
        <footer class="identity-dialog__footer"><button type="button" class="identity-btn" :disabled="busy" @click="confirmation = null">{{ t("取消") }}</button><button type="button" class="identity-btn" :class="confirmation.type === 'member' || confirmation.item.status === 1 ? 'identity-danger' : 'identity-primary'" :disabled="busy" @click="confirmAction">{{ t("确认") }}</button></footer>
      </div>
    </div>
  </section>
</template>

<style scoped>
.identity-hero { display:flex; align-items:center; justify-content:space-between; gap:20px; background:linear-gradient(110deg,#fff 65%,#edf8f4); }
.identity-eyebrow { margin:0 0 9px; color:#178879; font-size:10px; font-weight:750; letter-spacing:.17em; }
.identity-hero h1 { margin:0 0 9px; color:#172f3a; font-size:23px; letter-spacing:-.025em; }
.identity-primary { background:#167e70!important; border-color:#167e70!important; color:#fff!important; }
.identity-primary:hover { background:#10695e!important; }
.identity-btn.identity-danger { background:#d32f2f; border-color:#d32f2f; color:#fff; }
.identity-btn.identity-danger:hover:not(:disabled) { background:#b71c1c; border-color:#b71c1c; }
.identity-card { padding:0; overflow:hidden; }
.identity-toolbar { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px; padding:22px 24px; }
.identity-toolbar h2 { margin:0 0 6px; font-size:16px; color:#213743; }
.identity-toolbar p { margin:0; color:#8a9ca8; font-size:12px; }
.identity-filters { display:flex; align-items:center; gap:8px; flex-wrap:wrap; max-width:100%; }
.identity-page input,.identity-page textarea { min-height:38px; padding:8px 11px; border:1px solid #dbe5e9; border-radius:9px; background:#fff; color:#29414d; font:inherit; font-size:12px; outline:none; }
.identity-page input:focus,.identity-page textarea:focus { border-color:#42aa98; box-shadow:0 0 0 3px #e2f5ee; }
.identity-filters input { width:205px; }
.identity-filters .app-select { width:180px; flex:0 0 180px; }
.identity-btn { min-height:38px; padding:8px 14px; border:1px solid #d6e5e3; border-radius:9px; background:#f4faf8; color:#217c70; font:inherit; font-size:12px; font-weight:650; cursor:pointer; }
.identity-btn:disabled,.identity-actions button:disabled { opacity:.5; cursor:not-allowed; }
.identity-scroll { overflow:auto; }
.identity-table { width:100%; min-width:760px; border-collapse:collapse; text-align:left; }
.identity-table th { padding:14px 20px; background:#f7f9fa; color:#798d9a; font-size:11px; font-weight:650; white-space:nowrap; }
.identity-table td { padding:16px 20px; border-top:1px solid #edf1f3; color:#435765; font-size:12px; }
.identity-table tbody tr:hover { background:#f8fcfa; }
.identity-name { display:inline-flex; align-items:center; gap:9px; color:#203b48; font-weight:680; white-space:nowrap; }
.identity-node-toggle,.identity-node-spacer { display:inline-grid; place-items:center; width:20px; height:20px; flex:none; }
.identity-node-toggle { padding:0; border:0; border-radius:5px; background:transparent; color:#298d7e; font:inherit; font-size:17px; cursor:pointer; }
.identity-node-toggle:hover { background:#e4f3ee; }
.identity-node-toggle:focus-visible { outline:2px solid #298d7e; outline-offset:2px; }
.identity-status { display:inline-flex; padding:5px 9px; border-radius:20px; background:#e8f7f0; color:#248369; font-size:11px; white-space:nowrap; }
.identity-status.is-off { background:#f4f0ee; color:#9d766a; }
.identity-actions { display:flex; gap:12px; white-space:nowrap; }
.identity-actions button,.identity-member button { padding:0; border:0; background:none; color:#188477; font:inherit; font-size:12px; cursor:pointer; }
.identity-actions button:hover:not(:disabled) { text-decoration:underline; }
.identity-actions button.is-danger { color:#d32f2f; font-weight:600; }
.identity-actions button.is-danger:hover:not(:disabled) { color:#b71c1c; }
.identity-member-column:last-child .identity-member button { color:#d32f2f; }
.identity-member button:disabled { opacity:.5; cursor:not-allowed; }
.identity-empty { padding:40px!important; color:#92a3ad!important; text-align:center; font-size:12px; }
.identity-dialog { display:flex; flex-direction:column; width:min(480px,100%); padding:30px; }
.identity-dialog--wide { width:min(920px,100%); min-height:min(520px,calc(100dvh - 32px)); }
.identity-dialog--keys { width:min(1060px,100%); }
.identity-key-summary { margin:18px 0; color:#405662; font-size:13px; }
.identity-key-summary span { color:#8a9ca8; font-size:12px; }
.identity-key-scroll { min-height:120px; }
.identity-key-scroll .identity-table { min-width:860px; }
.identity-key-scroll td { line-height:1.8; }
.identity-key-scroll code { color:#798d9a; }
.identity-dialog--confirm { width:min(420px,100%); }
.identity-confirm-message { margin:24px 0; color:#405662; font-size:13px; line-height:1.6; }
.identity-dialog__head { display:flex; justify-content:space-between; align-items:flex-start; padding-bottom:24px; border-bottom:1px solid #e9eff0; }
.identity-dialog__head p { margin:0 0 8px; color:#15907c; font-size:11px; font-weight:700; }
.identity-dialog__head h2 { margin:0; font-size:20px; color:#1e3440; }
.identity-dialog__head button { border:0; background:none; color:#768c99; font-size:26px; cursor:pointer; }
.identity-fields { display:grid; gap:20px; padding:26px 0; }
.identity-fields label { display:grid; gap:9px; color:#405662; font-size:12px; font-weight:600; }
.identity-required { color:#db5353; }
.identity-fields input,.identity-fields .app-select,.identity-fields textarea { width:100%; font-weight:400; }
.identity-dialog__footer { display:flex; justify-content:flex-end; gap:10px; margin-top:auto; padding-top:18px; border-top:1px solid #e9eff0; }
.identity-member-columns { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); min-height:0; flex:1; }
.identity-member-column { display:flex; flex-direction:column; min-width:0; padding:20px 18px 0 0; }
.identity-member-column + .identity-member-column { border-left:1px solid #e9eff0; padding-right:0; padding-left:18px; }
.identity-member-column__head { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; min-height:25px; margin-bottom:14px; }
.identity-member-column__head h3 { margin:0; color:#213743; font-size:14px; }
.identity-member-column__head span { color:#8a9ca8; font-size:11px; }
.identity-member-search { width:100%; margin-bottom:10px; }
.identity-member-column > .app-select { width:100%; margin-bottom:10px; }
.identity-member-list { min-height:0; max-height: min(380px, 48dvh); overflow-y:auto; }
.identity-member { display:flex; align-items:center; gap:9px; padding:12px 0; border-bottom:1px solid #eef1f3; }
.identity-avatar { display:grid; place-items:center; width:34px; height:34px; flex:none; border-radius:10px; background:#e4f3ee; color:#218577; font-weight:700; }
.identity-member__info { display:grid; gap:4px; flex:1; min-width:0; font-size:12px; }
.identity-member__info strong,.identity-member__info small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.identity-member__info small { color:#8b9ca7; }
.identity-member .app-select { width:110px; flex:none; }
.identity-member__add { font-weight:650!important; }
.identity-member-more { display:block; margin:14px auto; color:#188477!important; }
@media (max-width:700px) { .identity-member-columns { grid-template-columns:1fr; } .identity-member-column,.identity-member-column + .identity-member-column { padding:18px 0; border-left:0; } .identity-member-column + .identity-member-column { border-top:1px solid #e9eff0; } .identity-member-list { max-height:260px; } }
@media (max-width:600px) { .identity-hero { align-items:flex-start; flex-direction:column; } .identity-filters input { width:100%; } .identity-filters .app-select { width:100%; flex:1 1 100%; } .identity-dialog { padding:22px; } }
</style>
