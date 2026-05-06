'use client'

import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { Button, type ButtonProps } from '@/components/ui/button'

interface CopyButtonProps extends Omit<ButtonProps, 'onClick'> {
  text: string
  label?: string
  copiedLabel?: string
}

export function CopyButton({
  text,
  label = 'Copy',
  copiedLabel = 'Copied',
  variant = 'outline',
  size = 'sm',
  ...rest
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard write can fail under permissions; degrade silently.
    }
  }

  return (
    <Button onClick={handleCopy} variant={variant} size={size} {...rest}>
      {copied ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
      <span>{copied ? copiedLabel : label}</span>
    </Button>
  )
}
