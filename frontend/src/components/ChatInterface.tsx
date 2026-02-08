import { useState, useRef, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import type { Organization, ConversationDetail, Message, UserContext, ToolStep, AgentStats } from '../types';
import { sendMessage, type ToolStartEvent, type ToolEndEvent } from '../api/client';
import { MessageBubble } from './MessageBubble';
import { ContextForm } from './ContextForm';
import {
  Send, Loader2, SlidersHorizontal, X, ChevronDown, ChevronRight,
  Activity, Bug, Clock, Cpu, Gauge,
} from 'lucide-react';

interface ChatInterfaceProps {
  conversation: ConversationDetail;
  organization: Organization;
  onConversationUpdated: (conv: ConversationDetail) => void;
}

export function ChatInterface({
  conversation,
  organization,
  onConversationUpdated,
}: ChatInterfaceProps) {
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [toolSteps, setToolSteps] = useState<ToolStep[]>([]);
  const [agentStats, setAgentStats] = useState<AgentStats | null>(null);
  const [showContext, setShowContext] = useState(false);
  const [context, setContext] = useState<UserContext>({});
  const [error, setError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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
    setInput('');
    setError(null);
    setIsStreaming(true);
    setStreamingContent('');
    setToolSteps([]);
    setAgentStats(null);

    const userMsg: Message = {
      id: crypto.randomUUID(),
      conversation_id: conversation.id,
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
    onConversationUpdated(updatedConv);

    let fullResponse = '';

    try {
      await sendMessage({
        conversationId: conversation.id,
        content: userContent,
        context: hasContext(context) ? context : undefined,
        onToken: (token) => {
          fullResponse += token;
          setStreamingContent((prev) => prev + token);
        },
        onToolStart: (data: ToolStartEvent) => {
          setToolSteps((prev) => [
            ...prev,
            {
              id: data.id,
              tool: data.tool,
              args: data.args,
              toolNumber: data.tool_number,
              aiCall: data.ai_call,
              status: 'running',
            },
          ]);
        },
        onToolEnd: (data: ToolEndEvent) => {
          setToolSteps((prev) => {
            const updated = [...prev];
            const running = updated.findIndex((t) => t.status === 'running');
            if (running >= 0) {
              updated[running] = {
                ...updated[running],
                status: 'done',
                resultPreview: data.result_preview,
                resultLength: data.result_length,
                durationMs: data.duration_ms,
              };
            }
            return updated;
          });
        },
        onStats: (stats: AgentStats) => {
          setAgentStats(stats);
        },
        onDone: (content) => {
          fullResponse = content || fullResponse;
          const assistantMsg: Message = {
            id: crypto.randomUUID(),
            conversation_id: conversation.id,
            role: 'assistant',
            content: fullResponse,
            context: null,
            tool_name: null,
            created_at: new Date().toISOString(),
          };
          onConversationUpdated({
            ...updatedConv,
            messages: [...updatedConv.messages, assistantMsg],
          });
          setIsStreaming(false);
          setStreamingContent('');
        },
        onError: (err) => {
          setError(err);
          setIsStreaming(false);
          setStreamingContent('');
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message');
      setIsStreaming(false);
      setStreamingContent('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-surface-border bg-surface-raised/50">
        <div>
          <h1 className="text-sm font-medium text-gray-200 truncate max-w-xl">
            {conversation.title}
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">{organization.name}</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Stats badge */}
          {agentStats && (
            <div className="flex items-center gap-3 text-xs text-gray-500 bg-surface-overlay px-3 py-1.5 rounded-lg">
              <span className="flex items-center gap-1" title="AI calls">
                <Cpu className="w-3 h-3" />
                {agentStats.ai_calls}/{agentStats.max_ai_calls}
              </span>
              <span className="flex items-center gap-1" title="Tool calls">
                <Activity className="w-3 h-3" />
                {agentStats.tool_calls}
              </span>
              <span className="flex items-center gap-1" title="Estimated tokens">
                <Gauge className="w-3 h-3" />
                {Math.round(agentStats.estimated_tokens / 1000)}k/{agentStats.max_tokens / 1000}k
              </span>
              <span className="flex items-center gap-1" title="Elapsed time">
                <Clock className="w-3 h-3" />
                {agentStats.elapsed_seconds}s
              </span>
            </div>
          )}
          {conversation.messages.length > 0 && (
            <Link
              to={`/debug/${conversation.id}`}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 hover:text-brand-400 bg-surface-overlay hover:bg-brand-600/10 rounded-lg transition-colors"
              title="View debug trace"
            >
              <Bug className="w-3.5 h-3.5" />
              Debug
            </Link>
          )}
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1">
        {conversation.messages.length === 0 && !isStreaming && (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500 text-sm">Describe the issue you're investigating</p>
          </div>
        )}

        {conversation.messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* Streaming */}
        {isStreaming && (
          <>
            {/* Tool steps */}
            {toolSteps.length > 0 && (
              <div className="mb-3 ml-11 space-y-1">
                {toolSteps.map((step, i) => (
                  <ToolStepRow key={step.id || i} step={step} />
                ))}
              </div>
            )}

            {/* Streaming text */}
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

            {!streamingContent && toolSteps.some((t) => t.status === 'running') && (
              <div className="flex items-center gap-2 text-gray-500 text-sm ml-11 py-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Investigating...</span>
              </div>
            )}
          </>
        )}

        {error && (
          <div className="flex items-center gap-2 px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="ml-auto">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Context form */}
      {showContext && (
        <div className="border-t border-surface-border bg-surface-raised/50 px-6 py-3">
          <ContextForm context={context} onChange={setContext} onClose={() => setShowContext(false)} />
        </div>
      )}

      {/* Input */}
      <div className="border-t border-surface-border px-6 py-4 bg-surface-raised/30">
        <div className="flex items-end gap-3">
          <button
            onClick={() => setShowContext(!showContext)}
            className={`p-2.5 rounded-lg transition-colors flex-shrink-0 ${
              showContext || hasContext(context)
                ? 'bg-brand-600/20 text-brand-400'
                : 'text-gray-500 hover:text-gray-300 hover:bg-surface-overlay'
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

          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            className="btn-primary p-2.5 flex-shrink-0"
          >
            {isStreaming ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
          </button>
        </div>

        {hasContext(context) && !showContext && (
          <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
            <SlidersHorizontal className="w-3 h-3" />
            <span>
              Context:{' '}
              {[context.service, context.environment, context.file_path].filter(Boolean).join(' · ')}
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
      className={`border rounded-lg transition-colors ${
        step.status === 'running'
          ? 'border-brand-600/30 bg-brand-600/5'
          : 'border-surface-border bg-surface-overlay/50'
      }`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs"
      >
        {step.status === 'running' ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-brand-400 flex-shrink-0" />
        ) : expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        )}
        <span className="font-medium text-gray-300">{formatToolName(step.tool)}</span>
        <span className="text-gray-600">#{step.toolNumber}</span>
        {step.durationMs !== undefined && (
          <span className="text-gray-600 ml-auto">{step.durationMs}ms</span>
        )}
        {step.resultLength !== undefined && (
          <span className="text-gray-600">{formatBytes(step.resultLength)}</span>
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2 border-t border-surface-border/50 pt-2">
          {/* Arguments */}
          <div>
            <span className="text-[10px] uppercase tracking-wider text-gray-600 font-medium">Arguments</span>
            <pre className="mt-1 text-xs text-gray-400 bg-surface/50 rounded p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono">
              {JSON.stringify(step.args, null, 2)}
            </pre>
          </div>
          {/* Result preview */}
          {step.resultPreview && (
            <div>
              <span className="text-[10px] uppercase tracking-wider text-gray-600 font-medium">Result Preview</span>
              <pre className="mt-1 text-xs text-gray-400 bg-surface/50 rounded p-2 overflow-x-auto max-h-60 overflow-y-auto font-mono whitespace-pre-wrap">
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
