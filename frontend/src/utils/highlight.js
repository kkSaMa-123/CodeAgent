import hljs from 'highlight.js/lib/common'

const EXTENSION_LANGUAGES = {
  c: 'c',
  cc: 'cpp',
  cpp: 'cpp',
  cxx: 'cpp',
  h: 'c',
  hpp: 'cpp',
  css: 'css',
  go: 'go',
  html: 'xml',
  java: 'java',
  js: 'javascript',
  json: 'json',
  jsx: 'javascript',
  md: 'markdown',
  py: 'python',
  rs: 'rust',
  sh: 'bash',
  sql: 'sql',
  ts: 'typescript',
  tsx: 'typescript',
  vue: 'xml',
  xml: 'xml',
  yaml: 'yaml',
  yml: 'yaml',
}

export function languageFromPath(path = '') {
  const filename = path.split('/').pop()?.toLowerCase() || ''
  if (filename === 'dockerfile') return 'dockerfile'
  if (filename === 'makefile') return 'makefile'
  const extension = filename.includes('.') ? filename.split('.').pop() : ''
  return EXTENSION_LANGUAGES[extension] || ''
}

export function highlightCode(code = '', path = '') {
  const language = languageFromPath(path)
  try {
    if (language && hljs.getLanguage(language)) {
      return hljs.highlight(code, { language, ignoreIllegals: true }).value
    }
    return hljs.highlightAuto(code).value
  } catch {
    return hljs.highlight(code, { language: 'plaintext' }).value
  }
}

export function highlightMarkdownCode(html = '') {
  const template = document.createElement('template')
  template.innerHTML = html
  for (const code of template.content.querySelectorAll('pre code')) {
    const languageClass = [...code.classList].find((name) => name.startsWith('language-'))
    const language = languageClass?.slice('language-'.length) || ''
    const source = code.textContent || ''
    try {
      code.innerHTML = language && hljs.getLanguage(language)
        ? hljs.highlight(source, { language, ignoreIllegals: true }).value
        : hljs.highlightAuto(source).value
    } catch {
      code.textContent = source
    }
    code.classList.add('hljs')
  }
  return template.innerHTML
}
