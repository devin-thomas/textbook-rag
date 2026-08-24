import type { Answer, AppHealth, Citation, ConversationSummary, Evidence, ProviderChoice, QueryRequest, Source } from "./types";

const API_BASE = "/textbooks/api";

type JsonObject = Record<string, unknown>;

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message);
  }
}

function object(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
}

function text(...values: unknown[]): string {
  return values.find((value): value is string => typeof value === "string") ?? "";
}

function number(...values: unknown[]): number | undefined {
  const value = values.find((item) => typeof item === "number" || (typeof item === "string" && item.trim() !== ""));
  if (value === undefined) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function historyAnswerStatus(rawStatus: string, actualProvider?: string): Answer["status"] {
  if (rawStatus === "abstained" || rawStatus.includes("insufficient")) {
    return actualProvider ? "provider_abstention" : "insufficient_evidence";
  }
  if (rawStatus === "error" || rawStatus === "provider_unavailable" || rawStatus === "retrieval_unavailable" || rawStatus === "internal_error") {
    return "error";
  }
  return "answered";
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (response.status === 204) return undefined;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = object(data);
    const nestedError = object(detail.error);
    throw new ApiError(text(nestedError.message, detail.message, detail.detail, "The request could not be completed."), response.status, text(nestedError.code, detail.code) || undefined);
  }
  return data;
}

function normalizeEvidence(value: unknown, index: number): Evidence {
  const item = object(value);
  const source = object(item.source);
  const scores = object(item.scores);
  return {
    id: text(item.id, item.chunk_id, item.evidence_id, `evidence-${index + 1}`),
    sourceId: text(item.source_id, source.id),
    sourceTitle: text(item.source_title, source.title, "Textbook"),
    page: number(item.page, item.physical_page, item.pdf_page) ?? 1,
    pageLabel: text(item.page_label) || undefined,
    excerpt: text(item.excerpt, item.content, item.text),
    rank: number(item.rank) ?? index + 1,
    semanticScore: number(item.semantic_score, scores.semantic),
    lexicalScore: number(item.fts_score, item.lexical_score, scores.lexical),
    fusedScore: number(item.fusion_score, item.fused_score, item.score, scores.fused),
  };
}

function normalizeCitation(value: unknown, index: number, evidence: Evidence[]): Citation {
  const item = object(value);
  const evidenceId = text(item.evidence_id, item.chunk_id, item.id);
  const match = evidence.find((entry) => entry.id === evidenceId) ?? evidence[index];
  return {
    id: text(item.id, String(index + 1)),
    evidenceId: evidenceId || match?.id || "",
    sourceId: text(item.source_id, match?.sourceId),
    sourceTitle: text(item.source_title, match?.sourceTitle, "Textbook"),
    page: number(item.page, item.physical_page, match?.page) ?? 1,
    pageLabel: text(item.page_label, match?.pageLabel) || undefined,
    pdfUrl: text(item.pdf_url) || undefined,
  };
}

export async function getSources(): Promise<Source[]> {
  const data = await request("/sources");
  const root = object(data);
  return array(Array.isArray(data) ? data : root.sources).map((value) => {
    const item = object(value);
    return {
      id: text(item.id, item.source_id),
      title: text(item.title, item.display_title),
      course_ids: array(item.course_ids).filter((id): id is string => typeof id === "string"),
      indexed: typeof item.indexed === "boolean" ? item.indexed : undefined,
      status: text(item.status, item.index_status) || undefined,
    };
  });
}

export async function getHealth(): Promise<AppHealth> {
  const raw = object(await request("/health"));
  const ollama = object(raw.ollama);
  return {
    status: text(raw.status),
    ollama: {
      configured: ollama.configured === true,
      status: text(ollama.status) || undefined,
    },
  };
}

export async function queryTextbooks(body: QueryRequest): Promise<Answer> {
  const raw = object(await request("/query", { method: "POST", body: JSON.stringify(body) }));
  const evidence = array(raw.evidence).map(normalizeEvidence);
  const provider = object(raw.provider_outcome ?? raw.provider);
  const rawStatus = text(raw.status, raw.answer_status).toLowerCase();
  const actualProvider = (text(raw.actual_provider, provider.actual, provider.provider).toLowerCase() || undefined) as "nvidia" | "ollama" | undefined;
  const status = (rawStatus === "abstained" || rawStatus.includes("insufficient")) && actualProvider
    ? "provider_abstention"
    : rawStatus.includes("insufficient") || rawStatus === "abstained"
      ? "insufficient_evidence"
      : "answered";
  return {
    status,
    question: body.question,
    text: text(raw.answer, raw.text, raw.message),
    citations: array(raw.citations).map((value, index) => normalizeCitation(value, index, evidence)),
    evidence,
    requestedProvider: body.provider,
    actualProvider,
    fallback: Boolean(raw.fallback_used ?? raw.fallback ?? provider.fallback ?? provider.did_fallback),
    fallbackReason: text(raw.initial_failure_kind, raw.fallback_reason, provider.fallback_reason, provider.reason) || undefined,
    conversationId: text(raw.conversation_id) || undefined,
    messageId: text(raw.assistant_message_id, raw.message_id) || undefined,
  };
}

export async function getConversations(): Promise<ConversationSummary[]> {
  const data = await request("/conversations");
  const root = object(data);
  return array(Array.isArray(data) ? data : root.conversations).map((value) => {
    const item = object(value);
    return {
      id: text(item.id, item.conversation_id),
      title: text(item.title, item.question, "Untitled question"),
      updatedAt: text(item.updated_at, item.created_at, new Date().toISOString()),
    };
  });
}

export async function getConversation(id: string): Promise<Answer> {
  const raw = object(await request(`/conversations/${encodeURIComponent(id)}`));
  const messages = array(raw.messages).map(object);
  let assistantIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (text(messages[index].role).toLowerCase() === "assistant") {
      assistantIndex = index;
      break;
    }
  }
  const assistant = assistantIndex >= 0 ? messages[assistantIndex] : undefined;
  let user: JsonObject | undefined;
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    if (text(messages[index].role).toLowerCase() === "user") {
      user = messages[index];
      break;
    }
  }
  if (!assistant) {
    const danglingUser = [...messages].reverse().find((message) => text(message.role).toLowerCase() === "user");
    return {
      status: "error",
      question: text(danglingUser?.text, danglingUser?.content, raw.title),
      text: "",
      citations: [],
      evidence: [],
      requestedProvider: (text(danglingUser?.provider_choice, "auto").toLowerCase()) as ProviderChoice,
      fallback: false,
      conversationId: id,
      error: "This saved question did not finish. You can ask it again.",
    };
  }
  const evidenceRaw = assistant?.evidence ?? raw.evidence;
  const evidence = array(evidenceRaw).map(normalizeEvidence);
  const citationsRaw = assistant?.citations ?? raw.citations ?? array(evidenceRaw)
    .map(object)
    .filter((item) => number(item.citation_order) !== undefined)
    .sort((left, right) => (number(left.citation_order) ?? 0) - (number(right.citation_order) ?? 0));
  const rawStatus = text(assistant?.status, raw.status).toLowerCase();
  const provider = text(assistant?.actual_provider, assistant?.provider).toLowerCase();
  const status = historyAnswerStatus(rawStatus, provider || undefined);
  const assistantText = text(assistant?.text, assistant?.content, raw.answer);
  return {
    status,
    question: text(user?.text, user?.content, raw.title),
    text: status === "error" ? "" : assistantText,
    citations: array(citationsRaw).map((value, index) => normalizeCitation(value, index, evidence)),
    evidence,
    requestedProvider: (text(assistant?.provider_choice, assistant?.requested_provider, "auto").toLowerCase()) as ProviderChoice,
    actualProvider: (provider || undefined) as "nvidia" | "ollama" | undefined,
    fallback: Boolean(assistant?.fallback_used ?? assistant?.fallback),
    fallbackReason: text(assistant?.initial_failure_kind, assistant?.fallback_reason) || undefined,
    conversationId: id,
    messageId: text(assistant?.id) || undefined,
    error: status === "error" ? assistantText || "This saved question could not be completed." : undefined,
  };
}

export async function deleteConversation(id: string): Promise<void> {
  await request(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function clearConversations(): Promise<void> {
  await request("/conversations?confirm=true", { method: "DELETE" });
}

export function pdfUrl(sourceId: string, page: number): string {
  return `${API_BASE}/sources/${encodeURIComponent(sourceId)}/pdf#page=${page}&view=FitH`;
}
