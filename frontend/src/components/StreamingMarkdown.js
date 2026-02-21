import { useState, useEffect, useRef, useCallback, memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  themeVariables: {
    darkMode: true,
    primaryColor: '#D946EF',
    primaryTextColor: '#FAFAFA',
    primaryBorderColor: '#D946EF',
    lineColor: '#52525B',
    secondaryColor: '#18181B',
    tertiaryColor: '#0A0A0A',
    background: '#0A0A0A',
    mainBkg: '#18181B',
    secondBkg: '#0A0A0A',
    fontFamily: 'JetBrains Mono, monospace',
    fontSize: '14px',
    nodeBorder: '#D946EF',
    clusterBkg: '#18181B',
    clusterBorder: '#27272A',
    edgeLabelBackground: '#0A0A0A',
    actorBkg: '#18181B',
    actorBorder: '#D946EF',
    actorTextColor: '#FAFAFA',
    signalColor: '#FAFAFA',
    signalTextColor: '#FAFAFA',
    labelBoxBkgColor: '#18181B',
    labelBoxBorderColor: '#27272A',
    labelTextColor: '#FAFAFA',
    loopTextColor: '#A1A1AA',
    noteBkgColor: '#27272A',
    noteTextColor: '#FAFAFA',
    noteBorderColor: '#D946EF',
    entityBorder: '#D946EF',
    entityFill: '#18181B',
  },
  flowchart: { curve: 'basis', padding: 15 },
  sequence: { actorMargin: 50, messageMargin: 40 },
  er: { fontSize: 12 },
});

const MermaidDiagram = memo(function MermaidDiagram({ content }) {
  const containerRef = useRef(null);
  const [svg, setSvg] = useState('');
  const [error, setError] = useState('');
  const idRef = useRef(`mermaid-${Math.random().toString(36).substr(2, 9)}`);

  useEffect(() => {
    if (!content || !content.trim()) return;
    let cancelled = false;
    mermaid
      .render(idRef.current, content.trim())
      .then(({ svg: renderedSvg }) => {
        if (!cancelled) setSvg(renderedSvg);
      })
      .catch((e) => {
        if (!cancelled) {
          console.warn('Mermaid render error:', e);
          setError(content);
        }
      });
    return () => { cancelled = true; };
  }, [content]);

  if (error) {
    return (
      <pre className="bg-[#0A0A0A] border border-[#27272A] rounded-sm p-4 overflow-x-auto text-sm text-muted-foreground">
        <code>{error}</code>
      </pre>
    );
  }
  if (!svg) return null;

  return (
    <div
      ref={containerRef}
      className="mermaid-diagram my-6 p-4 bg-[#0A0A0A] border border-[#27272A] rounded-sm overflow-x-auto flex justify-center"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
});

export default function StreamingMarkdown({ content, isStreaming }) {
  return (
    <div className="relative">
      <div className={`markdown-body ${isStreaming ? 'streaming-cursor' : ''}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeHighlight]}
          components={{
            code({ node, className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || '');
              const lang = match ? match[1] : '';
              const codeStr = String(children).replace(/\n$/, '');

              if (lang === 'mermaid' && !isStreaming) {
                return <MermaidDiagram content={codeStr} />;
              }

              // For mermaid during streaming, show as code block
              if (lang === 'mermaid') {
                return (
                  <pre className="bg-[#0A0A0A] border border-[#27272A] rounded-sm p-4 overflow-x-auto">
                    <code className="text-sm text-[#A1A1AA] font-mono">{codeStr}</code>
                  </pre>
                );
              }

              // Inline code
              if (!className) {
                return <code {...props}>{children}</code>;
              }

              // Regular code block (already handled by rehype-highlight)
              return <code className={className} {...props}>{children}</code>;
            },
            // Add data-heading attribute for TOC navigation
            h2({ children, ...props }) {
              const text = typeof children === 'string' ? children
                : Array.isArray(children) ? children.map(c => typeof c === 'string' ? c : '').join('') : '';
              return <h2 data-heading={text} {...props}>{children}</h2>;
            },
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}
