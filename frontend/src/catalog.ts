import type { Course, Source } from "./types";

export const COURSES: Course[] = [
  { id: "ITSC-1305", name: "Introduction to PC Operating Systems" },
  { id: "INEW-2330", name: "Comprehensive Software Project" },
  { id: "ITSE-1311", name: "Beginning Web Programming" },
  { id: "ITSE-2302", name: "Intermediate Web Programming" },
];

export const FALLBACK_SOURCES: Source[] = [
  { id: "parallel-operating-systems", title: "Guide to Parallel Operating Systems", course_ids: ["ITSC-1305"] },
  { id: "comptia-tech-plus", title: "CompTIA Tech+ Study Guide", course_ids: ["ITSC-1305"] },
  { id: "missing-link-web", title: "The Missing Link", course_ids: ["ITSE-1311", "ITSE-2302"] },
  { id: "clean-coder", title: "The Clean Coder", course_ids: ["INEW-2330"] },
];
