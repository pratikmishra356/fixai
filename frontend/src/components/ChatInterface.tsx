import { useState, useRef, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import type { Organization, ConversationDetail, Message, UserContext, ToolStep, AgentStats, ConversationProgress } from '../types';
import { sendMessage, type ToolStartEvent, type ToolEndEvent } from '../api/client';
import { MessageBubble } from './MessageBubble';
import { ContextForm } from './ContextForm';
import {
  Send, Loader2, SlidersHorizontal, X, ChevronDown, ChevronRight,
  Activity, Bug, Clock, Cpu, Gauge, Square,
} from 'lucide-react';

interface ChatInterfaceProps {
  conversation: ConversationDetail;
  organization: Organization;
  initialProgress?: ConversationProgress | null;
  onConversationUpdated: (conv: ConversationDetail) => void;
  onProgressUpdate?: (convId: string, progress: ConversationProgress) => void;
}

export function ChatInterface({
  conversation,
  organization,
  initialProgress,
  onConversationUpdated,
  onProgressUpdate,
}: ChatInterfaceProps) {
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(() => initialProgress?.isStreaming ?? false);
  const [streamingContent, setStreamingContent] = useState(() => initialProgress?.streamingContent ?? '');
  const [toolSteps, setToolSteps] = useState<ToolStep[]>(() => initialProgress?.toolSteps ?? []);
  const [agentStats, setAgentStats] = useState<AgentStats | null>(
    () => initialProgress?.agentStats ?? conversation.agent_stats ?? null,
  );
  const [showContext, setShowContext] = useState(false);
  const [context, setContext] = useState<UserContext>({});
  const [error, setError] = useState<string | null>(() => initialProgress?.error ?? null);
  const [showDebug, setShowDebug] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stopRef = useRef<(() => void) | null>(null);

  // --- Refs for cross-conversation progress (survive conversation switches) ---
  const currentConvIdRef = useRef(conversation.id);
  const onProgressUpdateRef = useRef(onProgressUpdate);
  onProgressUpdateRef.current = onProgressUpdate;
  const onConversationUpdatedRef = useRef(onConversationUpdated);
  onConversationUpdatedRef.current = onConversationUpdated;

  // Per-conversation progress accumulators stored in refs so stream
  // callbacks can push updates even after the user switches away.
  const streamProgressRef = useRef<Record<string, ConversationProgress>>({});

  // Mirror of local display state kept in a ref so the switch effect can
  // snapshot it without stale-closure issues.
  const currentProgressRef = useRef<ConversationProgress>({
    toolSteps: initialProgress?.toolSteps ?? [],
    streamingContent: initialProgress?.streamingContent ?? '',
    isStreaming: initialProgress?.isStreaming ?? false,
    agentStats: initialProgress?.agentStats ?? null,
    error: initialProgress?.error ?? null,
  });

  useEffect(() => {
    currentProgressRef.current = { toolSteps, streamingContent, isStreaming, agentStats, error };
  }, [toolSteps, streamingContent, isStreaming, agentStats, error]);

  const pushProgress = useCallback((convId: string, update: Partial<ConversationProgress>) => {
    const prev = streamProgressRef.current[convId] ?? {
      toolSteps: [], streamingContent: '', isStreaming: false, agentStats: null, error: null,
    };
    const merged = { ...prev, ...update };
    streamProgressRef.current[convId] = merged;
    onProgressUpdateRef.current?.(convId, { ...merged });
  }, []);

  // Handle conversation switch (component stays mounted — no key={} remount)
  useEffect(() => {
    if (currentConvIdRef.current === conversation.id) return;

    // Snapshot the state we're leaving
    pushProgress(currentConvIdRef.current, currentProgressRef.current);
    currentConvIdRef.current = conversation.id;

    // Restore: prefer ref-based accumulator (most up-to-date) then parent snapshot, then conversation from API
    const saved = streamProgressRef.current[conversation.id] ?? initialProgress;
    setIsStreaming(saved?.isStreaming ?? false);
    setStreamingContent(saved?.streamingContent ?? '');
    setToolSteps(saved?.toolSteps ?? []);
    setAgentStats(saved?.agentStats ?? conversation.agent_stats ?? null);
    setError(saved?.error ?? null);
    setInput('');
    setShowContext(false);
  }, [conversation.id, initialProgress, pushProgress]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [conversation.messages, streamingContent, toolSteps, scrollToBottom]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [conversation.id]);

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return;

    const userContent = input.trim();
    const convId = conversation.id;
    setInput('');
    setError(null);
    setIsStreaming(true);
    setStreamingContent('');
    setToolSteps([]);
    setAgentStats(null);

    // Reset ref-based progress for this stream
    streamProgressRef.current[convId] = {
      toolSteps: [],
      streamingContent: '',
      isStreaming: true,
      agentStats: null,
      error: null,
    };
    pushProgress(convId, streamProgressRef.current[convId]);

    const userMsg: Message = {
      id: crypto.randomUUID(),
      conversation_id: convId,
      role: 'user',
      content: userContent,
      context: hasContext(context) ? context : null,
      tool_name: null,
      created_at: new Date().toISOString(),
    };

    const updatedConv = {
      ...conversation,
      messages: [...conversation.messages, userMsg],
      title:
        conversation.messages.length === 0
          ? userContent.slice(0, 80) + (userContent.length > 80 ? '...' : '')
          : conversation.title,
    };
    onConversationUpdatedRef.current(updatedConv);

    let fullResponse = '';

    try {
      const { promise, stop } = sendMessage({
        conversationId: convId,
        content: userContent,
        context: hasContext(context) ? context : undefined,
        onToken: (token) => {
          fullResponse += token;
          const prev = streamProgressRef.current[convId];
          const nextContent = (prev?.streamingContent ?? '') + token;
          pushProgress(convId, { streamingContent: nextContent });
          if (currentConvIdRef.current === convId) {
            setStreamingContent(nextContent);
          }
        },
        onToolStart: (data: ToolStartEvent) => {
          const prev = streamProgressRef.current[convId];
          const newStep: ToolStep = {
            id: data.id,
            tool: data.tool,
            args: data.args,
            toolNumber: data.tool_number,
            aiCall: data.ai_call,
            status: 'running',
          };
          const nextSteps = [...(prev?.toolSteps ?? []), newStep];
          pushProgress(convId, { toolSteps: nextSteps });
          if (currentConvIdRef.current === convId) {
            setToolSteps(nextSteps);
          }
        },
        onToolEnd: (data: ToolEndEvent) => {
          const prev = streamProgressRef.current[convId];
          const steps = [...(prev?.toolSteps ?? [])];
          const running = steps.findIndex((t) => t.status === 'running');
          if (running >= 0) {
            steps[running] = {
              ...steps[running],
              status: 'done',
              resultPreview: data.result_preview,
              resultLength: data.result_length,
              durationMs: data.duration_ms,
            };
          }
          pushProgress(convId, { toolSteps: steps });
          if (currentConvIdRef.current === convId) {
            setToolSteps(steps);
          }
        },
        onStats: (stats: AgentStats) => {
          pushProgress(convId, { agentStats: stats });
          if (currentConvIdRef.current === convId) {
            setAgentStats(stats);
          }
        },
        onDone: (content) => {
          fullResponse = content || fullResponse;
          const assistantMsg: Message = {
            id: crypto.randomUUID(),
            conversation_id: convId,
            role: 'assistant',
            content: fullResponse,
            context: null,
            tool_name: null,
            created_at: new Date().toISOString(),
          };
          // Always update sidebar + conditionally update activeConversation
          onConversationUpdatedRef.current({
            ...updatedConv,
            messages: [...updatedConv.messages, assistantMsg],
          });
          // Clear streaming state but keep agentStats and toolSteps so they persist after answer
          pushProgress(convId, {
            isStreaming: false,
            streamingContent: '',
          });
          if (currentConvIdRef.current === convId) {
            setIsStreaming(false);
            setStreamingContent('');
          }
        },
        onError: (err) => {
          pushProgress(convId, { error: err, isStreaming: false, streamingContent: '' });
          if (currentConvIdRef.current === convId) {
            setError(err);
            setIsStreaming(false);
            setStreamingContent('');
          }
        },
      });
      stopRef.current = stop;
      await promise;
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : 'Failed to send message';
      pushProgress(convId, { error: errMsg, isStreaming: false, streamingContent: '' });
      if (currentConvIdRef.current === convId) {
        setError(errMsg);
        setIsStreaming(false);
        setStreamingContent('');
      }
    } finally {
      stopRef.current = null;
    }
  };

  const handleStop = () => {
    stopRef.current?.();
    stopRef.current = null;
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const displayMessages = showDebug
    ? conversation.messages
    : conversation.messages.filter(
        (m) => m.role === 'user' || (m.role === 'assistant' && !m.tool_name),
      );

  return (
    <div className="flex-1 flex flex-col min-h-0 h-full bg-surface">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3.5 border-b border-surface-border bg-white shadow-card">
        <div>
          <h1 className="text-sm font-semibold text-gray-800 truncate max-w-xl">
            {conversation.title}
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">{organization.name}</p>
        </div>
        <div className="flex items-center gap-2">
          {agentStats && (
            <div className="flex items-center gap-3 text-xs text-gray-600 bg-surface-overlay px-3 py-2 rounded-xl border border-surface-border">
              <span className="flex items-center gap-1" title="AI calls">
                <Cpu className="w-3 h-3 text-brand-500" />
                {agentStats.ai_calls}/{agentStats.max_ai_calls}
              </span>
              <span className="flex items-center gap-1" title="Tool calls">
                <Activity className="w-3 h-3 text-brand-500" />
                {agentStats.tool_calls}
              </span>
              <span className="flex items-center gap-1" title="Estimated tokens">
                <Gauge className="w-3 h-3 text-brand-500" />
                {Math.round(agentStats.estimated_tokens / 1000)}k/{agentStats.max_tokens / 1000}k
              </span>
              <span className="flex items-center gap-1" title="Elapsed time">
                <Clock className="w-3 h-3 text-brand-500" />
                {agentStats.elapsed_seconds}s
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={() => setShowDebug((v) => !v)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-xl border transition-colors ${
              showDebug
                ? 'bg-brand-100 text-brand-700 border-brand-300'
                : 'text-gray-600 hover:text-brand-600 bg-surface-overlay hover:bg-brand-50 border-surface-border'
            }`}
            title={showDebug ? 'Hide tool calls and responses' : 'Show tool calls and responses'}
          >
            <Bug className="w-3.5 h-3.5" />
            {showDebug ? 'Hide debug' : 'Show debug'}
          </button>
          {conversation.messages.length > 0 && (
            <Link
              to={`/debug/${conversation.id}`}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-gray-600 hover:text-brand-600 bg-surface-overlay hover:bg-brand-50 rounded-xl border border-surface-border transition-colors"
              title="View full debug trace in new page"
            >
              <Bug className="w-3.5 h-3.5" />
              Debug page
            </Link>
          )}
        </div>
      </header>

      {/* Messages - min-h-0 allows flex child to shrink and scroll properly */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-6 max-w-4xl mx-auto w-full">
        {conversation.messages.length === 0 && !isStreaming && (
          <div className="flex items-center justify-center h-full min-h-[200px]">
            <p className="text-gray-500 text-sm">Describe the issue you're investigating</p>
          </div>
        )}
        <div className="space-y-6">

        {displayMessages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* In-flight progress: tool steps, streaming content, spinner */}
        {isStreaming && (
          <>
            {toolSteps.length > 0 && (
              <div className="space-y-2">
                {toolSteps.map((step, i) => (
                  <ToolStepRow key={step.id || i} step={step} />
                ))}
              </div>
            )}

            {streamingContent && (
              <MessageBubble
                message={{
                  id: 'streaming',
                  conversation_id: conversation.id,
                  role: 'assistant',
                  content: streamingContent,
                  context: null,
                  tool_name: null,
                  created_at: new Date().toISOString(),
                }}
                isStreaming
              />
            )}

            {!streamingContent && (
              <div className="flex items-center gap-2 text-gray-500 text-sm py-3">
                <Loader2 className="w-4 h-4 animate-spin text-brand-500" />
                <span>Investigating...</span>
              </div>
            )}
          </>
        )}

        {error && (
          <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="ml-auto hover:text-red-700">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
        </div>
      </div>

      {showContext && (
        <div className="border-t border-surface-border bg-white px-6 py-3 shadow-card">
          <ContextForm context={context} onChange={setContext} onClose={() => setShowContext(false)} />
        </div>
      )}

      {/* Input */}
      <div className="border-t border-surface-border px-6 py-4 bg-white">
        <div className="flex items-end gap-3 max-w-4xl mx-auto w-full">
          <button
            onClick={() => setShowContext(!showContext)}
            className={`p-2.5 rounded-xl transition-colors flex-shrink-0 ${
              showContext || hasContext(context)
                ? 'bg-brand-100 text-brand-600'
                : 'text-gray-500 hover:text-gray-700 hover:bg-surface-overlay'
            }`}
            title="Add context (service, environment, file path)"
          >
            <SlidersHorizontal className="w-5 h-5" />
          </button>

          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Describe the issue you want to investigate..."
              rows={1}
              className="input-field resize-none pr-12 min-h-[44px] max-h-32"
              style={{ height: 'auto', minHeight: '44px' }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = 'auto';
                target.style.height = Math.min(target.scrollHeight, 128) + 'px';
              }}
              disabled={isStreaming}
            />
          </div>

          {isStreaming ? (
            <button
              onClick={handleStop}
              className="p-2.5 flex-shrink-0 rounded-xl bg-red-500 hover:bg-red-600 text-white transition-colors"
              title="Stop investigation"
            >
              <Square className="w-5 h-5" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="btn-primary p-2.5 flex-shrink-0"
            >
              <Send className="w-5 h-5" />
            </button>
          )}
        </div>

        {hasContext(context) && !showContext && (
          <div className="flex items-center gap-2 mt-2 text-xs text-gray-500 max-w-4xl mx-auto w-full">
            <SlidersHorizontal className="w-3 h-3 text-brand-500" />
            <span>
              Context: {[context.service, context.environment, context.file_path].filter(Boolean).join(' · ')}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Tool Step Row ─────────────────────────────────── */

function ToolStepRow({ step }: { step: ToolStep }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`border rounded-xl transition-colors ${
        step.status === 'running'
          ? 'border-brand-300 bg-brand-50'
          : 'border-surface-border bg-white'
      }`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-xs"
      >
        {step.status === 'running' ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-brand-500 flex-shrink-0" />
        ) : expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        )}
        <span className="font-medium text-gray-700">{formatToolName(step.tool)}</span>
        <span className="text-gray-500">#{step.toolNumber}</span>
        {step.durationMs !== undefined && (
          <span className="text-gray-500 ml-auto">{step.durationMs}ms</span>
        )}
        {step.resultLength !== undefined && (
          <span className="text-gray-500">{formatBytes(step.resultLength)}</span>
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2 border-t border-surface-border pt-2">
          <div>
            <span className="text-[10px] uppercase tracking-wider text-gray-500 font-medium">Arguments</span>
            <pre className="mt-1 text-xs text-gray-700 bg-slate-50 rounded-lg p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono border border-surface-border">
              {JSON.stringify(step.args, null, 2)}
            </pre>
          </div>
          {step.resultPreview && (
            <div>
              <span className="text-[10px] uppercase tracking-wider text-gray-500 font-medium">Result Preview</span>
              <pre className="mt-1 text-xs text-gray-700 bg-slate-50 rounded-lg p-2 overflow-x-auto max-h-60 overflow-y-auto font-mono whitespace-pre-wrap border border-surface-border">
                {tryFormatJson(step.resultPreview)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function hasContext(ctx: UserContext): boolean {
  return Boolean(ctx.service || ctx.environment || ctx.file_path);
}

function formatToolName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  return `${(bytes / 1024).toFixed(1)}KB`;
}

function tryFormatJson(str: string): string {
  try {
    const parsed = JSON.parse(str);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return str;
  }
}
