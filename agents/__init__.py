from .analytics import AnalyticsAgent
from .notion_agent import NotionAgent
from .product import ProductAgent

AGENTS = {
    "analytics": AnalyticsAgent,
    "notion": NotionAgent,
    "product": ProductAgent,
}
