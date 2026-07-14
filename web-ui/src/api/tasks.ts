import type {
  Task,
  TaskCreateResponse,
  TaskCreateRequest,
  TaskUpdate,
} from '@/types/task.d.ts'
import { http } from '@/lib/http'

export async function getAllTasks(): Promise<Task[]> {
  return await http('/api/tasks')
}

export async function createTask(data: TaskCreateRequest): Promise<TaskCreateResponse> {
  return await http('/api/tasks/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  })
}

export async function updateTask(taskId: number, data: TaskUpdate): Promise<Task> {
  const result = await http(`/api/tasks/${taskId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  })
  return result.task
}

export async function startTask(taskId: number): Promise<void> {
  await http(`/api/tasks/start/${taskId}`, { method: 'POST' })
}

export async function stopTask(taskId: number): Promise<void> {
  await http(`/api/tasks/stop/${taskId}`, { method: 'POST' })
}

export async function deleteTask(taskId: number): Promise<void> {
  await http(`/api/tasks/${taskId}`, { method: 'DELETE' })
}


export async function pauseTask(taskId: number): Promise<void> {
  await http(`/api/tasks/pause/${taskId}`, { method: "POST" })
}

export async function resumeTask(taskId: number): Promise<void> {
  await http(`/api/tasks/resume/${taskId}`, { method: "POST" })
}
