import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const base = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

export const MenuIcon = (props: IconProps) => <svg {...base} {...props}><path d="M4 6h16M4 12h16M4 18h16" /></svg>;
export const PlusIcon = (props: IconProps) => <svg {...base} {...props}><path d="M12 5v14M5 12h14" /></svg>;
export const SendIcon = (props: IconProps) => <svg {...base} {...props}><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></svg>;
export const SearchIcon = (props: IconProps) => <svg {...base} {...props}><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>;
export const BookIcon = (props: IconProps) => <svg {...base} {...props}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></svg>;
export const TrashIcon = (props: IconProps) => <svg {...base} {...props}><path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 11v6M14 11v6" /></svg>;
export const CloseIcon = (props: IconProps) => <svg {...base} {...props}><path d="m6 6 12 12M18 6 6 18" /></svg>;
export const ChevronIcon = (props: IconProps) => <svg {...base} {...props}><path d="m9 18 6-6-6-6" /></svg>;
export const FilterIcon = (props: IconProps) => <svg {...base} {...props}><path d="M4 5h16l-6 7v5l-4 2v-7Z" /></svg>;
export const ExternalIcon = (props: IconProps) => <svg {...base} {...props}><path d="M14 5h5v5M10 14 19 5M19 14v5H5V5h5" /></svg>;
export const AlertIcon = (props: IconProps) => <svg {...base} {...props}><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></svg>;
