export interface Organization {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  is_active: boolean;
  code_parser_base_url: string | null;
  code_parser_org_id: string | null;
  code_parser_repo_id: string | null;
  metrics_explorer_base_url: string | null;
  metrics_explorer_org_id: string | null;
  logs_explorer_base_url: string | null;
  logs_explorer_org_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrganizationCreate {
  name: string;
  slug: string;
  description?: string;
  code_parser_base_url?: string;
  code_parser_org_id?: string;
  code_parser_repo_id?: string;
  metrics_explorer_base_url?: string;
  metrics_explorer_org_id?: string;
  logs_explorer_base_url?: string;
  logs_explorer_org_id?: string;
}

export interface Conversation {
  id: string;
  organization_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  context: UserContext | Record<string, unknown> | null;
  tool_name: string | null;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  organization_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
}

export interface UserContext {
  service?: string;
  environment?: string;
  file_path?: string;
}

// --- Debug / Trace types ---

export interface ToolStep {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  toolNumber: number;
  aiCall: number;
  status: 'running' | 'done' | 'error';
  resultPreview?: string;
  resultLength?: number;
  durationMs?: number;
}

export interface AgentStats {
  ai_calls: number;
  max_ai_calls: number;
  tool_calls: number;
  elapsed_seconds: number;
  estimated_tokens: number;
  max_tokens: number;
  final?: boolean;
}

export interface DebugTrace {
  conversation_id: string;
  title: string;
  created_at: string;
  trace: DebugTraceEntry[];
  summary: {
    total_messages: number;
    user_messages: number;
    assistant_messages: number;
    tool_calls: number;
    tool_responses: number;
  };
}

export interface DebugTraceEntry {
  type: 'user_message' | 'tool_call' | 'tool_response' | 'assistant_response';
  timestamp: string;
  content?: string;
  context?: Record<string, unknown> | null;
  tool?: string;
  tool_call_id?: string;
  arguments?: Record<string, unknown> | null;
}
