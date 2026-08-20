// Based on the Pydantic model in the backend

export interface Task {
  id: number;
  task_name: string;
  task_type: 'keyword' | 'item_id' | 'store';
  enabled: boolean;
  keyword: string | null;
  item_id_list: string[];
  store_id: string | null;
  store_name: string | null;
  max_pages: number;
  personal_only: boolean;
  min_price: string | null;
  max_price: string | null;
  cron: string | null;
  next_run_at?: string | null;
  account_state_file?: string | null;
  account_strategy: 'auto' | 'fixed' | 'rotate';
  free_shipping?: boolean;
  new_publish_option?: string | null;
  region?: string | null;
  keyword_rules: string[];
  is_running: boolean;
  is_queued: boolean;
  is_paused: boolean;
}

export interface TaskCreateResponse {
  message: string;
  task: Task;
}

// For PATCH requests, all fields are optional
export type TaskUpdate = Partial<Omit<Task, 'id' | 'next_run_at' | 'is_queued'>>;

// For task creation
export interface TaskCreateRequest {
  task_name: string;
  task_type?: 'keyword' | 'item_id' | 'store';
  keyword?: string | null;
  item_id_list?: string[];
  store_id?: string | null;
  store_name?: string | null;
  personal_only?: boolean;
  min_price?: string | null;
  max_price?: string | null;
  max_pages?: number;
  cron?: string | null;
  account_state_file?: string | null;
  account_strategy?: 'auto' | 'fixed' | 'rotate';
  free_shipping?: boolean;
  new_publish_option?: string | null;
  region?: string | null;
  keyword_rules?: string[];
}
