import { ref } from 'vue'

type Theme = 'light' | 'dark'

const STORAGE_KEY = 'theme'

function readInitial(): Theme {
  if (typeof window === 'undefined') return 'light'
  const stored = localStorage.getItem(STORAGE_KEY) as Theme | null
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const theme = ref<Theme>(readInitial())

function apply(value: Theme) {
  const root = document.documentElement
  root.classList.toggle('dark', value === 'dark')
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {}
}

/** Global theme controller. Call toggle() anywhere; state is shared. */
export function useTheme() {
  const toggle = () => {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    apply(theme.value)
  }

  return { theme, toggle }
}
