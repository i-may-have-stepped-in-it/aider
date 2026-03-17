
import os
import re
import tempfile
import webbrowser
from typing import Optional
from .base import Skill, SkillContext, SkillResult

class ArtifactPreviewSkill(Skill):
    """
    Detect and preview visual artifacts (Mermaid, HTML, SVG).
    Parity with Claude Artifacts.
    """

    name = "artifact-preview"
    description = "Automatically preview visual artifacts (Mermaid, HTML, SVG)."

    def __init__(self, context: Optional[SkillContext] = None):
        super().__init__(context)
        
    async def execute(self, content: str) -> SkillResult:
        """Scan content for renderable blocks and open them."""
        # 1. Mermaid Detection
        mermaid_match = re.search(r'```mermaid\n(.*?)```', content, re.DOTALL)
        if mermaid_match:
            mermaid_code = mermaid_match.group(1).strip()
            self.preview_mermaid(mermaid_code)
            return SkillResult(success=True, output="Mermaid diagram previewed in browser.")
            
        # 2. HTML/SVG Detection
        html_match = re.search(r'```html\n(.*?)```', content, re.DOTALL)
        if html_match:
            html_code = html_match.group(1).strip()
            self.preview_html(html_code)
            return SkillResult(success=True, output="HTML previewed in browser.")
            
        return SkillResult(success=True, output="No previewable artifacts found.")

    def preview_mermaid(self, code: str):
        """Render mermaid via mermaid.live or a local template."""
        # Simplified: Use mermaid.ink for direct image URL preview
        import urllib.parse
        encoded = urllib.parse.quote(code)
        url = f"https://mermaid.ink/img/{encoded}"
        self.output(f"Opening Mermaid diagram: {url}")
        webbrowser.open(url)

    def preview_html(self, html: str):
        """Save HTML to temp file and open in browser."""
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            f.write(html.encode("utf-8"))
            path = f.name
        self.output(f"Opening HTML preview: {path}")
        webbrowser.open(f"file://{os.path.abspath(path)}")

    def preview_svg(self, svg: str):
        """Save SVG to temp file and open in browser."""
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            f.write(svg.encode("utf-8"))
            path = f.name
        self.output(f"Opening SVG preview: {path}")
        webbrowser.open(f"file://{os.path.abspath(path)}")
