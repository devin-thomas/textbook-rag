import { useMemo, useState } from "react";
import { COURSES } from "../catalog";
import { CloseIcon, FilterIcon, SearchIcon, TrashIcon } from "../icons";
import type { ConversationSummary, ProviderChoice } from "../types";

interface HistoryRailProps {
  conversations: ConversationSummary[];
  selectedId?: string;
  mobileOpen: boolean;
  onSelect: (id: string) => void;
  onDelete: (conversation: ConversationSummary) => void;
  onClear: () => void;
  onCloseMobile: () => void;
}

type ProviderFilter = "all" | ProviderChoice;
type AnswerModeFilter = "all" | "single" | "select_all";

interface HistoryFilters {
  courseId: string;
  provider: ProviderFilter;
  mode: AnswerModeFilter;
  from: string;
  to: string;
}

const EMPTY_FILTERS: HistoryFilters = {
  courseId: "all",
  provider: "all",
  mode: "all",
  from: "",
  to: "",
};

function dayLabel(value: string): string {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return "Today";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: date.getFullYear() !== today.getFullYear() ? "numeric" : undefined }).format(date);
}

function localDateBoundary(value: string, dayOffset = 0): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day + dayOffset);
}

function providerLabel(value: ProviderFilter): string {
  if (value === "all") return "All providers";
  return value === "nvidia" ? "NVIDIA" : value === "ollama" ? "Ollama" : "Auto";
}

function modeLabel(value: AnswerModeFilter): string {
  if (value === "all") return "All answer modes";
  return value === "select_all" ? "Select all that apply" : "One answer";
}

function hasActiveFilters(filters: HistoryFilters): boolean {
  return filters.courseId !== "all"
    || filters.provider !== "all"
    || filters.mode !== "all"
    || Boolean(filters.from)
    || Boolean(filters.to);
}

export function HistoryRail({ conversations, selectedId, mobileOpen, onSelect, onDelete, onClear, onCloseMobile }: HistoryRailProps) {
  const [search, setSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<HistoryFilters>(EMPTY_FILTERS);
  const filtersActive = hasActiveFilters(filters);
  const activeFilterCount = [
    filters.courseId !== "all",
    filters.provider !== "all",
    filters.mode !== "all",
    Boolean(filters.from),
    Boolean(filters.to),
  ].filter(Boolean).length;
  const invalidDateRange = Boolean(filters.from && filters.to && filters.from > filters.to);

  const filteredConversations = useMemo(() => {
    const searchTerm = search.trim().toLowerCase();
    return conversations.filter((item) => {
      if (searchTerm && !item.title.toLowerCase().includes(searchTerm)) return false;
      if (filters.courseId !== "all" && !(item.courseIds ?? []).includes(filters.courseId)) return false;
      if (filters.provider !== "all" && (item.providerChoice ?? "auto") !== filters.provider && item.actualProvider !== filters.provider) return false;
      if (filters.mode !== "all" && (filters.mode === "select_all") !== (item.selectAllThatApply ?? false)) return false;
      if (invalidDateRange) return false;
      const updatedAt = new Date(item.updatedAt);
      if (Number.isNaN(updatedAt.getTime())) return false;
      if (filters.from && updatedAt < localDateBoundary(filters.from)) return false;
      if (filters.to && updatedAt >= localDateBoundary(filters.to, 1)) return false;
      return true;
    });
  }, [conversations, filters, invalidDateRange, search]);

  const grouped = useMemo(() => {
    const result = new Map<string, ConversationSummary[]>();
    filteredConversations.forEach((item) => {
      const label = dayLabel(item.updatedAt);
      result.set(label, [...(result.get(label) ?? []), item]);
    });
    return result;
  }, [filteredConversations]);

  const clearFilters = () => setFilters(EMPTY_FILTERS);
  const hasCriteria = Boolean(search.trim()) || filtersActive;
  const matchingLabel = `${filteredConversations.length} matching ${filteredConversations.length === 1 ? "question" : "questions"}`;

  return (
    <>
      {mobileOpen && <button className="drawer-backdrop" aria-label="Close history" onClick={onCloseMobile} />}
      <aside className={`history-rail ${mobileOpen ? "mobile-open" : ""}`} aria-label="Question history">
        <div className="rail-title-row"><h2>History</h2><button className="icon-button mobile-only" onClick={onCloseMobile} aria-label="Close history"><CloseIcon /></button></div>
        <label className="search-field"><SearchIcon /><span className="sr-only">Find a question</span><input aria-label="Find a question" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a question" /></label>
        <div className="history-filter-actions">
          <button type="button" className={`history-filter-toggle ${filtersActive ? "active" : ""}`} onClick={() => setFiltersOpen((open) => !open)} aria-expanded={filtersOpen} aria-controls="history-filter-panel"><FilterIcon /> Filters{filtersActive && <span className="filter-count" aria-label={`${activeFilterCount} active filters`}>{activeFilterCount}</span>}</button>
          <span className="history-count" role="status" aria-live="polite">{matchingLabel}</span>
        </div>
        {filtersOpen && (
          <div className="history-filters" id="history-filter-panel">
            <div className="history-filter-heading"><span className="eyebrow">Refine history</span><button type="button" className="text-button history-filter-clear" onClick={clearFilters} disabled={!filtersActive}>Clear filters</button></div>
            <label className="history-filter-control">Course<select aria-label="Filter history by course" value={filters.courseId} onChange={(event) => setFilters((current) => ({ ...current, courseId: event.target.value }))}><option value="all">All courses</option>{COURSES.map((course) => <option key={course.id} value={course.id}>{course.id.replace("-", " ")}</option>)}</select></label>
            <label className="history-filter-control">Provider<select aria-label="Filter history by provider" value={filters.provider} onChange={(event) => setFilters((current) => ({ ...current, provider: event.target.value as ProviderFilter }))}><option value="all">{providerLabel("all")}</option><option value="auto">Auto</option><option value="nvidia">NVIDIA</option><option value="ollama">Ollama</option></select></label>
            <label className="history-filter-control">Answer mode<select aria-label="Filter history by answer mode" value={filters.mode} onChange={(event) => setFilters((current) => ({ ...current, mode: event.target.value as AnswerModeFilter }))}><option value="all">{modeLabel("all")}</option><option value="single">One answer</option><option value="select_all">Select all that apply</option></select></label>
            <div className="history-filter-dates"><label className="history-filter-control">From date<input type="date" aria-label="Filter history from date" value={filters.from} onChange={(event) => setFilters((current) => ({ ...current, from: event.target.value }))} /></label><label className="history-filter-control">To date<input type="date" aria-label="Filter history to date" value={filters.to} onChange={(event) => setFilters((current) => ({ ...current, to: event.target.value }))} aria-invalid={invalidDateRange} /></label></div>
            {invalidDateRange && <p className="history-filter-error" role="alert">Choose a “to” date on or after the “from” date.</p>}
          </div>
        )}
        <div className="history-list">
          {grouped.size === 0 ? (
            <div className="empty-history"><span aria-hidden="true">◇</span><h3>{hasCriteria ? "No matching questions" : "Your study trail starts here"}</h3><p>{invalidDateRange ? "Adjust the date range to see saved questions." : filtersActive ? "Clear filters or choose a different course, provider, mode, or date range." : search ? "Try another phrase." : "Questions you ask will be saved locally on Titan."}</p>{filtersActive && <button type="button" className="text-button empty-history-action" onClick={clearFilters}>Clear filters</button>}</div>
          ) : [...grouped].map(([label, items]) => (
            <section className="history-group" key={label} aria-label={label}>
              <h3>{label}</h3>
              {items.map((item) => (
                <div className={`history-row ${selectedId === item.id ? "selected" : ""}`} key={item.id}>
                  <button type="button" className="history-select" onClick={() => { onSelect(item.id); onCloseMobile(); }} aria-current={selectedId === item.id ? "page" : undefined}>
                    <span>{item.title}</span><time>{new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(item.updatedAt))}</time>
                  </button>
                  <button type="button" className="history-delete icon-button" onClick={() => onDelete(item)} aria-label={`Delete ${item.title}`}><TrashIcon /></button>
                </div>
              ))}
            </section>
          ))}
        </div>
        <button type="button" className="clear-history text-button" onClick={onClear} disabled={conversations.length === 0}><TrashIcon /> Clear history…</button>
      </aside>
    </>
  );
}
