export interface RegisterAccountPayload {
  admin_username: string
  admin_password: string
  username: string
  password: string
}

export interface RegisterAccountResponse {
  message: string
  user: { id: number; username: string; role: string }
  tenant: { id: string; name: string }
}

export async function registerAccount(
  payload: RegisterAccountPayload,
): Promise<RegisterAccountResponse> {
  const response = await fetch('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `HTTP error! status: ${response.status}`)
  }
  return await response.json()
}
