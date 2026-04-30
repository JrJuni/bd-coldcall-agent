import Link from "next/link";

type EmptyStateProps = {
  title: string;
  description?: string;
  ctaLabel?: string;
  ctaHref?: string;
};

export default function EmptyState({
  title,
  description,
  ctaLabel,
  ctaHref,
}: EmptyStateProps) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-white p-8 text-center text-sm">
      <p className="font-medium text-slate-700">{title}</p>
      {description && (
        <p className="mt-2 text-slate-500">{description}</p>
      )}
      {ctaLabel && ctaHref && (
        <Link
          href={ctaHref}
          className="mt-4 inline-block rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
        >
          {ctaLabel}
        </Link>
      )}
    </div>
  );
}
