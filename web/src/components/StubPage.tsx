type StubPageProps = {
  title: string;
  ship: string;
  description: string;
};

export default function StubPage({ title, ship, description }: StubPageProps) {
  return (
    <div className="max-w-2xl">
      <h1 className="mb-2 text-2xl font-semibold">{title}</h1>
      <p className="mb-6 text-sm text-slate-500">Ships in {ship}</p>
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm leading-relaxed text-slate-700">
        {description}
      </div>
    </div>
  );
}
