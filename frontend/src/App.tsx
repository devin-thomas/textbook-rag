import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, clearConversations, deleteConversation, getConversation, getConversations, getHealth, getSources, queryTextbooks } from "./api";
import { FALLBACK_SOURCES } from "./catalog";
import { AnswerView } from "./components/AnswerView";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { EvidencePanel } from "./components/EvidencePanel";
import { HistoryRail } from "./components/HistoryRail";
import { ScopePopover } from "./components/ScopePopover";
import { BookIcon, FilterIcon, MenuIcon, PlusIcon, SendIcon } from "./icons";
import type { Answer, AnswerStatus, ConversationSummary, Evidence, ProviderChoice, Source } from "./types";

type DeleteTarget = ConversationSummary | "all" | undefined;
type ResearchHealthState = "checking" | "configured" | "unavailable";

function scopeLabel(courseIds: string[], sourceIds: string[], sources: Source[]): string {
  if (!courseIds.length && !sourceIds.length) return "All four books";
  if (sourceIds.length === 1) return sources.find((source) => source.id === sourceIds[0])?.title ?? "1 textbook";
  if (sourceIds.length > 1) return `${sourceIds.length} textbooks`;
  return `${courseIds.length} course${courseIds.length === 1 ? "" : "s"}`;
}

export default function App() {
  const [provider, setProvider] = useState<ProviderChoice>("auto");
  const [question, setQuestion] = useState("");
  const [sources, setSources] = useState<Source[]>(FALLBACK_SOURCES);
  const [courseIds, setCourseIds] = useState<string[]>([]);
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string>();
  const [answer, setAnswer] = useState<Answer>();
  const [status, setStatus] = useState<AnswerStatus>("idle");
  const [loadingStep, setLoadingStep] = useState("Finding the strongest passages…");
  const [loadingQuestion, setLoadingQuestion] = useState("");
  const [evidenceVisible, setEvidenceVisible] = useState(false);
  const [mobileEvidenceExpanded, setMobileEvidenceExpanded] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<Evidence>();
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget>();
  const [deleting, setDeleting] = useState(false);
  const [researchHealth, setResearchHealth] = useState<ResearchHealthState>("checking");

  const refreshConversations = useCallback(async () => {
    try { setConversations(await getConversations()); } catch { /* History remains usable as an empty local view while the API starts. */ }
  }, []);

  useEffect(() => {
    void Promise.all([
      getSources().then((items) => items.length && setSources(items)).catch(() => undefined),
      getHealth().then((health) => setResearchHealth(health.status === "ok" && health.ollama.configured ? "configured" : "unavailable")).catch(() => setResearchHealth("unavailable")),
      refreshConversations(),
    ]);
  }, [refreshConversations]);

  useEffect(() => {
    if (status !== "loading") return;
    const timer = window.setTimeout(() => setLoadingStep(`Reading with ${provider === "auto" ? "NVIDIA first" : provider === "nvidia" ? "NVIDIA" : "Ollama"}…`), 900);
    return () => window.clearTimeout(timer);
  }, [provider, status]);

  const selectedScope = useMemo(() => scopeLabel(courseIds, sourceIds, sources), [courseIds, sourceIds, sources]);

  const reset = () => {
    setQuestion("");
    setAnswer(undefined);
    setStatus("idle");
    setSelectedConversationId(undefined);
    setEvidenceVisible(false);
    setMobileEvidenceExpanded(false);
    setActiveEvidence(undefined);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || status === "loading") return;
    setLoadingQuestion(trimmed);
    setLoadingStep("Finding the strongest passages…");
    setStatus("loading");
    setAnswer(undefined);
    setActiveEvidence(undefined);
    setEvidenceVisible(false);
    setMobileEvidenceExpanded(false);
    try {
      const result = await queryTextbooks({
        question: trimmed,
        provider,
        course_ids: courseIds.length ? courseIds : undefined,
        source_ids: sourceIds.length ? sourceIds : undefined,
        conversation_id: selectedConversationId,
      });
      setAnswer(result);
      setStatus(result.status);
      setQuestion("");
      setSelectedConversationId(result.conversationId);
      setEvidenceVisible(result.evidence.length > 0);
      await refreshConversations();
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "The textbook service is unavailable right now.";
      setAnswer({ status: "error", question: trimmed, text: "", citations: [], evidence: [], requestedProvider: provider, fallback: false, error: message });
      setStatus("error");
    }
  };

  const openConversation = async (id: string) => {
    setSelectedConversationId(id);
    setStatus("loading");
    setLoadingQuestion("Opening saved question…");
    setLoadingStep("Loading local history…");
    try {
      const result = await getConversation(id);
      setAnswer(result);
      setStatus(result.status);
      setProvider(result.requestedProvider);
      setEvidenceVisible(result.evidence.length > 0);
      setActiveEvidence(undefined);
    } catch (error) {
      setAnswer({ status: "error", question: "Saved question", text: "", citations: [], evidence: [], requestedProvider: provider, fallback: false, error: error instanceof Error ? error.message : "Could not load this question." });
      setStatus("error");
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      if (deleteTarget === "all") {
        await clearConversations();
        setConversations([]);
        reset();
      } else {
        await deleteConversation(deleteTarget.id);
        setConversations((items) => items.filter((item) => item.id !== deleteTarget.id));
        if (selectedConversationId === deleteTarget.id) reset();
      }
      setDeleteTarget(undefined);
    } finally {
      setDeleting(false);
    }
  };

  const openCitation = (item: Evidence) => {
    setActiveEvidence(item);
    setEvidenceVisible(true);
    setMobileEvidenceExpanded(true);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="icon-button mobile-only" onClick={() => setHistoryOpen(true)} aria-label="Open history"><MenuIcon /></button>
        <a className="brand" href="/textbooks/" onClick={(event) => { event.preventDefault(); reset(); }}>Textbook Desk</a>
        <button className="scope-top desktop-only" onClick={() => setScopeOpen(true)}><BookIcon /> {selectedScope} <span>⌄</span></button>
        <label className="provider-select"><span className="desktop-only">Provider</span><select value={provider} onChange={(event) => setProvider(event.target.value as ProviderChoice)} aria-label="Answer provider"><option value="auto">Auto</option><option value="nvidia">NVIDIA</option><option value="ollama">Ollama</option></select></label>
        <span className="research-status desktop-only" data-state={researchHealth}><i /> {researchHealth === "checking" ? "Checking Research…" : researchHealth === "configured" ? "Research configured" : "Research unavailable"}</span>
        <button className="new-question" onClick={reset}><PlusIcon /><span className="desktop-only">New question</span></button>
      </header>

      <div className={`workspace ${evidenceVisible ? "has-evidence" : ""}`}>
        <HistoryRail conversations={conversations} selectedId={selectedConversationId} mobileOpen={historyOpen} onSelect={openConversation} onDelete={setDeleteTarget} onClear={() => setDeleteTarget("all")} onCloseMobile={() => setHistoryOpen(false)} />
        <main className="answer-pane">
          <AnswerView status={status} answer={answer} loadingQuestion={loadingQuestion} loadingStep={loadingStep} onCitation={openCitation} onShowEvidence={() => { setEvidenceVisible(true); setMobileEvidenceExpanded(true); }} />
          <form className="composer" onSubmit={submit}>
            <div className="privacy-note"><span aria-hidden="true">◇</span> Answers stay inside your textbooks</div>
            <div className="composer-box">
              <label><span className="sr-only">Ask your textbooks</span><textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="Ask your textbooks…" rows={2} maxLength={4000} /></label>
              <div className="composer-controls">
                <button type="button" className="scope-button" onClick={() => setScopeOpen(!scopeOpen)} aria-expanded={scopeOpen}><FilterIcon /> <span>{selectedScope}</span> <span>⌄</span></button>
                <button className="send-button" type="submit" disabled={!question.trim() || status === "loading"} aria-label="Ask question"><SendIcon /></button>
              </div>
              <ScopePopover open={scopeOpen} sources={sources} courseIds={courseIds} sourceIds={sourceIds} onCourseIds={setCourseIds} onSourceIds={setSourceIds} onClose={() => setScopeOpen(false)} />
            </div>
          </form>
        </main>
        {evidenceVisible && answer?.evidence && <EvidencePanel evidence={answer.evidence} activeEvidence={activeEvidence} mobileExpanded={mobileEvidenceExpanded} onMobileExpanded={setMobileEvidenceExpanded} onActiveEvidence={setActiveEvidence} onCloseDesktop={() => setEvidenceVisible(false)} />}
      </div>

      <ConfirmDialog open={Boolean(deleteTarget)} title={deleteTarget === "all" ? "Clear all question history?" : `Delete “${deleteTarget?.title}”?`} description={deleteTarget === "all" ? "This permanently removes every saved conversation from Titan. Your textbook index and original PDFs will not be changed." : "This permanently removes this conversation from Titan. Your textbook index and original PDFs will not be changed."} confirmLabel={deleteTarget === "all" ? "Clear all history" : "Delete question"} busy={deleting} onConfirm={confirmDelete} onClose={() => setDeleteTarget(undefined)} />
    </div>
  );
}
