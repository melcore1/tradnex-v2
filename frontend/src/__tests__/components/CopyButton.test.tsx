import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CopyButton } from '@/components/shared/CopyButton'

describe('CopyButton', () => {
  it('writes to clipboard on click', async () => {
    const writeSpy = vi.spyOn(navigator.clipboard, 'writeText')
    render(<CopyButton text="hello" />)
    await userEvent.click(screen.getByRole('button'))
    expect(writeSpy).toHaveBeenCalledWith('hello')
  })

  it('immediately shows the copied label after click', async () => {
    render(<CopyButton text="x" label="Copy" copiedLabel="Done" />)
    await userEvent.click(screen.getByRole('button'))
    // The setTimeout(2000) reset isn't relevant — what matters is the
    // user gets immediate visible feedback that the click landed.
    expect(await screen.findByText('Done')).toBeInTheDocument()
  })
})
