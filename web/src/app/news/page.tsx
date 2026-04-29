import StubPage from "@/components/StubPage";

export default function NewsPage() {
  return (
    <StubPage
      title="Daily News"
      ship="P10-5"
      description="RAG 시드에서 산업 키워드를 추출해 매일 아침 시장 동향 뉴스 10건을 가져옵니다. Sonnet 1회 호출로 짧은 코멘트가 붙고, 결과는 캐시되어 같은 날 재로드는 무료입니다."
    />
  );
}
