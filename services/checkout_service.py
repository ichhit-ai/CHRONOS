# Microservice Codebase: Checkout Controller
class CheckoutService:
    def __init__(self, auth_client, inventory_client, payment_client):
        self.auth = auth_client
        self.inventory = inventory_client
        self.payment = payment_client

    def process_checkout(self, token, order_data):
        """
        Coordinates JWT Auth check, inventory decrement, and payment capture.
        """
        # 1. Verify User Token
        auth_res = self.auth.verify_token(token)
        if auth_res["status"] != 200:
            return {"status": 401, "error": "Authentication failure: " + auth_res.get("error")}

        # 2. Deduct Inventory Stock
        inv_res = self.inventory.deduct_stock(order_data["items"])
        if inv_res["status"] != 200:
            return {"status": 500, "error": "Inventory deduction failed"}

        # 3. Process Payment Charge
        pay_res = self.payment.capture_charge(order_data["amount"])
        if pay_res["status"] != 200:
            return {"status": 500, "error": "Payment capture failed: " + pay_res.get("error")}

        return {
            "status": 200,
            "order_id": "ord_887122",
            "message": "Checkout processed successfully"
        }
