import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import './index.css'
import { applyTheme, readStoredTheme } from './lib/theme'

// 저장해 둔 테마를 첫 렌더 전에 붙여 깜빡임을 막는다
applyTheme(readStoredTheme())

const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
