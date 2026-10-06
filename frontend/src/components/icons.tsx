// 인라인 SVG 아이콘 (아이콘 라이브러리 없이). currentColor를 따르고 장식용이라 aria-hidden.
import type { SVGProps } from "react";

const base = (size: number): SVGProps<SVGSVGElement> => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true,
});

export const MenuIcon = ({ size = 18 }: { size?: number }) => (
  <svg {...base(size)}><path d="M4 6h16" /><path d="M4 12h16" /><path d="M4 18h16" /></svg>
);
export const ChatIcon = ({ size = 15 }: { size?: number }) => (
  <svg {...base(size)}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" /></svg>
);
export const CloseIcon = ({ size = 18 }: { size?: number }) => (
  <svg {...base(size)}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>
);
export const SendIcon = ({ size = 18 }: { size?: number }) => (
  <svg {...base(size)}><path d="M12 19V5" /><path d="m5 12 7-7 7 7" /></svg>
);
export const PlusIcon = ({ size = 16 }: { size?: number }) => (
  <svg {...base(size)}><path d="M12 5v14" /><path d="M5 12h14" /></svg>
);
export const LinkIcon = ({ size = 14 }: { size?: number }) => (
  <svg {...base(size)}><path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5" /><path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.5" /></svg>
);
export const ExternalIcon = ({ size = 13 }: { size?: number }) => (
  <svg {...base(size)}><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" /></svg>
);
export const ClockIcon = ({ size = 13 }: { size?: number }) => (
  <svg {...base(size)}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
);
export const SearchIcon = ({ size = 13 }: { size?: number }) => (
  <svg {...base(size)}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
);
export const ThumbUpIcon = ({ size = 15 }: { size?: number }) => (
  <svg {...base(size)}><path d="M7 10v11" /><path d="M15 5.9 14 10h5.8a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 18.4 21H7V10l4.5-7.4a1.6 1.6 0 0 1 2.9.9Z" /></svg>
);
export const ThumbDownIcon = ({ size = 15 }: { size?: number }) => (
  <svg {...base(size)}><path d="M17 14V3" /><path d="M9 18.1 10 14H4.2a2 2 0 0 1-2-2.3l1.4-7A2 2 0 0 1 5.6 3H17v11l-4.5 7.4a1.6 1.6 0 0 1-2.9-.9Z" /></svg>
);
export const CheckIcon = ({ size = 14 }: { size?: number }) => (
  <svg {...base(size)}><path d="M20 6 9 17l-5-5" /></svg>
);
export const AlertIcon = ({ size = 15 }: { size?: number }) => (
  <svg {...base(size)}><path d="M12 9v4" /><path d="M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></svg>
);
