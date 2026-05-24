# Microservice Codebase: Inventory Service
class InventoryService:
    def __init__(self, db_client):
        self.db = db_client

    def deduct_stock(self, items):
        """
        Deducts stock balances for a given set of items.
        """
        for item in items:
            sku = item["sku"]
            quantity = item["qty"]
            # Perform DB inventory deduction query
            self.db.execute("UPDATE inventory SET stock = stock - ? WHERE sku = ?", (quantity, sku))
            
        return {
            "status": 200,
            "message": f"Successfully deducted {len(items)} items from stock inventory"
        }
