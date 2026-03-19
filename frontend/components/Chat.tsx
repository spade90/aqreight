'use client';

import React from 'react';
import { apiAsk } from '../lib/api';

type Citation = { title: string; section?: string };
type Chunk = { title: string; section?: string; text: string };
type Message = {
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  chunks?: Chunk[];
};

const suggestedQuestions = [
  'Can a customer return a damaged blender after 20 days?',
  "What's the shipping SLA to East Malaysia for bulky items?",
  'What is the refund window for small appliances?',
];

export default function Chat() {
  const [messages, setMessages] = React.useState<Message[]>([]);
  const [q, setQ] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [openChunk, setOpenChunk] = React.useState<string | null>(null);
  const bottomRef = React.useRef<HTMLDivElement>(null);

  const chunkKey = (chunk: Chunk, index: number) =>
    `${chunk.title}::${chunk.section || 'Body'}::${index}`;

  const send = async (question?: string) => {
    const prompt = (question ?? q).trim();
    if (!prompt || loading) return;

    setMessages((m) => [...m, { role: 'user', content: prompt }]);
    setLoading(true);
    setQ('');
    setOpenChunk(null);

    try {
      const res = await apiAsk(prompt);
      setMessages((m) => [...m, {
        role: 'assistant',
        content: res.answer,
        citations: res.citations,
        chunks: res.chunks,
      }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Request failed.';
      setMessages((m) => [...m, { role: 'assistant', content: `Error: ${msg}` }]);
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  return (
    <section className="chatPanel">
      <div className="chipRow">
        {suggestedQuestions.map((question) => (
          <button
            key={question}
            className="chip"
            type="button"
            onClick={() => void send(question)}
            disabled={loading}
          >
            {question}
          </button>
        ))}
      </div>

      <div className="messageList">
        {messages.length === 0 && (
          <div className="emptyState">
            Ingest docs, then ask a question above.
          </div>
        )}

        {messages.map((message, i) => (
          <article
            key={`${message.role}-${i}`}
            className={`bubble ${message.role === 'user' ? 'bubbleUser' : 'bubbleAssistant'}`}
          >
            <div className="bubbleContent">{message.content}</div>

            {message.citations && message.citations.length > 0 && (
              <div className="citationRow">
                {message.citations.map((citation, ci) => {
                  const chunkIndex = message.chunks?.findIndex(
                    (c) => c.title === citation.title && c.section === citation.section
                  ) ?? -1;
                  const key = chunkIndex >= 0
                    ? chunkKey(message.chunks![chunkIndex], chunkIndex)
                    : `${citation.title}::${citation.section || 'Body'}::${ci}`;

                  return (
                    <button
                      key={key}
                      className={`citationChip ${openChunk === key ? 'citationChipOpen' : ''}`}
                      type="button"
                      onClick={() => setOpenChunk((cur) => cur === key ? null : key)}
                    >
                      {citation.title.replace('.md', '')}{citation.section ? ` · ${citation.section}` : ''}
                    </button>
                  );
                })}
              </div>
            )}

            {message.chunks?.map((chunk, ci) => {
              const key = chunkKey(chunk, ci);
              if (openChunk !== key) return null;
              return (
                <div key={key} className="sourceCard">
                  <div className="sourceTitle">
                    {chunk.title.replace('.md', '')}{chunk.section ? ` · ${chunk.section}` : ''}
                  </div>
                  <div className="sourceText">{chunk.text}</div>
                </div>
              );
            })}
          </article>
        ))}

        {loading && (
          <article className="bubble bubbleAssistant">
            <div className="bubbleContent thinking">Thinking…</div>
          </article>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="composer">
        <input
          className="composerInput"
          placeholder="Ask a policy question…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void send(); } }}
        />
        <button
          className="sendButton"
          onClick={() => void send()}
          disabled={loading || !q.trim()}
        >
          Send
        </button>
      </div>
    </section>
  );
}
