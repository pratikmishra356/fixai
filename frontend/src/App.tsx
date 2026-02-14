import { useState, useEffect, useCallback } from 'react';
import { Routes, Route } from 'react-router-dom';
import type { Organization, Conversation, ConversationDetail } from './types';
import {
  listOrganizations,
  listConversations,
  createConversation,
  getConversation,
  deleteConversation,
} from './api/client';
import { Sidebar } from './components/Sidebar';
import { ChatInterface } from './components/ChatInterface';
import { OrgSetupModal } from './components/OrgSetupModal';
import { DebugView } from './components/DebugView';
import { Settings, Zap } from 'lucide-react';

export default function App() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrg, setSelectedOrg] = useState<Organization | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<ConversationDetail | null>(null);
  const [showOrgModal, setShowOrgModal] = useState(false);
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
        if (activeConversation?.id === convId) {
          setActiveConversation(null);
        }
      } catch (err) {
        console.error('Failed to delete conversation:', err);
      }
    },
    [activeConversation?.id],
  );

  const handleOrgCreated = (org: Organization) => {
    setOrganizations((prev) => [org, ...prev]);
    setSelectedOrg(org);
    setShowOrgModal(false);
  };

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
                onOpenOrgSettings={() => setShowOrgModal(true)}
              />
              <main className="flex-1 flex flex-col min-w-0">
                {selectedOrg ? (
                  activeConversation ? (
                    <ChatInterface
                      conversation={activeConversation}
                      organization={selectedOrg}
                      onConversationUpdated={(conv) => {
                        setActiveConversation(conv);
                        setConversations((prev) =>
                          prev.map((c) =>
                            c.id === conv.id ? { ...c, title: conv.title, message_count: conv.messages.length } : c,
                          ),
                        );
                      }}
                    />
                  ) : (
                    <EmptyState onNewConversation={handleNewConversation} />
                  )
                ) : (
                  <SetupPrompt onSetup={() => setShowOrgModal(true)} />
                )}
              </main>
              {showOrgModal && (
                <OrgSetupModal
                  onClose={() => setShowOrgModal(false)}
                  onCreated={handleOrgCreated}
                />
              )}
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

function SetupPrompt({ onSetup }: { onSetup: () => void }) {
  return (
    <div className="flex-1 flex items-center justify-center bg-surface">
      <div className="text-center max-w-md px-6">
        <div className="w-20 h-20 rounded-2xl bg-surface-overlay flex items-center justify-center mx-auto mb-6 shadow-soft">
          <Settings className="w-10 h-10 text-gray-500" />
        </div>
        <h2 className="text-2xl font-semibold text-gray-800 mb-3">Set up your organization</h2>
        <p className="text-gray-600 mb-8 leading-relaxed">
          Configure your organization and connect it to your code parser,
          metrics explorer, and logs explorer services.
        </p>
        <button onClick={onSetup} className="btn-primary text-base px-6 py-3 rounded-xl">
          Create Organization
        </button>
      </div>
    </div>
  );
}
