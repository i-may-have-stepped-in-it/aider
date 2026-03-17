
import os
import logging
import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import time

logger = logging.getLogger(__name__)

@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float

class SearchWebTool:
    """
    Search the web using Tavily API.
    Provides native search parity with Gemini/Kimi/Claude.
    """
    
    TAVILY_API_URL = "https://api.tavily.com/search"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY")
        
    def search(self, query: str, max_results: int = 5, search_depth: str = "advanced") -> Dict[str, Any]:
        """
        Execute search via Tavily API.
        """
        if not self.api_key:
            return {
                "success": False,
                "error": "Tavily API key not found. Please set TAVILY_API_KEY environment variable."
            }
            
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": search_depth,
            "include_answer": True,
            "include_images": False,
            "include_raw_content": False,
            "max_results": max_results,
        }
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self.TAVILY_API_URL, json=payload)
                response.raise_for_status()
                data = response.json()
                
                results = data.get("results", [])
                formatted_results = []
                for res in results:
                    formatted_results.append(
                        f"Title: {res.get('title')}\nURL: {res.get('url')}\nContent: {res.get('content')}\n"
                    )
                
                answer = data.get("answer")
                output = ""
                if answer:
                    output += f"Summary Answer: {answer}\n\n"
                
                output += "Search Results:\n" + "\n---\n".join(formatted_results)
                
                return {
                    "success": True,
                    "output": output,
                    "results_count": len(results)
                }
                
        except httpx.HTTPStatusError as e:
            logger.error(f"Tavily API error: {e.response.status_code} - {e.response.text}")
            return {
                "success": False,
                "error": f"Search API error: {e.response.status_code}"
            }
        except Exception as e:
            logger.exception("Search execution failed")
            return {
                "success": False,
                "error": f"Search failed: {str(e)}"
            }
