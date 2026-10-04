import mark from "../assets/danbi-mark.png";
import wordmark from "../assets/danbi-wordmark.png";

/** 단비 글자 로고 ("Danbi"). 원본: 프로젝트 루트의 Danbi_image.png에서 글자만 투명 배경으로 뽑은 것. */
export function Logo({ height = 24 }: { height?: number }) {
  return <img src={wordmark} height={height} alt="단비" className="logo" draggable={false} />;
}

/** 정사각형 자리(답변 아바타 등)에 쓰는 첫 글자 D. 장식용이므로 스크린리더에서는 숨긴다. */
export function LogoMark({ size = 18 }: { size?: number }) {
  return <img src={mark} width={size} height={size} alt="" aria-hidden="true" className="logo-mark" draggable={false} />;
}
