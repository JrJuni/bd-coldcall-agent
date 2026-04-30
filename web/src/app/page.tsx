import Link from "next/link";

const QUICK_LINKS = [
  {
    href: "/proposals/new",
    title: "새 제안서",
    description: "회사·산업·언어를 입력해 BD 제안서 초안을 즉시 생성.",
    accent: "bg-slate-900 text-white hover:bg-slate-800",
  },
  {
    href: "/discover",
    title: "Discovery",
    description: "RAG 기반 BD 타겟 발굴 — 6차원 점수 + weights 슬라이더 재계산.",
    accent: "border border-slate-300 bg-white hover:bg-slate-50",
  },
  {
    href: "/targets",
    title: "Targets 파이프라인",
    description: "등록된 회사 · 영업 단계 관리 · Proposal 점프.",
    accent: "border border-slate-300 bg-white hover:bg-slate-50",
  },
  {
    href: "/rag",
    title: "RAG Docs",
    description: "Namespace 별 docs 업로드 / 삭제 / 인덱싱 트리거.",
    accent: "border border-slate-300 bg-white hover:bg-slate-50",
  },
  {
    href: "/news",
    title: "Daily News",
    description: "RAG namespace + 시드 키워드로 Brave 뉴스 한 번에 모아 캐시.",
    accent: "border border-slate-300 bg-white hover:bg-slate-50",
  },
  {
    href: "/interactions",
    title: "사업 기록",
    description: "콜·미팅·메모 기록 (P10-6 작업 중).",
    accent: "border border-dashed border-slate-300 bg-white hover:bg-slate-50",
  },
];

export default function HomePage() {
  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-semibold">BD Cold-Call Agent</h1>
        <p className="mt-2 text-sm text-slate-500">
          타겟 발굴 → 제안서 → 콜 → 기록 까지의 BD 일상 운영을 한 화면에서 관리합니다.
          왼쪽 네비 또는 아래 카드로 이동하세요.
        </p>
      </header>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {QUICK_LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={`block rounded-lg p-5 shadow-sm transition ${link.accent}`}
          >
            <h2 className="text-lg font-semibold">{link.title}</h2>
            <p className="mt-2 text-sm opacity-90">{link.description}</p>
          </Link>
        ))}
      </div>
      <p className="text-xs text-slate-400">
        Home 6-박스 대시보드는 P10-8 에서 별도 합류 예정.
      </p>
    </div>
  );
}
