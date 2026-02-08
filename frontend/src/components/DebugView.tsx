import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DebugTrace, DebugTraceEntry } from '../types';
import { getConversationDebug } from '../api/client';
import {
  ArrowLeft, Loader2, User, Bot, Wrench, ChevronDown, ChevronRight,
  MessageSquare, Clock, Activity, AlertCircle,
} from 'lucide-react';

export function DebugView() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const [trace, setTrace] = useState<DebugTrace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (conversationId) {
      loadDebug(conversationId);
    }
  }, [conversationId]);

  const loadDebug = async (id: string) => {
    try {
      setLoading(true);
      const data = await getConversationDebug(id);
      setTrace(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load debug trace');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-surface">
        <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
      </div>
    );
  }

  if (error || !trace) {
    return (
      <div className="h-screen flex items-center justify-center bg-surface">
        <div className="text-center">
          <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-3" />
          <p className="text-red-400">{error || 'Trace not found'}</p>
          <Link to="/" className="text-brand-400 text-sm mt-2 inline-block hover:underline">
            Back to chat
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-surface">
      {/* Header */}
      <header className="flex items-center gap-4 px-6 py-4 border-b border-surface-border bg-surface-raised/50">
        <Link
          to="/"
          className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-base font-semibold text-gray-100 truncate">
            Debug: {trace.title}
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {new Date(trace.created_at).toLocaleString()}
          </p>
        </div>

        {/* Summary stats */}
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <MessageSquare className="w-3 h-3" />
            {trace.summary.total_messages} messages
          </span>
          <span className="flex items-center gap-1">
            <Activity className="w-3 h-3" />
            {trace.summary.tool_calls} tool calls
          </span>
          <span className="flex items-center gap-1">
            <Bot className="w-3 h-3" />
            {trace.summary.assistant_messages} responses
          </span>
        </div>
      </header>

      {/* Trace timeline */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto py-6 px-6">
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-6 top-0 bottom-0 w-px bg-surface-border" />

            {trace.trace.map((entry, i) => (
              <TraceEntry key={i} entry={entry} index={i} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function TraceEntry({ entry, index }: { entry: DebugTraceEntry; index: number }) {
  const [expanded, setExpanded] = useState(
    entry.type === 'user_message' || entry.type === 'assistant_response'
  );

  const iconMap = {
    user_message: { icon: User, color: 'bg-surface-overlay text-gray-400', label: 'User' },
    tool_call: { icon: Wrench, color: 'bg-amber-500/20 text-amber-400', label: 'Tool Call' },
    tool_response: { icon: Activity, color: 'bg-emerald-500/20 text-emerald-400', label: 'Tool Response' },
    assistant_response: { icon: Bot, color: 'bg-brand-600/20 text-brand-400', label: 'AI Response' },
  };

  const config = iconMap[entry.type];
  const Icon = config.icon;

  return (
    <div className="relative flex gap-4 pb-6">
      {/* Timeline dot */}
      <div className={`relative z-10 w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 ${config.color}`}>
        <Icon className="w-5 h-5" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pt-1">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 mb-1 group"
        >
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-gray-600" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-gray-600" />
          )}
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
            {config.label}
            {entry.tool && (
              <span className="normal-case tracking-normal text-gray-400 ml-1 font-mono">
                {entry.tool}
              </span>
            )}
          </span>
          <span className="text-[10px] text-gray-600 font-mono">
            {formatTimestamp(entry.timestamp)}
          </span>
        </button>

        {expanded && (
          <div className="mt-1">
            {entry.type === 'user_message' && (
              <div className="bg-surface-overlay border border-surface-border rounded-lg p-4">
                <p className="text-sm text-gray-200 whitespace-pre-wrap">{entry.content}</p>
                {entry.context && Object.keys(entry.context).length > 0 && (
                  <div className="mt-2 flex gap-2 flex-wrap">
                    {Object.entries(entry.context).map(([k, v]) => (
                      <span key={k} className="text-xs bg-surface px-2 py-0.5 rounded text-gray-500">
                        {k}: <span className="text-gray-400">{String(v)}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {entry.type === 'tool_call' && entry.arguments && (
              <div className="bg-surface-overlay border border-surface-border rounded-lg p-3">
                <span className="text-[10px] uppercase tracking-wider text-gray-600 font-medium">Arguments</span>
                <pre className="mt-1 text-xs text-gray-400 font-mono bg-surface/50 rounded p-2 overflow-x-auto max-h-60 overflow-y-auto">
                  {JSON.stringify(entry.arguments, null, 2)}
                </pre>
              </div>
            )}

            {entry.type === 'tool_response' && entry.content && (
              <div className="bg-surface-overlay border border-surface-border rounded-lg p-3">
                <span className="text-[10px] uppercase tracking-wider text-gray-600 font-medium">Response</span>
                <pre className="mt-1 text-xs text-gray-400 font-mono bg-surface/50 rounded p-2 overflow-x-auto max-h-80 overflow-y-auto whitespace-pre-wrap">
                  {tryFormatJson(entry.content)}
                </pre>
              </div>
            )}

            {entry.type === 'assistant_response' && entry.content && (
              <div className="bg-surface-overlay border border-surface-border rounded-lg p-4">
                <div className="markdown-body text-sm text-gray-200 leading-relaxed">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {entry.content}
                  </ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return '';
  }
}

function tryFormatJson(str: string): string {
  try {
    const parsed = JSON.parse(str);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return str;
  }
}
