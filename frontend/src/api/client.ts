import type {
  Organization,
  OrganizationCreate,
  Conversation,
  ConversationDetail,
  UserContext,
  AgentStats,
  DebugTrace,
} from '../types';

const BASE = '/api/v1';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ─── Organizations ───────────────────────────────────────────────

export async function listOrganizations(): Promise<Organization[]> {
  return request('/organizations');
}

export async function createOrganization(body: OrganizationCreate): Promise<Organization> {
  return request('/organizations', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function getOrganization(orgId: string): Promise<Organization> {
  return request(`/organizations/${orgId}`);
}

export async function updateOrganization(
  orgId: string,
  body: Partial<OrganizationCreate & { is_active: boolean }>,
): Promise<Organization> {
  return request(`/organizations/${orgId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

// ─── Conversations ───────────────────────────────────────────────

export async function listConversations(orgId: string): Promise<Conversation[]> {
  return request(`/organizations/${orgId}/conversations`);
}

export async function createConversation(
  orgId: string,
  title = 'New Conversation',
): Promise<Conversation> {
  return request(`/organizations/${orgId}/conversations`, {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
}

export async function getConversation(conversationId: string): Promise<ConversationDetail> {
  return request(`/conversations/${conversationId}`);
}

export async function deleteConversation(conversationId: string): Promise<void> {
  return request(`/conversations/${conversationId}`, { method: 'DELETE' });
}

// ─── Debug ───────────────────────────────────────────────────────

export async function getConversationDebug(conversationId: string): Promise<DebugTrace> {
  return request(`/conversations/${conversationId}/debug`);
}

// ─── Messages (SSE streaming) ────────────────────────────────────

export interface ToolStartEvent {
  tool: string;
  args: Record<string, unknown>;
  id: string;
  tool_number: number;
  ai_call: number;
}

export interface ToolEndEvent {
  tool: string;
  result_preview: string;
  result_length: number;
  duration_ms: number;
}

export interface SendMessageOptions {
  conversationId: string;
  content: string;
  context?: UserContext;
  onToken: (text: string) => void;
  onToolStart: (data: ToolStartEvent) => void;
  onToolEnd: (data: ToolEndEvent) => void;
  onStats: (stats: AgentStats) => void;
  onDone: (fullContent: string) => void;
  onError: (error: string) => void;
}

export async function sendMessage(opts: SendMessageOptions): Promise<void> {
  const body: Record<string, unknown> = { content: opts.content };
  if (opts.context) body.context = opts.context;

  const res = await fetch(
    `${BASE}/conversations/${opts.conversationId}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    opts.onError(err.detail || `HTTP ${res.status}`);
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    opts.onError('No response stream');
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    let currentEvent = '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        const raw = line.slice(6);
        try {
          const data = JSON.parse(raw);
          switch (currentEvent) {
            case 'token':
              opts.onToken(data.content || '');
              break;
            case 'tool_start':
              opts.onToolStart(data as ToolStartEvent);
              break;
            case 'tool_end':
              opts.onToolEnd(data as ToolEndEvent);
              break;
            case 'stats':
              opts.onStats(data as AgentStats);
              break;
            case 'done':
              opts.onDone(data.content || '');
              break;
            case 'error':
              opts.onError(data.error || 'Unknown error');
              break;
          }
        } catch {
          // ignore malformed JSON
        }
        currentEvent = '';
      }
    }
  }
}
