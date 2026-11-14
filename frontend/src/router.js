import { createRouter, createWebHistory } from 'vue-router'
import { auth } from './lib/auth'

const routes = [
  { path: '/login', component: () => import('./views/LoginView.vue'), meta: { guest: true } },
  { path: '/register', component: () => import('./views/LoginView.vue'), meta: { guest: true }, props: { mode: 'register' } },
  { path: '/', component: () => import('./views/DashboardView.vue') },
  { path: '/courses/:id', component: () => import('./views/CourseView.vue'), props: true },
  { path: '/assignments/:id', component: () => import('./views/AssignmentView.vue'), props: true },
  { path: '/submissions/:id/viva', component: () => import('./views/VivaView.vue'), props: true, meta: { role: 'student' } },
  { path: '/submissions/:id/report', component: () => import('./views/ReportView.vue'), props: true, meta: { role: 'instructor' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (to.meta.guest) return auth.token ? '/' : true
  if (!auth.token) return '/login'
  if (to.meta.role && auth.user?.role !== to.meta.role) return '/'
  return true
})

export default router
