import { useState } from 'react';
import type { Organization } from '../types';
import { createOrganization } from '../api/client';
import { X, Loader2 } from 'lucide-react';

interface OrgSetupModalProps {
  onClose: () => void;
  onCreated: (org: Organization) => void;
}

export function OrgSetupModal({ onClose, onCreated }: OrgSetupModalProps) {
  const [form, setForm] = useState({
    name: '',
    slug: '',
    description: '',
    code_parser_base_url: 'http://localhost:8000',
    code_parser_org_id: '',
    code_parser_repo_id: '',
    metrics_explorer_base_url: 'http://localhost:8002',
    metrics_explorer_org_id: '',
    logs_explorer_base_url: 'http://localhost:8003',
    logs_explorer_org_id: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateField = (field: string, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    if (field === 'name') {
      const slug = value
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '');
      setForm((prev) => ({ ...prev, [field]: value, slug }));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name || !form.slug) return;

    setSaving(true);
    setError(null);

    try {
      const body: Record<string, string | undefined> = {
        name: form.name,
        slug: form.slug,
        description: form.description || undefined,
      };

      if (form.code_parser_base_url) body.code_parser_base_url = form.code_parser_base_url;
      if (form.code_parser_org_id) body.code_parser_org_id = form.code_parser_org_id;
      if (form.code_parser_repo_id) body.code_parser_repo_id = form.code_parser_repo_id;
      if (form.metrics_explorer_base_url) body.metrics_explorer_base_url = form.metrics_explorer_base_url;
      if (form.metrics_explorer_org_id) body.metrics_explorer_org_id = form.metrics_explorer_org_id;
      if (form.logs_explorer_base_url) body.logs_explorer_base_url = form.logs_explorer_base_url;
      if (form.logs_explorer_org_id) body.logs_explorer_org_id = form.logs_explorer_org_id;

      const org = await createOrganization(body as any);
      onCreated(org);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create organization');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-surface-raised border border-surface-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-border">
          <h2 className="text-lg font-semibold text-gray-100">Create Organization</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {/* Basic info */}
          <div>
            <h3 className="text-sm font-medium text-gray-300 mb-3">Basic Information</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1.5">Name *</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => updateField('name', e.target.value)}
                  placeholder="My Organization"
                  className="input-field"
                  required
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1.5">Slug *</label>
                <input
                  type="text"
                  value={form.slug}
                  onChange={(e) => updateField('slug', e.target.value)}
                  placeholder="my-org"
                  className="input-field"
                  pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"
                  required
                />
              </div>
            </div>
            <div className="mt-3">
              <label className="block text-xs text-gray-500 mb-1.5">Description</label>
              <input
                type="text"
                value={form.description}
                onChange={(e) => updateField('description', e.target.value)}
                placeholder="Optional description"
                className="input-field"
              />
            </div>
          </div>

          {/* Service mappings */}
          <div>
            <h3 className="text-sm font-medium text-gray-300 mb-3">Service Connections</h3>

            {/* Code Parser */}
            <div className="bg-surface-overlay border border-surface-border rounded-lg p-4 mb-3">
              <div className="mb-3">
                <h4 className="text-sm font-medium text-gray-200">Code Parser</h4>
                <p className="text-xs text-gray-500 mt-0.5">Code parsing and entry point analysis</p>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Base URL</label>
                  <input
                    type="url"
                    value={form.code_parser_base_url}
                    onChange={(e) => updateField('code_parser_base_url', e.target.value)}
                    placeholder="http://localhost:8000"
                    className="input-field text-xs"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Organization ID</label>
                  <input
                    type="text"
                    value={form.code_parser_org_id}
                    onChange={(e) => updateField('code_parser_org_id', e.target.value)}
                    placeholder="ULID of the org"
                    className="input-field text-xs"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Repository ID</label>
                  <input
                    type="text"
                    value={form.code_parser_repo_id}
                    onChange={(e) => updateField('code_parser_repo_id', e.target.value)}
                    placeholder="ULID of the repo"
                    className="input-field text-xs"
                  />
                </div>
              </div>
            </div>

            {/* Metrics Explorer */}
            <ServiceConfig
              title="Metrics Explorer"
              description="Metrics, dashboards, and monitoring"
              baseUrl={form.metrics_explorer_base_url}
              identifier={form.metrics_explorer_org_id}
              identifierLabel="Organization ID"
              identifierPlaceholder="UUID of the metrics org"
              onBaseUrlChange={(v) => updateField('metrics_explorer_base_url', v)}
              onIdentifierChange={(v) => updateField('metrics_explorer_org_id', v)}
            />

            {/* Logs Explorer */}
            <ServiceConfig
              title="Logs Explorer"
              description="Log search and exploration"
              baseUrl={form.logs_explorer_base_url}
              identifier={form.logs_explorer_org_id}
              identifierLabel="Organization ID"
              identifierPlaceholder="UUID of the logs org"
              onBaseUrlChange={(v) => updateField('logs_explorer_base_url', v)}
              onIdentifierChange={(v) => updateField('logs_explorer_org_id', v)}
            />
          </div>

          {error && (
            <div className="px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
            <button type="submit" disabled={saving || !form.name || !form.slug} className="btn-primary">
              {saving ? (
                <><Loader2 className="w-4 h-4 animate-spin inline mr-2" />Creating...</>
              ) : (
                'Create Organization'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ServiceConfig({
  title,
  description,
  baseUrl,
  identifier,
  identifierLabel,
  identifierPlaceholder,
  onBaseUrlChange,
  onIdentifierChange,
}: {
  title: string;
  description: string;
  baseUrl: string;
  identifier: string;
  identifierLabel: string;
  identifierPlaceholder: string;
  onBaseUrlChange: (v: string) => void;
  onIdentifierChange: (v: string) => void;
}) {
  return (
    <div className="bg-surface-overlay border border-surface-border rounded-lg p-4 mb-3">
      <div className="mb-3">
        <h4 className="text-sm font-medium text-gray-200">{title}</h4>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Base URL</label>
          <input
            type="url"
            value={baseUrl}
            onChange={(e) => onBaseUrlChange(e.target.value)}
            placeholder="http://localhost:8000"
            className="input-field text-xs"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">{identifierLabel}</label>
          <input
            type="text"
            value={identifier}
            onChange={(e) => onIdentifierChange(e.target.value)}
            placeholder={identifierPlaceholder}
            className="input-field text-xs"
          />
        </div>
      </div>
    </div>
  );
}
