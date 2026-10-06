/** Google 로그인 버튼. Google 스크립트 없이 서버의 /api/auth/login으로 가는 링크다 (CSP 'self' 유지). */
export function GoogleButton({ next = "/", label = "Google 계정으로 로그인" }: { next?: string; label?: string }) {
  return (
    <a className="google-btn" href={`/api/auth/login?next=${encodeURIComponent(next)}`}>
      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
      </svg>
      <span>{label}</span>
    </a>
  );
}

export const LOGIN_ERRORS: Record<string, string> = {
  domain: "단국대학교 Google 계정(@dankook.ac.kr)으로만 로그인할 수 있어요.",
  unverified: "이메일 인증이 끝나지 않은 Google 계정이에요.",
  cancelled: "로그인을 취소했어요.",
  blocked: "이용이 제한된 계정이에요.",
  state: "로그인 시간이 지났거나 요청이 올바르지 않아요. 다시 시도해 주세요.",
  token: "로그인 정보를 확인하지 못했어요. 다시 시도해 주세요.",
  google: "Google 로그인 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.",
};
