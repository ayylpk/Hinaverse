import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface UserProfile {
  nickname: string
  avatar: string
}

const STORAGE_KEY = 'hina_user'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('hina_token') || '')
  const profile = ref<UserProfile>({
    nickname: '月月',
    avatar: '',
  })

  const isLoggedIn = computed(() => !!token.value)

  function login(username: string, password: string): boolean {
    if (username === 'admin' && password === '123456') {
      token.value = 'mock-token-admin'
      localStorage.setItem('hina_token', token.value)
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        try {
          profile.value = JSON.parse(saved)
        } catch {
          /* ignore */
        }
      }
      return true
    }
    return false
  }

  function logout() {
    token.value = ''
    localStorage.removeItem('hina_token')
  }

  function updateProfile(next: Partial<UserProfile>) {
    profile.value = { ...profile.value, ...next }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(profile.value))
  }

  return { token, profile, isLoggedIn, login, logout, updateProfile }
})
