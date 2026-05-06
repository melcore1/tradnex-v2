import { describe, it, expect } from 'vitest'
import { fmtMoney, fmtPct, fmtNumber } from '@/lib/format/decimal'

describe('fmtMoney', () => {
  it('formats numbers and decimal-strings', () => {
    expect(fmtMoney(0)).toBe('$0.00')
    expect(fmtMoney('1234.5')).toBe('$1,234.50')
    expect(fmtMoney(null)).toBe('—')
  })

  it('adds + sign when withSign and value > 0', () => {
    expect(fmtMoney(1, { withSign: true })).toBe('+$1.00')
    expect(fmtMoney(-1, { withSign: true })).toBe('$-1.00')
  })
})

describe('fmtPct', () => {
  it('multiplies by 100 and formats', () => {
    expect(fmtPct(0.123)).toBe('12.30%')
    expect(fmtPct('0.5', { withSign: true })).toBe('+50.00%')
  })
})

describe('fmtNumber', () => {
  it('formats numbers with locale separators', () => {
    expect(fmtNumber(1234.5, 2)).toBe('1,234.50')
    expect(fmtNumber(null)).toBe('—')
  })
})
