import type { UserContext } from '../types';
import { X, Server, Globe, FileCode } from 'lucide-react';

interface ContextFormProps {
  context: UserContext;
  onChange: (ctx: UserContext) => void;
  onClose: () => void;
}

export function ContextForm({ context, onChange, onClose }: ContextFormProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-gray-600 uppercase tracking-wider">
          Investigation Context
          <span className="text-gray-400 normal-case tracking-normal ml-2">
            (optional)
          </span>
        </h3>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-gray-700 transition-colors p-1 rounded-lg hover:bg-surface-overlay"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="flex items-center gap-1.5 text-xs text-gray-600 mb-1.5">
            <Server className="w-3 h-3 text-brand-500" />
            Service Name
          </label>
          <input
            type="text"
            value={context.service || ''}
            onChange={(e) => onChange({ ...context, service: e.target.value || undefined })}
            placeholder="e.g. order-service"
            className="input-field text-xs"
          />
        </div>

        <div>
          <label className="flex items-center gap-1.5 text-xs text-gray-600 mb-1.5">
            <Globe className="w-3 h-3 text-brand-500" />
            Environment
          </label>
          <input
            type="text"
            value={context.environment || ''}
            onChange={(e) =>
              onChange({ ...context, environment: e.target.value || undefined })
            }
            placeholder="e.g. prod, staging"
            className="input-field text-xs"
          />
        </div>

        <div>
          <label className="flex items-center gap-1.5 text-xs text-gray-600 mb-1.5">
            <FileCode className="w-3 h-3 text-brand-500" />
            File Path
          </label>
          <input
            type="text"
            value={context.file_path || ''}
            onChange={(e) =>
              onChange({ ...context, file_path: e.target.value || undefined })
            }
            placeholder="e.g. src/handlers/order.py"
            className="input-field text-xs"
          />
        </div>
      </div>
    </div>
  );
}
