<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps({ content: { type: String, default: '' } })
marked.setOptions({ gfm: true, breaks: true })
const html = computed(() => DOMPurify.sanitize(marked.parse(props.content), { USE_PROFILES: { html: true } }))
</script>

<template>
  <div class="markdown-body" v-html="html" />
</template>
