<script setup>
import { ref } from 'vue'
const props = defineProps({ store: { type: Object, required: true }, conversations: { type: Object, required: true }, run: { type: Object, required: true } })
const path = ref('')
const adding = ref(false)
async function add() { const item = await props.store.add(path.value.trim()); if (item) { path.value = ''; adding.value = false } }
</script>

<template>
  <section class="settings-page">
    <header class="settings-header"><div><p class="kicker">Reusable workflows</p><h2>Skill 配置</h2><p>注册本地 SKILL.md，并为当前对话选择工作流。</p></div><button class="primary" type="button" @click="adding = !adding">＋ 添加本地 Skill</button></header>
    <form v-if="adding" class="skill-add" @submit.prevent="add"><label>Skill 文件夹绝对路径<input v-model="path" placeholder="/Users/name/.codeagent/skills/example" /></label><p>系统只读取目录中的 SKILL.md，不执行脚本，也不会删除原目录。</p><div><button class="secondary" type="button" @click="adding = false">取消</button><button class="primary" :disabled="!path.trim()">添加</button></div></form>
    <p v-if="store.error" class="inline-error">{{ store.error }}</p>
    <div class="skill-layout">
      <aside class="skill-list"><div v-if="!store.skills.length" class="settings-empty">还没有注册 Skill。</div><button v-for="skill in store.skills" :key="skill.id" type="button" :class="{ selected: store.selectedSkill?.id === skill.id }" @click="store.selectSkill(skill.id)"><strong>{{ skill.name }}</strong><small>{{ skill.description }}</small><span>{{ store.enabledSkills.includes(skill.id) ? '已启用' : skill.version }}</span></button></aside>
      <div v-if="store.selectedSkill" class="skill-detail">
        <div class="skill-title"><div><h3>{{ store.selectedSkill.name }}</h3><p>{{ store.selectedSkill.description }}</p></div><label>当前对话启用 <input type="checkbox" :checked="store.enabledSkills.includes(store.selectedSkill.id)" :disabled="!conversations.currentId || run.isActive" @change="store.toggleSkill(store.selectedSkill, $event.target.checked)" /></label></div>
        <dl><dt>版本</dt><dd>{{ store.selectedSkill.version }}</dd><dt>来源</dt><dd><code>{{ store.selectedSkill.path }}</code></dd><dt>必需工具</dt><dd>{{ store.selectedSkill.required_tools.join('、') || '无' }}</dd></dl>
        <h4>SKILL.md 指令</h4><pre>{{ store.selectedSkill.instructions }}</pre>
        <div class="skill-actions"><button class="secondary" type="button" @click="store.refreshSkill(store.selectedSkill.id)">刷新内容</button><button class="danger" type="button" @click="store.removeSkill(store.selectedSkill.id)">从 CodeAgent 移除</button></div>
      </div>
      <div v-else class="settings-empty">选择一个 Skill 查看详情。</div>
    </div>
  </section>
</template>
