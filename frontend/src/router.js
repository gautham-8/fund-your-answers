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
      { path: 'students', component: () => import('./views/CourseRoster.vue'), meta: { role: 'instructor' } },
      { path: 'roster', redirect: (to) => `/courses/${to.params.id}/students` }, // old link
      { path: 'insights', component: () => import('./views/CourseInsights.vue'), meta: { role: 'instructor' } },
      { path: 'accommodations', component: () => import('./views/CourseAccommodations.vue'), meta: { role: 'instructor' } },
    ],
  },
  { path: '/assignments/:id', component: () => import('./views/AssignmentView.vue'), props: true },
  { path: '/submissions/:id/pages', component: () => import('./views/PagesView.vue'), props: true, meta: { role: 'student' } },
  // Both roles: instructors grade, students see their marked pages. `remount` so "Next student" loads fresh.
  { path: '/submissions/:id/grade', component: () => import('./views/GradeView.vue'), props: true, meta: { wide: true, remount: true } },
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

// After a deploy, lazily loaded pages from the old build no longer exist, so clicking a link would do nothing.
// Load the new build by doing a full page load of where the user was going (once, so it can't loop).
const reloaded = {
  get: () => { try { return sessionStorage.getItem('viva_reloaded') } catch { return null } },
  set: (v) => { try { v ? sessionStorage.setItem('viva_reloaded', v) : sessionStorage.removeItem('viva_reloaded') } catch {} },
}
router.onError((err, to) => {
  const stale = /dynamically imported module|Importing a module script failed|error loading dynamically/i.test(err?.message || '')
  if (stale && reloaded.get() !== to.fullPath) {
    reloaded.set(to.fullPath)
    location.assign(to.fullPath)
  }
})
router.afterEach(() => reloaded.set(null))

export default router
