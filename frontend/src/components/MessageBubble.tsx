import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../types';
import { User, Bot, FileText } from 'lucide-react';

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

export function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div
      className={`flex gap-3 py-4 ${isUser ? '' : ''}`}
    >
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${
          isUser
            ? 'bg-surface-overlay text-gray-400'
            : 'bg-brand-600/20 text-brand-400'
        }`}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-medium text-gray-400">
            {isUser ? 'You' : 'FixAI'}
          </span>
          <span className="text-xs text-gray-600">
            {formatTime(message.created_at)}
          </span>
        </div>

        {/* User context badges */}
        {isUser && message.context && (() => {
          const ctx = message.context as Record<string, unknown>;
          return (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {ctx.service ? <ContextBadge label="Service" value={String(ctx.service)} /> : null}
              {ctx.environment ? <ContextBadge label="Env" value={String(ctx.environment)} /> : null}
              {ctx.file_path ? <ContextBadge label="File" value={String(ctx.file_path)} icon={<FileText className="w-3 h-3" />} /> : null}
            </div>
          );
        })()}

        {/* Message content */}
        {isUser ? (
          <p className="text-gray-200 text-sm leading-relaxed whitespace-pre-wrap">
            {message.content}
          </p>
        ) : (
          <div className="markdown-body text-gray-200 text-sm leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
            {isStreaming && (
              <span className="inline-block w-1.5 h-4 bg-brand-400 animate-pulse ml-0.5 align-middle rounded-sm" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ContextBadge({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-surface-overlay
                     border border-surface-border rounded text-xs text-gray-400">
      {icon}
      <span className="text-gray-500">{label}:</span>
      <span className="text-gray-300">{value}</span>
    </span>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}
