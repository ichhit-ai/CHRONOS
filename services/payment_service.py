# Microservice Codebase: Payment Gateway Integration Service
import time

class PaymentService:
    def __init__(self, db_client, stripe_client):
        self.db = db_client
        self.stripe = stripe_client

    def capture_charge(self, amount):
        """
        Processes credit card capture and logs the transactions.
        
        CRITICAL ANTI-PATTERN: Calling self.stripe.charge() which performs a slow 
        external network HTTP call INSIDE the database transaction block holding the lock!
        Under high database thread usage, this saturates the connection pool and results in
        PGSQL Lock Wait Timeouts.
        """
        # Starting atomic transaction context (holds table/row locks)
        with self.db.transaction() as tx:
            # 1. Prepare payment entry
            tx.execute("INSERT INTO payment_audit VALUES ('INIT', ?)", (amount,))
            
            # 2. Make SLOW network call to external payment provider while holding the DB transaction open!
            # Under payment_gateway_down or high db load, this slow HTTP request takes 3000ms+
            stripe_res = self.stripe.charge(amount)
            
            if stripe_res["status"] != 200:
                tx.rollback()
                return {"status": 500, "error": "External bank gateway timeout"}
                
            # 3. Finalize payment record
            tx.execute("UPDATE payment_audit SET state = 'CAPTURED' WHERE amount = ?", (amount,))
            
        return {
            "status": 200,
            "charge_id": stripe_res["charge_id"],
            "message": "Payment charged and committed to database successfully"
        }
