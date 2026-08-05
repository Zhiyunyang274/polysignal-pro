"""
Order Manager - Manage order lifecycle

Stub for Milestone 1 - full implementation in Milestone 2
"""

from polysignal.models.paper_trade import PaperOrder


class OrderManager:
    """Stub for order management"""

    def create_order(self, *args, **kwargs) -> PaperOrder:
        """Create order (stub)"""
        raise NotImplementedError("OrderManager not implemented in MVP")

    def cancel_order(self, order_id: str) -> bool:
        """Cancel order (stub)"""
        return False
