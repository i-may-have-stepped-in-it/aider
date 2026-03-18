from .base import ParallelSkill, SkillResult


class DelegatedWebSkill(ParallelSkill):
    """
    Skill that delegates web search and scraping to the upstream OpenClaw Agent.
    Targets the '@speed' tier with 'openclaw:search' agent identity.
    """

    name = "web_delegation"
    description = "Delegate web search and scraping to the upstream OpenClaw agent"
    version = "1.1.0"

    async def _execute_impl(self, action: str, **kwargs) -> SkillResult:
        if action == "search":
            return await self.search(kwargs.get("query", ""))
        elif action == "scrape":
            return await self.scrape(kwargs.get("url", ""))
        return SkillResult(success=False, error=f"Unknown action: {action}")

    async def search(self, query: str) -> SkillResult:
        """Ask the upstream OpenClaw search agent to perform a search."""
        self.update_progress(f"Delegating search to OpenClaw: {query}")

        prompt = (
            f"Please perform a comprehensive web search for the following query: '{query}'\n\n"
            "Return the results in a clear markdown format."
        )

        # Target the OpenClaw search-enabled agent via the model name
        results = await self.execute_parallel(
            [{"name": "upstream_search", "prompt": prompt, "model": "@speed/openclaw:search"}]
        )

        return results[0]

    async def scrape(self, url: str) -> SkillResult:
        """Ask the upstream OpenClaw browse agent to scrape a URL."""
        self.update_progress(f"Delegating scrape to OpenClaw: {url}")

        prompt = (
            f"Please visit and extract the content from this URL: {url}\n\n"
            "Provide a readable markdown summary of the page content."
        )

        results = await self.execute_parallel(
            [{"name": "upstream_scrape", "prompt": prompt, "model": "@speed/openclaw:browse"}]
        )

        return results[0]
