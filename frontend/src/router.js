import { createRouter, createWebHistory } from 'vue-router'
import { auth } from './lib/auth'

const routes = [
  { path: '/login', component: () => import('./views/LoginView.vue'), meta: { guest: true } },
  { path: '/register', component: () => import('./views/LoginView.vue'), meta: { guest: true }, props: { mode: 'register' } },
  { path: '/', component: () => import('./views/DashboardView.vue') },
  { path: '/join/:code', component: () => import('./views/JoinView.vue'), props: true },
  {
    path: '/courses/:id',
    component: () => import('./views/CourseLayout.vue'),
    props: true,
    children: [
      { path: '', component: () => import('./views/CourseAssignments.vue') },
      { path: 'regrades', component: () => import('./views/CourseRegrades.vue') },
      { path: 'roster', component: () => import('./views/CourseRoster.vue'), meta: { role: 'instructor' } },
    ],
  },
  { path: '/assignments/:id', component: () => import('./views/AssignmentView.vue'), props: true },
  { path: '/submissions/:id/pages', component: () => import('./views/PagesView.vue'), props: true, meta: { role: 'student' } },
  { path: '/submissions/:id/viva', component: () => import('./views/VivaView.vue'), props: true, meta: { role: 'student' } },
  { path: '/submissions/:id/report', component: () => import('./views/ReportView.vue'), props: true, meta: { role: 'instructor' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: (to, from, saved) => saved || (to.path !== from.path ? { top: 0 } : undefined),
})

router.beforeEach((to) => {
  if (to.meta.guest) return auth.token ? '/' : true
  if (!auth.token) return { path: '/login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
  if (to.meta.role && auth.user?.role !== to.meta.role) return '/'
  return true
})

export default router
