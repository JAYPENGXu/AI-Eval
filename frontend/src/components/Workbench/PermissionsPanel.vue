<template>
  <section v-if="active" class="permissions-workbench">
    <div class="permission-heading">
      <div><h2>组织与权限</h2><p>{{ organization?.name || '未选择组织' }} · RBAC + ABAC</p></div>
      <el-button :loading="loading" @click="loadAll">刷新</el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <div v-if="!organization" class="empty-organization">
      <el-empty description="尚未加入组织" />
      <div class="toolbar-form"><el-input v-model="organizationName" placeholder="组织名称" /><el-button type="primary" @click="$emit('create-organization', organizationName)">创建组织</el-button></div>
    </div>
    <el-tabs v-else v-model="tab">
      <el-tab-pane label="组织" name="organization">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="名称">{{ organization.name }}</el-descriptions-item>
          <el-descriptions-item label="标识">{{ organization.slug }}</el-descriptions-item>
          <el-descriptions-item label="我的角色">{{ membership?.roles?.join(' / ') || '-' }}</el-descriptions-item>
          <el-descriptions-item label="密级">{{ membership?.clearance || '-' }}</el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>

      <el-tab-pane label="成员" name="members">
        <div v-if="can('manage_members')" class="toolbar-form">
          <el-input v-model="memberForm.username" placeholder="用户名" />
          <el-input v-model="memberForm.department" placeholder="部门" />
          <el-select v-model="memberForm.clearance"><el-option v-for="item in classifications" :key="item" :label="item" :value="item" /></el-select>
          <el-select v-model="memberForm.roles" multiple placeholder="角色"><el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" /></el-select>
          <el-button type="primary" @click="addMember">添加成员</el-button>
        </div>
        <el-table :data="members" size="small">
          <el-table-column prop="user_name" label="用户" />
          <el-table-column prop="department" label="部门" />
          <el-table-column prop="clearance" label="Clearance" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="角色"><template #default="{ row }">{{ roleNames(row.roles) }}</template></el-table-column>
          <el-table-column v-if="can('manage_members')" label="操作" width="150"><template #default="{ row }"><el-button text @click="toggleMember(row)">{{ row.status === 'active' ? '停用' : '启用' }}</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="角色" name="roles">
        <div v-if="can('manage_roles')" class="toolbar-form role-form">
          <el-input v-model="roleForm.name" placeholder="角色名称" />
          <el-input v-model="roleForm.slug" placeholder="role_slug" />
          <el-select v-model="roleForm.capabilities" multiple collapse-tags placeholder="Capabilities"><el-option v-for="item in capabilities" :key="item" :label="item" :value="item" /></el-select>
          <el-button type="primary" @click="addRole">创建角色</el-button>
        </div>
        <el-table :data="roles" size="small"><el-table-column prop="name" label="角色" /><el-table-column prop="slug" label="Slug" /><el-table-column label="能力"><template #default="{ row }"><el-tag v-for="item in row.capabilities" :key="item" size="small">{{ item }}</el-tag></template></el-table-column><el-table-column prop="is_system" label="内置" width="80" /></el-table>
      </el-tab-pane>

      <el-tab-pane label="访问策略" name="policies">
        <div v-if="can('manage_policies')" class="policy-editor">
          <el-input v-model="policyForm.name" placeholder="策略名称" />
          <el-select v-model="policyForm.classification"><el-option v-for="item in classifications" :key="item" :label="item" :value="item" /></el-select>
          <el-segmented v-model="policyForm.visibility" :options="['organization', 'restricted']" />
          <el-select v-model="policyForm.allowed_roles" multiple placeholder="允许角色"><el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" /></el-select>
          <el-input v-model="policyForm.departmentsText" placeholder="允许部门，逗号分隔" />
          <el-button type="primary" @click="addPolicy">创建策略</el-button>
        </div>
        <el-table :data="policies" size="small"><el-table-column prop="name" label="策略" /><el-table-column prop="classification" label="密级" /><el-table-column prop="visibility" label="范围" /><el-table-column prop="version" label="版本" width="70" /><el-table-column label="授权角色"><template #default="{ row }">{{ roleNames(row.allowed_roles) }}</template></el-table-column><el-table-column prop="is_active" label="启用" width="70" /></el-table>
      </el-tab-pane>

      <el-tab-pane label="资源授权" name="resources">
        <el-empty v-if="!selectedKb" description="请选择知识库" />
        <template v-else>
          <div class="resource-band">
            <h3>KnowledgeBase · {{ selectedKb.name }}</h3>
            <el-segmented v-model="resourceForm.kbVisibility" :options="['private','organization','restricted']" />
            <el-select v-model="resourceForm.kbPolicy" placeholder="KB Policy"><el-option v-for="policy in policies" :key="policy.id" :label="`${policy.name} · ${policy.classification}`" :value="policy.id" /></el-select>
            <el-button v-if="can('manage_knowledge_bases')" type="primary" @click="saveKbPolicy">保存 KB 授权</el-button>
          </div>
          <div v-if="selectedDocument" class="resource-band">
            <h3>Document · {{ selectedDocument.filename }}</h3>
            <el-select v-model="resourceForm.documentPolicy" placeholder="Document Policy"><el-option v-for="policy in policies" :key="policy.id" :label="`${policy.name} · ${policy.classification}`" :value="policy.id" /></el-select>
            <el-switch v-model="resourceForm.documentInherits" active-text="继承 KB Policy" />
            <el-button v-if="can('manage_documents')" type="primary" @click="saveDocumentPolicy">保存文档授权</el-button>
          </div>
          <div v-if="selectedDocument && chunks.length" class="resource-band">
            <h3>Chunk 高级覆盖</h3>
            <el-input v-model="resourceForm.chunkIdsText" placeholder="Chunk ID，逗号分隔" />
            <el-select v-model="resourceForm.chunkPolicy" placeholder="覆盖 Policy"><el-option v-for="policy in policies" :key="policy.id" :label="`${policy.name} · ${policy.classification}`" :value="policy.id" /></el-select>
            <el-button v-if="can('manage_documents')" @click="saveChunkPolicy">批量覆盖</el-button>
          </div>
        </template>
      </el-tab-pane>

      <el-tab-pane label="授权审计" name="audit">
        <el-table :data="audits" size="small"><el-table-column prop="created_at" label="时间" width="180" /><el-table-column prop="actor_name" label="操作者" /><el-table-column prop="action" label="动作" /><el-table-column prop="resource_type" label="资源" /><el-table-column label="决策" width="90"><template #default="{ row }"><el-tag :type="row.allowed ? 'success' : 'danger'">{{ row.allowed ? '允许' : '拒绝' }}</el-tag></template></el-table-column><el-table-column prop="reason" label="原因" /></el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../../api'
import { getErrorMessage } from '../../composables/polling'

const props = defineProps({ active: Boolean, organization: { type: Object, default: null }, selectedKb: { type: Object, default: null }, selectedDocument: { type: Object, default: null }, chunks: { type: Array, default: () => [] } })
const emit = defineEmits(['create-organization'])
const organizationName = ref('')
const tab = ref('organization'); const loading = ref(false); const error = ref('')
const members = ref([]); const roles = ref([]); const policies = ref([]); const audits = ref([])
const classifications = ['public', 'internal', 'confidential', 'restricted']
const capabilities = ['manage_organization','manage_members','manage_roles','manage_knowledge_bases','manage_documents','manage_policies','query','view_traces','run_evaluations','use_agent']
const membership = computed(() => props.organization?.membership)
const memberForm = reactive({ username: '', department: '', clearance: 'internal', roles: [] })
const roleForm = reactive({ name: '', slug: '', capabilities: [] })
const policyForm = reactive({ name: '', classification: 'internal', visibility: 'organization', allowed_roles: [], departmentsText: '' })
const resourceForm = reactive({ kbVisibility: 'private', kbPolicy: null, documentPolicy: null, documentInherits: true, chunkIdsText: '', chunkPolicy: null })
const can = (capability) => membership.value?.capabilities?.includes(capability)
const roleNames = (ids = []) => ids.map((id) => roles.value.find((role) => role.id === id)?.name || `#${id}`).join(' / ') || '-'
async function loadAll() { if (!props.organization) return; loading.value = true; error.value = ''; try { const id = props.organization.id; const jobs = []; if (can('manage_members')) jobs.push(api.listMemberships(id).then(v => { members.value = v })); if (can('manage_roles')) jobs.push(api.listRoles(id).then(v => { roles.value = v })); if (can('manage_policies')) jobs.push(api.listPolicies(id).then(v => { policies.value = v })); if (can('view_traces') || can('manage_organization')) jobs.push(api.listAuthorizationAuditLogs(id).then(v => { audits.value = v })); await Promise.all(jobs) } catch (err) { error.value = getErrorMessage(err) } finally { loading.value = false } }
async function addMember() { await api.createMembership(props.organization.id, memberForm); memberForm.username=''; memberForm.department=''; memberForm.roles=[]; await loadAll() }
async function toggleMember(row) { await api.updateMembership(props.organization.id, row.id, { status: row.status === 'active' ? 'suspended' : 'active' }); await loadAll() }
async function addRole() { await api.createRole(props.organization.id, roleForm); roleForm.name=''; roleForm.slug=''; roleForm.capabilities=[]; await loadAll() }
async function saveKbPolicy() { if (!props.selectedKb) return; await api.updateKb(props.selectedKb.id, { visibility: resourceForm.kbVisibility, access_policy: resourceForm.kbPolicy }); await loadAll() }
async function saveDocumentPolicy() { if (!props.selectedDocument || !resourceForm.documentPolicy) return; await api.setDocumentPolicy(props.selectedDocument.id, resourceForm.documentPolicy, resourceForm.documentInherits); await loadAll() }
async function saveChunkPolicy() { const ids = resourceForm.chunkIdsText.split(',').map(Number).filter(Number.isInteger); if (!ids.length || !resourceForm.chunkPolicy) return; await api.bulkSetChunkPolicy(ids, resourceForm.chunkPolicy); resourceForm.chunkIdsText=''; await loadAll() }
async function addPolicy() { await api.createPolicy({ organization: props.organization.id, name: policyForm.name, classification: policyForm.classification, visibility: policyForm.visibility, allowed_roles: policyForm.allowed_roles, allowed_departments: policyForm.departmentsText.split(',').map(v=>v.trim()).filter(Boolean), allowed_users: [], denied_users: [], is_active: true }); policyForm.name=''; policyForm.allowed_roles=[]; policyForm.departmentsText=''; await loadAll() }
watch(() => [props.active, props.organization?.id, props.selectedKb?.id, props.selectedDocument?.id], ([active]) => {
  resourceForm.kbVisibility = props.selectedKb?.visibility || 'private'; resourceForm.kbPolicy = props.selectedKb?.access_policy || null
  resourceForm.documentPolicy = props.selectedDocument?.access_policy || null; resourceForm.documentInherits = props.selectedDocument?.inherits_policy ?? true
  if (active) loadAll()
}, { immediate: true })
</script>

<style scoped>
.permissions-workbench { padding: 4px 2px 20px; }
.permission-heading { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }
.permission-heading h2 { margin:0; font-size:18px; letter-spacing:0; }
.permission-heading p { margin:4px 0 0; color:#6b7280; }
.toolbar-form,.policy-editor { display:grid; grid-template-columns:repeat(4,minmax(120px,1fr)) auto; gap:8px; margin-bottom:14px; }
.role-form { grid-template-columns:180px 180px 1fr auto; }
.policy-editor { grid-template-columns:180px 150px 250px 1fr 1fr auto; }
.el-tag { margin:2px 4px 2px 0; }
.resource-band { display:grid; grid-template-columns:minmax(220px,1fr) minmax(200px,1fr) minmax(220px,1fr) auto; gap:10px; align-items:center; padding:14px 0; border-bottom:1px solid #e5e7eb; }
.resource-band h3 { margin:0; font-size:14px; letter-spacing:0; }
@media (max-width: 1100px) { .toolbar-form,.policy-editor,.role-form { grid-template-columns:1fr 1fr; } }
</style>
