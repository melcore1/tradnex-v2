import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RawJsonToggle } from '@/components/shared/RawJsonToggle'

describe('RawJsonToggle', () => {
  it('shows formatted view by default and switches to Raw JSON', async () => {
    render(<RawJsonToggle formatted={<p>FORMATTED</p>} raw={{ a: 1 }} />)
    expect(screen.getByText('FORMATTED')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /raw json/i }))
    expect(screen.getByText(/"a": 1/)).toBeInTheDocument()
  })

  it('Copy JSON copies the stringified payload', async () => {
    const writeSpy = vi.spyOn(navigator.clipboard, 'writeText')
    render(<RawJsonToggle formatted={<p>F</p>} raw={{ x: 'y' }} />)
    await userEvent.click(screen.getByRole('button', { name: /copy json/i }))
    expect(writeSpy).toHaveBeenCalledWith(JSON.stringify({ x: 'y' }, null, 2))
  })
})
