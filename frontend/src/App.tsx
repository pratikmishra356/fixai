import { useState, useEffect, useCallback } from 'react';
import { Routes, Route } from 'react-router-dom';
import type { Organization, Conversation, ConversationDetail, ConversationProgress } from './types';
import {
  listOrganizations,
  listConversations,
  createConversation,
  getConversation,
  deleteConversation,
} from './api/client';
import { Sidebar } from './components/Sidebar';
import { ChatInterface } from './components/ChatInterface';
import { DebugView } from './components/DebugView';
import { Zap } from 'lucide-react';

export default function App() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrg, setSelectedOrg] = useState<Organization | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<ConversationDetail | null>(null);
  const [progressByConv, setProgressByConv] = useState<Record<string, ConversationProgress>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadOrgs();
  }, []);

  const loadOrgs = async () => {
    try {
      const orgs = await listOrganizations();
      setOrganizations(orgs);
      if (orgs.length > 0 && !selectedOrg) {
        setSelectedOrg(orgs[0]);
      }
    } catch (err) {
      console.error('Failed to load organizations:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (selectedOrg) {
      loadConversations(selectedOrg.id);
    } else {
      setConversations([]);
      setActiveConversation(null);
    }
  }, [selectedOrg?.id]);

  const loadConversations = async (orgId: string) => {
    try {
      const convs = await listConversations(orgId);
      setConversations(convs);
    } catch (err) {
      console.error('Failed to load conversations:', err);
    }
  };

  const handleNewConversation = useCallback(async () => {
    if (!selectedOrg) return;
    try {
      const conv = await createConversation(selectedOrg.id);
      setConversations((prev) => [conv, ...prev]);
      setActiveConversation({
        id: conv.id,
        organization_id: conv.organization_id,
        title: conv.title,
        created_at: conv.created_at,
        updated_at: conv.updated_at,
        messages: [],
      });
    } catch (err) {
      console.error('Failed to create conversation:', err);
    }
  }, [selectedOrg]);

  const handleSelectConversation = useCallback(async (convId: string) => {
    try {
      const detail = await getConversation(convId);
      setActiveConversation(detail);
    } catch (err) {
      console.error('Failed to load conversation:', err);
    }
  }, []);

  const handleDeleteConversation = useCallback(
    async (convId: string) => {
      try {
        await deleteConversation(convId);
        setConversations((prev) => prev.filter((c) => c.id !== convId));
        setProgressByConv((prev) => {
          const next = { ...prev };
          delete next[convId];
          return next;
        });
        if (activeConversation?.id === convId) {
          setActiveConversation(null);
        }
      } catch (err) {
        console.error('Failed to delete conversation:', err);
      }
    },
    [activeConversation?.id],
  );

  const handleProgressUpdate = useCallback((convId: string, progress: ConversationProgress) => {
    setProgressByConv((prev) => ({ ...prev, [convId]: progress }));
  }, []);

  const handleConversationUpdated = useCallback((conv: ConversationDetail) => {
    setActiveConversation((prev) => (prev?.id === conv.id ? conv : prev));
    setConversations((prev) =>
      prev.map((c) =>
        c.id === conv.id ? { ...c, title: conv.title, message_count: conv.messages.length } : c,
      ),
    );
  }, []);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-surface">
        <div className="flex items-center gap-3 text-gray-600">
          <Zap className="w-6 h-6 animate-pulse text-brand-500" />
          <span className="text-lg font-medium">Loading FixAI...</span>
        </div>
      </div>
    );
  }

  return (
    <>
      <Routes>
        <Route
          path="/debug/:conversationId"
          element={<DebugView />}
        />
        <Route
          path="*"
          element={
            <div className="h-screen flex overflow-hidden bg-[#f8fafc]">
              <Sidebar
                organizations={organizations}
                selectedOrg={selectedOrg}
                conversations={conversations}
                activeConversationId={activeConversation?.id || null}
                onSelectOrg={setSelectedOrg}
                onNewConversation={handleNewConversation}
                onSelectConversation={handleSelectConversation}
                onDeleteConversation={handleDeleteConversation}
              />
              <main className="flex-1 flex flex-col min-w-0">
                {selectedOrg ? (
                  activeConversation ? (
                    <ChatInterface
                      conversation={activeConversation}
                      organization={selectedOrg}
                      initialProgress={progressByConv[activeConversation.id]}
                      onConversationUpdated={handleConversationUpdated}
                      onProgressUpdate={handleProgressUpdate}
                    />
                  ) : (
                    <EmptyState onNewConversation={handleNewConversation} />
                  )
                ) : (
                  <NoOrgState />
                )}
              </main>
            </div>
          }
        />
      </Routes>
    </>
  );
}

function EmptyState({ onNewConversation }: { onNewConversation: () => void }) {
  return (
    <div className="flex-1 flex items-center justify-center bg-surface">
      <div className="text-center max-w-md px-6">
        <div className="w-20 h-20 rounded-2xl bg-brand-100 flex items-center justify-center mx-auto mb-6 shadow-soft">
          <Zap className="w-10 h-10 text-brand-600" />
        </div>
        <h2 className="text-2xl font-semibold text-gray-800 mb-3">Start debugging</h2>
        <p className="text-gray-600 mb-8 leading-relaxed">
          Ask FixAI to investigate production issues. It will search code, metrics,
          and logs to help you find the root cause.
        </p>
        <button onClick={onNewConversation} className="btn-primary text-base px-6 py-3 rounded-xl">
          New Conversation
        </button>
      </div>
    </div>
  );
}

function NoOrgState() {
  return (
    <div className="flex-1 flex items-center justify-center bg-surface">
      <div className="text-center max-w-md px-6">
        <div className="w-20 h-20 rounded-2xl bg-surface-overlay flex items-center justify-center mx-auto mb-6 shadow-soft">
          <Zap className="w-10 h-10 text-gray-500" />
        </div>
        <h2 className="text-2xl font-semibold text-gray-800 mb-3">No organization found</h2>
        <p className="text-gray-600 leading-relaxed">
          Organizations are created from the CodeCircle dashboard.
          Set up a workspace there and this will be ready to use.
        </p>
      </div>
    </div>
  );
}
