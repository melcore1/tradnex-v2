import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
})

// jsdom/happy-dom doesn't ship clipboard by default
if (!('clipboard' in navigator)) {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
}
