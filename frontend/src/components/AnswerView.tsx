import { useState } from "react";
import { AlertIcon, BookIcon, ChevronIcon, CloseIcon } from "../icons";
import type { Answer, AnswerStatus, Evidence } from "../types";

interface AnswerViewProps {
  status: AnswerStatus;
  answer?: Answer;
  loadingQuestion: string;
  loadingStep: string;
  onCitation: (evidence: Evidence) => void;
  onShowEvidence: () => void;
}

function evidenceForCitation(answer: Answer, citationIndex: number): Evidence | undefined {
  const citation = answer.citations[citationIndex];
  return citation ? answer.evidence.find((item) => item.id === citation.evidenceId) ?? answer.evidence.find((item) => item.sourceId === citation.sourceId && item.page === citation.page) ?? answer.evidence[citationIndex] : answer.evidence[citationIndex];
}

function AnswerText({ answer, onCitation }: { answer: Answer; onCitation: (evidence: Evidence) => void }) {
  const parts = answer.text.split(/(\[\d+\])/g);
  return <>{parts.map((part, index) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (!match) return <span key={index}>{part}</span>;
    const citationIndex = Number(match[1]) - 1;
    const evidence = evidenceForCitation(answer, citationIndex);
    return evidence ? <button key={index} className="citation" onClick={() => onCitation(evidence)} aria-label={`Open inline citation ${match[1]}, ${evidence.sourceTitle}, page ${evidence.page}`}>{part}</button> : <span key={index}>{part}</span>;
  })}</>;
}

function CitationControls({ answer, onCitation }: { answer: Answer; onCitation: (evidence: Evidence) => void }) {
  if (!answer.citations.length) return null;
  return (
    <nav className="citation-controls" aria-label="Answer citations">
      {answer.citations.map((citation, index) => {
        const evidence = evidenceForCitation(answer, index);
        if (!evidence) return null;
        const page = citation.pageLabel ?? evidence.pageLabel ?? citation.page;
        return <button key={`${citation.evidenceId}-${index}`} onClick={() => onCitation(evidence)} aria-label={`Open citation ${index + 1}, ${citation.sourceTitle}, page ${page}`}><span>[{index + 1}]</span> {citation.sourceTitle} · p. {page}</button>;
      })}
    </nav>
  );
}

export function AnswerView({ status, answer, loadingQuestion, loadingStep, onCitation, onShowEvidence }: AnswerViewProps) {
  const [dismissedFallbackKey, setDismissedFallbackKey] = useState<string>();
  const fallbackKey = answer?.fallback ? answer.messageId ?? `${answer.conversationId ?? ""}:${answer.question}:${answer.text}` : "";

  if (status === "idle") return (
    <div className="welcome-state">
      <div className="welcome-mark" aria-hidden="true"><BookIcon /></div>
      <p className="eyebrow">Your semester library</p>
      <h1>Ask the page,<br />not the whole internet.</h1>
      <p>Search four course textbooks and get a concise answer tied to the exact pages that support it.</p>
      <div className="prompt-ideas" aria-label="Question ideas">
        <span>Try asking</span>
        <p>“What makes a professional commitment?”</p>
        <p>“How does virtual memory work?”</p>
      </div>
    </div>
  );

  if (status === "loading") return (
    <article className="answer-article" aria-live="polite">
      <p className="eyebrow">You asked</p><h1>{loadingQuestion}</h1><hr />
      <div className="loading-answer">
        <div className="loading-symbol" aria-hidden="true"><span /><span /><span /></div>
        <p className="eyebrow">Working from your textbooks</p>
        <h2>{loadingStep}</h2>
        <div className="skeleton long" /><div className="skeleton" /><div className="skeleton short" />
      </div>
    </article>
  );

  if (!answer) return null;

  return (
    <article className="answer-article">
      {answer.fallback && dismissedFallbackKey !== fallbackKey && <div className="fallback-banner" role="status"><AlertIcon /><span><strong>NVIDIA unavailable</strong> — answered by Ollama</span><button type="button" className="icon-button fallback-dismiss" onClick={() => setDismissedFallbackKey(fallbackKey)} aria-label="Dismiss fallback notice"><CloseIcon /></button></div>}
      {answer.retrievalFallback && <div className="retrieval-fallback-banner" role="status"><AlertIcon /><span><strong>Research unavailable</strong> — using textbook keyword search for this request.</span></div>}
      <p className="eyebrow">You asked</p><h1>{answer.question}</h1>
      {answer.selectAllThatApply && <p className="answer-mode-note" role="status"><strong>Select all that apply mode</strong><span>Multiple correct answers may be included.</span></p>}
      <hr />
      {answer.status === "insufficient_evidence" ? (
        <div className="insufficient-state">
          <span className="insufficient-mark" aria-hidden="true">?</span>
          <p className="eyebrow">Not enough textbook evidence</p>
          <h2>I couldn’t find support for that in these four books.</h2>
          <p>Try rephrasing the question or widening the selected course and textbook scope. No generation provider was called.</p>
        </div>
      ) : answer.status === "provider_abstention" ? (
        <div className="insufficient-state provider-abstention">
          <span className="insufficient-mark" aria-hidden="true">!</span>
          <p className="eyebrow">Provider did not answer</p>
          <h2>{answer.actualProvider?.toUpperCase() ?? "The selected provider"} could not produce a grounded answer from the retrieved passages.</h2>
          <p>The provider was called, but its response was an abstention. Try rephrasing the question or inspect the retrieved textbook evidence.</p>
          {answer.evidence.length > 0 && <button type="button" className="show-evidence" onClick={onShowEvidence}><BookIcon /> Inspect retrieved evidence ({answer.evidence.length}) <ChevronIcon className="chevron-down" /></button>}
        </div>
      ) : answer.status === "error" ? (
        <div className="error-state" role="alert"><AlertIcon /><div><p className="eyebrow">Couldn’t answer</p><h2>{answer.error}</h2><p>Your question is still here. Check the provider or try again.</p></div></div>
      ) : (
        <>
          <p className="eyebrow answer-label">Answer</p>
          <div className="answer-copy"><AnswerText answer={answer} onCitation={onCitation} /></div>
          <CitationControls answer={answer} onCitation={onCitation} />
          <div className="provider-result"><span className={`provider-dot ${answer.actualProvider ?? "unknown"}`} /> Answered by <strong>{answer.actualProvider?.toUpperCase() ?? "the selected provider"}</strong>{answer.fallback && <span className="fallback-note"> after automatic fallback</span>}</div>
          <button type="button" className="show-evidence" onClick={onShowEvidence}><BookIcon /> Show textbook evidence ({answer.evidence.length}) <ChevronIcon className="chevron-down" /></button>
        </>
      )}
    </article>
  );
}
