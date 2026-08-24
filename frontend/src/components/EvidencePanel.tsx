import { useEffect, useState } from "react";
import { pdfUrl } from "../api";
import { BookIcon, ChevronIcon, CloseIcon, ExternalIcon } from "../icons";
import type { Evidence } from "../types";

interface EvidencePanelProps {
  evidence: Evidence[];
  activeEvidence?: Evidence;
  mobileExpanded: boolean;
  onMobileExpanded: (expanded: boolean) => void;
  onActiveEvidence: (evidence: Evidence) => void;
  onCloseDesktop: () => void;
}

function ScoreDetail({ evidence }: { evidence: Evidence }) {
  const scores = [
    ["Semantic", evidence.semanticScore],
    ["Text match", evidence.lexicalScore],
    ["Combined", evidence.fusedScore],
  ].filter((entry): entry is [string, number] => typeof entry[1] === "number");
  if (!scores.length) return <span>Retrieved rank {evidence.rank}</span>;
  return <span>{scores.map(([label, value]) => `${label} ${value.toFixed(3)}`).join(" · ")}</span>;
}

export function EvidencePanel({ evidence, activeEvidence, mobileExpanded, onMobileExpanded, onActiveEvidence, onCloseDesktop }: EvidencePanelProps) {
  const [tab, setTab] = useState<"evidence" | "page">("evidence");
  const [expandedId, setExpandedId] = useState<string>();

  useEffect(() => {
    if (activeEvidence) setTab("page");
  }, [activeEvidence]);

  const openPage = (item: Evidence) => {
    onActiveEvidence(item);
    setTab("page");
    onMobileExpanded(true);
  };

  return (
    <aside className={`evidence-panel ${mobileExpanded ? "mobile-expanded" : ""}`} aria-label="Textbook evidence">
      <button className="sheet-handle mobile-only" onClick={() => onMobileExpanded(!mobileExpanded)} aria-label={mobileExpanded ? "Collapse evidence" : "Expand evidence"}><span /></button>
      <div className="evidence-heading">
        <h2><BookIcon /> Textbook evidence <span>({evidence.length})</span></h2>
        <button className="icon-button desktop-close" onClick={onCloseDesktop} aria-label="Close evidence"><CloseIcon /></button>
        <button className="icon-button mobile-only" onClick={() => onMobileExpanded(!mobileExpanded)} aria-label={mobileExpanded ? "Collapse evidence" : "Expand evidence"}><ChevronIcon className={mobileExpanded ? "chevron-up" : "chevron-down"} /></button>
      </div>
      <div className="evidence-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "evidence"} onClick={() => setTab("evidence")}>Evidence</button>
        <button role="tab" aria-selected={tab === "page"} disabled={!activeEvidence} onClick={() => setTab("page")}>Page view</button>
      </div>
      {tab === "evidence" ? (
        <div className="evidence-list">
          {evidence.map((item, index) => {
            const expanded = expandedId === item.id;
            return (
              <article className={`evidence-card ${index === 0 ? "best-match" : ""}`} key={item.id}>
                <div className="evidence-rank">{index + 1}</div>
                <div className="evidence-body">
                  <h3>{item.sourceTitle} · p. {item.pageLabel ?? item.page}</h3>
                  <p>{item.excerpt}</p>
                  <button className="open-page" onClick={() => openPage(item)}>Open page <ExternalIcon /></button>
                  <button className="ranking-detail" onClick={() => setExpandedId(expanded ? undefined : item.id)} aria-expanded={expanded}>
                    {expanded ? "Hide ranking detail" : "Show ranking detail"}<ChevronIcon />
                  </button>
                  {expanded && <div className="score-detail"><ScoreDetail evidence={item} /></div>}
                </div>
              </article>
            );
          })}
          {evidence.length === 0 && <p className="empty-evidence">Evidence for an answer will appear here.</p>}
        </div>
      ) : activeEvidence ? (
        <div className="pdf-view">
          <div className="pdf-title"><strong>{activeEvidence.sourceTitle}</strong><span>Page {activeEvidence.page}</span></div>
          <iframe title={`${activeEvidence.sourceTitle}, page ${activeEvidence.page}`} src={pdfUrl(activeEvidence.sourceId, activeEvidence.page)} />
        </div>
      ) : null}
    </aside>
  );
}
