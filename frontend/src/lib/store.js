import { reactive } from 'vue'
import { api } from './api'

/** App-wide state: the user's classes (for the sidebar) and the class currently being viewed. */
export const store = reactive({ courses: [], loaded: false, course: null })

export async function loadCourses() {
  try {
    store.courses = await api('/api/courses')
  } finally {
    store.loaded = true
  }
}

export function setCourse(course) {
  store.course = course
}

export function resetStore() {
  store.courses = []
  store.loaded = false
  store.course = null
}
