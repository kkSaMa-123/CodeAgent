import { createRouter, createWebHistory } from 'vue-router'

const EmptyRoute = { template: '<span />' }

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/projects' },
    { path: '/projects', component: EmptyRoute },
    { path: '/projects/:projectId', component: EmptyRoute },
    { path: '/projects/:projectId/conversations/:conversationId', component: EmptyRoute },
    { path: '/:pathMatch(.*)*', redirect: '/projects' },
  ],
})
