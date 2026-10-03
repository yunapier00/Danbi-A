import { useId } from "react";

/** 단비(단 비) 로고: 빗방울. 장식용이므로 스크린리더에서는 숨긴다. */
export function Logo({ size = 28 }: { size?: number }) {
  const id = useId();
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo">
      <defs>
        <linearGradient id={`${id}-g`} x1="8" y1="2" x2="26" y2="30" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--logo-1, #38bdf8)" />
          <stop offset="1" stopColor="var(--logo-2, #1d4ed8)" />
        </linearGradient>
      </defs>
      <path d="M16 2.5c-.4 0-.8.2-1 .6C12.3 7.4 6 15.2 6 20a10 10 0 0 0 20 0c0-4.8-6.3-12.6-9-16.9a1.2 1.2 0 0 0-1-.6Z"
            fill={`url(#${id}-g)`} />
      <path d="M11.5 20.5a4.5 4.5 0 0 0 4.5 4.5" fill="none" stroke="#fff" strokeOpacity=".75" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
