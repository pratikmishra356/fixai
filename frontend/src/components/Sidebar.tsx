import { useState } from 'react';
import type { Organization, Conversation } from '../types';
import {
  Plus,
  MessageSquare,
  Trash2,
  ChevronDown,
  Zap,
  Settings,
  Building2,
} from 'lucide-react';

interface SidebarProps {
  organizations: Organization[];
  selectedOrg: Organization | null;
  conversations: Conversation[];
  activeConversationId: string | null;
  onSelectOrg: (org: Organization) => void;
  onNewConversation: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onOpenOrgSettings: () => void;
}

export function Sidebar({
  organizations,
  selectedOrg,
  conversations,
  activeConversationId,
  onSelectOrg,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
  onOpenOrgSettings,
}: SidebarProps) {
  const [orgDropdownOpen, setOrgDropdownOpen] = useState(false);

  return (
    <aside className="w-72 bg-white border-r border-surface-border flex flex-col h-full shadow-card">
      {/* Header */}
      <div className="p-4 border-b border-surface-border">
        <div className="flex items-center gap-2.5 mb-4">
          <div className="w-9 h-9 rounded-xl bg-brand-500 flex items-center justify-center shadow-soft">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <span className="font-semibold text-lg text-gray-800">FixAI</span>
        </div>

        {/* Org selector */}
        <div className="relative">
          <button
            onClick={() => setOrgDropdownOpen(!orgDropdownOpen)}
            className="w-full flex items-center justify-between px-3 py-2.5 bg-surface-overlay
                       rounded-xl text-sm text-gray-700 hover:bg-slate-200/80 transition-colors border border-surface-border"
          >
            <div className="flex items-center gap-2 truncate">
              <Building2 className="w-4 h-4 text-gray-500 flex-shrink-0" />
              <span className="truncate font-medium">
                {selectedOrg?.name || 'Select organization'}
              </span>
            </div>
            <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />
          </button>

          {orgDropdownOpen && (
            <>
              <div
                className="fixed inset-0 z-10"
                onClick={() => setOrgDropdownOpen(false)}
              />
              <div className="absolute top-full left-0 right-0 mt-2 bg-white border
                              border-surface-border rounded-xl shadow-soft z-20 overflow-hidden">
                {organizations.map((org) => (
                  <button
                    key={org.id}
                    onClick={() => {
                      onSelectOrg(org);
                      setOrgDropdownOpen(false);
                    }}
                    className={`w-full text-left px-3 py-2.5 text-sm transition-colors
                      ${selectedOrg?.id === org.id ? 'text-brand-600 bg-brand-50 font-medium' : 'text-gray-700 hover:bg-surface-overlay'}`}
                  >
                    {org.name}
                  </button>
                ))}
                <button
                  onClick={() => {
                    onOpenOrgSettings();
                    setOrgDropdownOpen(false);
                  }}
                  className="w-full text-left px-3 py-2.5 text-sm text-gray-600
                             hover:bg-surface-overlay transition-colors border-t border-surface-border
                             flex items-center gap-2"
                >
                  <Plus className="w-3 h-3" />
                  Add organization
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* New conversation button */}
      {selectedOrg && (
        <div className="p-3">
          <button
            onClick={onNewConversation}
            className="w-full flex items-center gap-2 px-3 py-2.5 bg-brand-500
                       hover:bg-brand-600 rounded-xl text-sm font-medium text-white
                       transition-colors shadow-soft"
          >
            <Plus className="w-4 h-4" />
            New Conversation
          </button>
        </div>
      )}

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto px-2 py-1">
        {conversations.length === 0 && selectedOrg && (
          <p className="text-center text-gray-500 text-xs mt-8 px-4">
            No conversations yet. Start one above.
          </p>
        )}
        {conversations.map((conv) => (
          <ConversationItem
            key={conv.id}
            conversation={conv}
            isActive={conv.id === activeConversationId}
            onSelect={() => onSelectConversation(conv.id)}
            onDelete={() => onDeleteConversation(conv.id)}
          />
        ))}
      </div>

      {/* Footer */}
      {selectedOrg && (
        <div className="p-3 border-t border-surface-border">
          <button
            onClick={onOpenOrgSettings}
            className="btn-ghost w-full flex items-center gap-2 justify-center text-gray-600"
          >
            <Settings className="w-4 h-4" />
            Organization Settings
          </button>
        </div>
      )}
    </aside>
  );
}

function ConversationItem({
  conversation,
  isActive,
  onSelect,
  onDelete,
}: {
  conversation: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [hovering, setHovering] = useState(false);

  return (
    <div
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      className={`group flex items-center gap-2 px-3 py-2.5 rounded-xl cursor-pointer
                  mb-0.5 transition-colors ${
                    isActive
                      ? 'bg-brand-50 text-brand-700 font-medium'
                      : 'text-gray-600 hover:bg-surface-overlay hover:text-gray-800'
                  }`}
      onClick={onSelect}
    >
      <MessageSquare className="w-4 h-4 flex-shrink-0 opacity-70" />
      <span className="text-sm truncate flex-1">{conversation.title}</span>
      {hovering && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="text-gray-400 hover:text-red-500 transition-colors p-0.5"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
