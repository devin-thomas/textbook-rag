import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const sources = { sources: [{ id: "missing-link-web", title: "The Missing Link", course_ids: ["ITSE-1311"] }] };
const healthy = { status: "ok", ollama: { configured: true } };

function response(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function mockApi(queryResult?: unknown, conversations: unknown[] = [], health: unknown = healthy, conversationDetail?: unknown) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/health")) return response(health);
    if (url.endsWith("/sources")) return response(sources);
    if (url.endsWith("/conversations") && (!init?.method || init.method === "GET")) return response({ conversations });
    if (conversationDetail && url.includes("/conversations/")) return response(conversationDetail);
    if (url.includes("/query")) return response(queryResult ?? {});
    if (url.includes("confirm=true")) return response(undefined, 204);
    if (init?.method === "DELETE") return response(undefined, 204);
    return response({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Textbook Desk", () => {
  it("reports Research configuration only after the health response", async () => {
    mockApi();
    render(<App />);
    expect(await screen.findByText("Research configured")).toBeInTheDocument();
    expect(screen.queryByText("Research online")).not.toBeInTheDocument();
  });

  it("submits the chosen provider and displays cited textbook evidence", async () => {
    const fetchMock = mockApi({
      status: "answered",
      answer: "Semantic HTML describes purpose, not appearance. [1]",
      actual_provider: "ollama",
      fallback_used: false,
      conversation_id: "conv-1",
      citations: [{ id: "1", evidence_id: "chunk-1" }],
      evidence: [{ id: "chunk-1", source_id: "missing-link-web", source_title: "The Missing Link", physical_page: 64, excerpt: "Semantic elements describe meaning.", rank: 1, fused_score: 0.25 }],
    });
    const user = userEvent.setup();
    render(<App />);

    await user.selectOptions(screen.getByLabelText("Answer provider"), "ollama");
    await user.type(screen.getByPlaceholderText("Ask your textbooks…"), "Why is semantic HTML important?");
    await user.click(screen.getByRole("button", { name: "Ask question" }));

    expect(await screen.findByText(/Semantic HTML describes purpose/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "The Missing Link · p. 64" })).toBeInTheDocument();
    expect(screen.getByText("OLLAMA")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open citation 1, The Missing Link, page 64" }));
    expect(await screen.findByTitle("The Missing Link, page 64")).toHaveAttribute("src", expect.stringContaining("#page=64"));
    const queryCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/query"));
    expect(JSON.parse(String(queryCall?.[1]?.body))).toMatchObject({ provider: "ollama", question: "Why is semantic HTML important?" });
  });

  it("announces an automatic fallback without changing the user selection", async () => {
    mockApi({ status: "answered", answer: "A grounded answer.", actual_provider: "ollama", fallback_used: true, initial_failure_kind: "timeout", citations: [], evidence: [] });
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByPlaceholderText("Ask your textbooks…"), "Explain this");
    await user.click(screen.getByRole("button", { name: "Ask question" }));
    expect(await screen.findByText(/NVIDIA unavailable/)).toBeInTheDocument();
    expect(screen.getByLabelText("Answer provider")).toHaveValue("auto");
    await user.click(screen.getByRole("button", { name: "Dismiss fallback notice" }));
    expect(screen.queryByText(/NVIDIA unavailable/)).not.toBeInTheDocument();
  });

  it("renders a persisted provider failure as an error when history is reopened", async () => {
    mockApi(undefined, [{ id: "conv-failed", title: "Virtual memory", updated_at: "2026-08-24T14:00:00Z" }], healthy, {
      id: "conv-failed",
      title: "Virtual memory",
      messages: [
        { id: "u1", role: "user", text: "What is virtual memory?", provider_choice: "nvidia" },
        { id: "a1", role: "assistant", text: "Nvidia is temporarily unavailable for this question.", provider_choice: "nvidia", status: "provider_unavailable", evidence: [] },
      ],
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /^Virtual memory/ }));
    expect(await screen.findByRole("heading", { name: "Nvidia is temporarily unavailable for this question." })).toBeInTheDocument();
    expect(screen.queryByText(/Answered by/)).not.toBeInTheDocument();
  });

  it("renders insufficient evidence as a distinct non-error state", async () => {
    mockApi({ status: "insufficient_evidence", answer: "", citations: [], evidence: [] });
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByPlaceholderText("Ask your textbooks…"), "What is the weather tomorrow?");
    await user.click(screen.getByRole("button", { name: "Ask question" }));
    expect(await screen.findByText("I couldn’t find support for that in these four books.")).toBeInTheDocument();
    expect(screen.getByText(/No generation provider was called/)).toBeInTheDocument();
  });

  it("renders structured citations when prose has no citation markers", async () => {
    mockApi({
      status: "ok",
      answer: "Semantic structure helps assistive technology.",
      actual_provider: "nvidia",
      fallback_used: false,
      citations: [{ chunk_id: "chunk-1", source_id: "missing-link-web", source_title: "The Missing Link", physical_page: 70, page_label: "64" }],
      evidence: [{ chunk_id: "chunk-1", source_id: "missing-link-web", source_title: "The Missing Link", physical_page: 70, page_label: "64", excerpt: "Semantic elements describe meaning.", rank: 1 }],
    });
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByPlaceholderText("Ask your textbooks…"), "Why use semantic elements?");
    await user.click(screen.getByRole("button", { name: "Ask question" }));
    const citation = await screen.findByRole("button", { name: "Open citation 1, The Missing Link, page 64" });
    await user.click(citation);
    expect(await screen.findByTitle("The Missing Link, page 70")).toHaveAttribute("src", expect.stringContaining("#page=70"));
  });

  it("distinguishes a provider abstention from retrieval insufficiency", async () => {
    mockApi({
      status: "insufficient_evidence",
      answer: "",
      actual_provider: "nvidia",
      fallback_used: false,
      citations: [],
      evidence: [{ chunk_id: "chunk-1", source_id: "missing-link-web", source_title: "The Missing Link", physical_page: 70, excerpt: "A related passage.", rank: 1 }],
    });
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByPlaceholderText("Ask your textbooks…"), "Explain the passage");
    await user.click(screen.getByRole("button", { name: "Ask question" }));
    expect(await screen.findByText("Provider did not answer")).toBeInTheDocument();
    expect(screen.getByText(/The provider was called/)).toBeInTheDocument();
    expect(screen.queryByText(/No generation provider was called/)).not.toBeInTheDocument();
  });

  it("requires confirmation before clearing local history", async () => {
    const fetchMock = mockApi(undefined, [{ id: "conv-1", title: "Virtual memory", updated_at: "2026-08-24T14:00:00Z" }]);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Virtual memory");
    await user.click(screen.getByRole("button", { name: /Clear history/ }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Clear all question history?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Clear all history" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("confirm=true"), expect.objectContaining({ method: "DELETE" })));
    expect(screen.queryByText("Virtual memory")).not.toBeInTheDocument();
  });
});
