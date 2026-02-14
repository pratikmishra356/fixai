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
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${
          isUser
            ? 'bg-slate-200 text-slate-600'
            : 'bg-brand-100 text-brand-600'
        }`}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      <div className={`flex-1 min-w-0 ${isUser ? 'text-right' : ''}`}>
        <div className={`flex items-center gap-2 mb-1.5 ${isUser ? 'justify-end' : ''}`}>
          <span className="text-xs font-medium text-gray-500">
            {isUser ? 'You' : 'FixAI'}
          </span>
          <span className="text-xs text-gray-400">
            {formatTime(message.created_at)}
          </span>
        </div>

        {isUser && message.context && (() => {
          const ctx = message.context as Record<string, unknown>;
          return (
            <div className={`flex flex-wrap gap-1.5 mb-2 ${isUser ? 'justify-end' : ''}`}>
              {ctx.service ? <ContextBadge label="Service" value={String(ctx.service)} /> : null}
              {ctx.environment ? <ContextBadge label="Env" value={String(ctx.environment)} /> : null}
              {ctx.file_path ? <ContextBadge label="File" value={String(ctx.file_path)} icon={<FileText className="w-3 h-3" />} /> : null}
            </div>
          );
        })()}

        {isUser ? (
          <div className="inline-block px-4 py-2.5 rounded-2xl rounded-tr-md bg-slate-100 text-gray-800 text-sm leading-relaxed whitespace-pre-wrap max-w-[85%]">
            {message.content}
          </div>
        ) : (
          <div className="px-4 py-3 rounded-2xl rounded-tl-md bg-white border border-surface-border shadow-card max-w-[90%]">
            <div className="markdown-body text-gray-700 text-sm leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
              {isStreaming && (
                <span className="inline-block w-1.5 h-4 bg-brand-500 animate-pulse ml-0.5 align-middle rounded-sm" />
              )}
            </div>
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
    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-white
                     border border-surface-border rounded-lg text-xs text-gray-600 shadow-card">
      {icon}
      <span className="text-gray-500">{label}:</span>
      <span className="font-medium text-gray-700">{value}</span>
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
