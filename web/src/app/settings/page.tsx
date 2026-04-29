import StubPage from "@/components/StubPage";

export default function SettingsPage() {
  return (
    <StubPage
      title="Settings"
      ship="P10-7"
      description="API 키 (마스킹 표시), RAG (chunk·overlap·top_k), Search (max_articles_per_channel), Discovery (weights·tier_rules·competitors·intent_tiers·sector_leaders) 를 sub-tab 으로 분리해 yaml 직접 편집 없이 관리."
    />
  );
}
