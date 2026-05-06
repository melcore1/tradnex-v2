import { apiFetch } from './client'

export type PromptTemplateName = 'entry_evaluation' | 'exit_evaluation'

export interface PromptVersionResponse {
  id: number
  template_name: string
  version_number: number
  template_text: string
  response_schema: Record<string, unknown>
  status: string
  created_ts: string
  created_by: string
  activated_ts: string | null
  deprecated_ts: string | null
  notes: string | null
}

export interface PromptCreateRequest {
  template_name: PromptTemplateName
  template_text: string
  response_schema: Record<string, unknown>
  notes?: string
}

export interface PromptActivateRequest {
  version_id: number
}

export const promptsApi = {
  active: (template: PromptTemplateName) =>
    apiFetch<PromptVersionResponse>(`/api/prompts/${template}/active`),
  history: (template: PromptTemplateName) =>
    apiFetch<PromptVersionResponse[]>(`/api/prompts/${template}/history`),
  create: (req: PromptCreateRequest) =>
    apiFetch<PromptVersionResponse>('/api/prompts', { method: 'POST', body: req }),
  activate: (req: PromptActivateRequest) =>
    apiFetch<PromptVersionResponse>('/api/prompts/activate', { method: 'POST', body: req }),
  rollback: (template: PromptTemplateName, version_number: number) =>
    apiFetch<PromptVersionResponse>(
      `/api/prompts/${template}/rollback/${version_number}`,
      { method: 'POST' },
    ),
}
