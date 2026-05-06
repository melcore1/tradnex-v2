'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { authApi } from '@/lib/api/auth'
import { ApiError } from '@/lib/api/client'
import { toast } from '@/components/ui/sonner'

const loginSchema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
})

type LoginValues = z.infer<typeof loginSchema>

export default function LoginPage() {
  const router = useRouter()
  const [submitting, setSubmitting] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
  })

  const onSubmit = async (values: LoginValues) => {
    setSubmitting(true)
    try {
      await authApi.login(values)
      toast.success('Welcome back')
      router.push('/')
      router.refresh()
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 429) {
          toast.error('Too many attempts. Try again later.')
        } else if (err.status === 401) {
          toast.error('Invalid credentials')
        } else {
          toast.error(`Login failed (${err.status})`)
        }
      } else {
        toast.error('Could not reach the server')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-12">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>TradNex</CardTitle>
          <CardDescription>Sign in to continue</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" {...register('email')} />
              {errors.email ? <span className="text-xs text-destructive">{errors.email.message}</span> : null}
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" autoComplete="current-password" {...register('password')} />
              {errors.password ? <span className="text-xs text-destructive">{errors.password.message}</span> : null}
            </div>
            <Button type="submit" disabled={submitting} className="mt-2">
              {submitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
