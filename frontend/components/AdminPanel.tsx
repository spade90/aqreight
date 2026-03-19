'use client';

import React from 'react';
import { apiIngest, apiMetrics } from '../lib/api';

type Metrics = {
  total_docs: number;
  total_chunks: number;
  avg_retrieval_latency_ms: number;
  avg_generation_latency_ms: number;
  p95_retrieval_latency_ms: number;
  p95_generation_latency_ms: number;
  total_queries: number;
  embedding_model: string;
  llm_model: string;
};

export default function AdminPanel() {
  const [metrics, setMetrics] = React.useState<Metrics | null>(null);
  const [ingesting, setIngesting] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const [status, setStatus] = React.useState<{ text: string; error: boolean }>({ text: '', error: false });

  const refresh = async () => {
    setRefreshing(true);
    try {
      const m = await apiMetrics();
      setMetrics(m);
      setStatus({ text: 'Metrics updated.', error: false });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not fetch metrics.';
      setStatus({ text: msg, error: true });
    } finally {
      setRefreshing(false);
    }
  };

  const ingest = async () => {
    setIngesting(true);
    setStatus({ text: 'Indexing…', error: false });
    try {
      const result = await apiIngest();
      await refresh();
      setStatus({ text: `${result.indexed_docs} docs · ${result.indexed_chunks} chunks indexed`, error: false });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ingest failed.';
      setStatus({ text: msg, error: true });
    } finally {
      setIngesting(false);
    }
  };

  React.useEffect(() => { refresh(); }, []);

  const isReady = Boolean(metrics && metrics.total_docs > 0);

  return (
    <aside className="sidebar">
      <div className="sidebarSection">
        <div className="readinessRow">
          <span className={`statusDot ${isReady ? 'dotReady' : 'dotPending'}`} />
          <span className="readinessText">{isReady ? 'Ready' : 'Not ready'}</span>
        </div>

        <button className="ingestButton" onClick={ingest} disabled={ingesting || refreshing}>
          {ingesting ? 'Indexing…' : 'Ingest docs'}
        </button>

        <button className="refreshButton" onClick={refresh} disabled={refreshing || ingesting}>
          {refreshing ? 'Refreshing…' : 'Refresh metrics'}
        </button>

        {status.text && (
          <p className={`sidebarStatus ${status.error ? 'statusError' : 'statusOk'}`}>
            {status.text}
          </p>
        )}
      </div>

      {metrics && (
        <div className="sidebarSection">
          <p className="sidebarSectionLabel">Index</p>
          <div className="statRow"><span>Docs</span><strong>{metrics.total_docs}</strong></div>
          <div className="statRow"><span>Chunks</span><strong>{metrics.total_chunks}</strong></div>
          <div className="statRow"><span>Queries</span><strong>{metrics.total_queries}</strong></div>
        </div>
      )}

      {metrics && (
        <div className="sidebarSection">
          <p className="sidebarSectionLabel">Latency</p>
          <div className="statRow"><span>Retrieval</span><strong>{metrics.avg_retrieval_latency_ms} ms</strong></div>
          <div className="statRow"><span>Generation</span><strong>{metrics.avg_generation_latency_ms} ms</strong></div>
        </div>
      )}

      {metrics && (
        <div className="sidebarSection">
          <p className="sidebarSectionLabel">Models</p>
          <div className="statRow"><span>LLM</span><strong className="statTrunc">{metrics.llm_model}</strong></div>
          <div className="statRow"><span>Embed</span><strong className="statTrunc">{metrics.embedding_model}</strong></div>
        </div>
      )}
    </aside>
  );
}
