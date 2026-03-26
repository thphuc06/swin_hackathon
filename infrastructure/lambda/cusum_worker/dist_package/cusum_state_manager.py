"""
CUSUM State Manager: Persist and retrieve CUSUM detector state from database.

This module handles:
1. Loading saved CUSUM state from DB (for streaming continuity)
2. Saving updated state to DB after each transaction
3. Computing baseline statistics from transaction history
4. Deduplication and recovery patterns
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timezone


class CUSUMStateManager:
    """
    Persist CUSUM state to database between transactions.
    
    The detector processes streams, so state must survive process restarts.
    This manager loads/saves state to ensure continuity.
    """
    
    def __init__(self, db_connection: Any):
        """
        Initialize state manager with DB connection.
        
        Args:
            db_connection: Database connection (psycopg2, sqlalchemy, etc.)
                          Must support .execute() and .query() methods
        """
        self.db = db_connection
    
    def load_state(self, user_id: str, jar_id: str) -> Dict[str, Any]:
        """
        Load saved CUSUM state for a user/jar pair.
        
        Args:
            user_id: User identifier
            jar_id: Jar name (e.g., 'food', 'transport')
        
        Returns:
            Dictionary with:
                - cumsum_pos: Current S+ value
                - cumsum_neg: Current S- value
                - reference_mean: Baseline mean
                - reference_sigma: Baseline std dev
                - k_parameter: Slack parameter
                - h_parameter: Threshold parameter
                - transaction_count: Number of transactions processed
                - last_update_ts: Timestamp of last update
            
            Returns default zeros if no state found (first time).
        """
        try:
            # Query the tier1_cusum_state table
            query = """
                SELECT 
                    cumsum_pos, cumsum_neg, 
                    reference_mean, reference_sigma,
                    k_parameter, h_parameter,
                    transaction_count, last_updated_at
                FROM tier1_cusum_state
                WHERE user_id = %s AND jar_id = %s
                LIMIT 1
            """
            
            result = self.db.query(query, (user_id, jar_id))
            
            if result:
                row = result[0] if isinstance(result, list) else result
                return {
                    "cumsum_pos": float(row[0] or 0.0),
                    "cumsum_neg": float(row[1] or 0.0),
                    "reference_mean": float(row[2] or 0.0),
                    "reference_sigma": float(row[3] or 0.0),
                    "k_parameter": float(row[4] or 0.5),
                    "h_parameter": float(row[5] or 5.0),
                    "transaction_count": int(row[6] or 0),
                    "last_updated_at": str(row[7]) if row[7] else None,
                }
            
            # No existing state: return defaults (fresh detector)
            return {
                "cumsum_pos": 0.0,
                "cumsum_neg": 0.0,
                "reference_mean": 0.0,
                "reference_sigma": 0.0,
                "k_parameter": 0.5,
                "h_parameter": 5.0,
                "transaction_count": 0,
                "last_updated_at": None,
            }
        
        except Exception as e:
            print(f"[WARN] Failed to load CUSUM state: {e}")
            return {
                "cumsum_pos": 0.0,
                "cumsum_neg": 0.0,
                "reference_mean": 0.0,
                "reference_sigma": 0.0,
                "k_parameter": 0.5,
                "h_parameter": 5.0,
                "transaction_count": 0,
            }
    
    def save_state(
        self,
        user_id: str,
        jar_id: str,
        cumsum_pos: float,
        cumsum_neg: float,
        reference_mean: float,
        reference_sigma: float,
        k_parameter: float = 0.5,
        h_parameter: float = 5.0,
        drift_detected: bool = False,
        transaction_count: int = 0,
    ) -> bool:
        """
        Persist CUSUM state to database (insert or update).
        
        Args:
            user_id: User identifier
            jar_id: Jar name
            cumsum_pos: Current S+ value
            cumsum_neg: Current S- value
            reference_mean: Baseline mean
            reference_sigma: Baseline std dev
            k_parameter: Slack parameter
            h_parameter: Threshold parameter
            drift_detected: Whether drift was signaled
            transaction_count: Total transactions processed
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Upsert logic: insert if not exists, update if exists
            query_upsert = """
                INSERT INTO tier1_cusum_state (
                    user_id, jar_id,
                    cumsum_pos, cumsum_neg,
                    reference_mean, reference_sigma,
                    k_parameter, h_parameter,
                    drift_detected_up, drift_detected_down,
                    transaction_count, last_transaction_ts, last_updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (user_id, jar_id)
                DO UPDATE SET
                    cumsum_pos = EXCLUDED.cumsum_pos,
                    cumsum_neg = EXCLUDED.cumsum_neg,
                    reference_mean = EXCLUDED.reference_mean,
                    reference_sigma = EXCLUDED.reference_sigma,
                    k_parameter = EXCLUDED.k_parameter,
                    h_parameter = EXCLUDED.h_parameter,
                    drift_detected_up = EXCLUDED.drift_detected_up,
                    drift_detected_down = EXCLUDED.drift_detected_down,
                    transaction_count = EXCLUDED.transaction_count,
                    last_transaction_ts = NOW(),
                    last_updated_at = NOW()
            """
            
            self.db.execute(
                query_upsert,
                (
                    user_id, jar_id,
                    cumsum_pos, cumsum_neg,
                    reference_mean, reference_sigma,
                    k_parameter, h_parameter,
                    cumsum_pos > (h_parameter * reference_sigma),  # drift_up
                    cumsum_neg < -(h_parameter * reference_sigma),  # drift_down
                    transaction_count
                )
            )
            
            
            
            return True
        
        except Exception as e:
            print(f"[ERROR] Failed to save CUSUM state: {e}")
            return False
    
    def get_baseline_stats(
        self,
        user_id: str,
        jar_id: str,
        lookback_days: int = 30,
        min_samples: int = 5,
    ) -> Dict[str, float]:
        """
        Compute baseline mean and standard deviation from transaction history.
        
        Args:
            user_id: User identifier
            jar_id: Jar name
            lookback_days: Number of days to look back for history
            min_samples: Minimum transactions required
        
        Returns:
            Dictionary with:
                - mean: Average transaction amount
                - sigma: Standard deviation
                - sample_count: Number of transactions used
                
            Returns {'mean': 0.0, 'sigma': 0.0} if insufficient data
        """
        try:
            query = """
                SELECT 
                    COUNT(*) as count,
                    AVG(amount) as mean,
                    STDDEV_SAMP(amount) as sigma
                FROM transactions
                WHERE user_id = %s 
                  AND jar_id = %s
                  AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
                  AND amount > 0
            """
            
            result = self.db.query(query, (user_id, jar_id, lookback_days))
            
            if result:
                row = result[0] if isinstance(result, list) else result
                count = int(row[0] or 0)
                mean = float(row[1] or 0.0)
                sigma = float(row[2] or 0.0)
                
                # Need minimum samples for stats to be reliable
                if count >= min_samples:
                    return {
                        "mean": mean,
                        "sigma": max(sigma, 0.01),  # Avoid zero sigma
                        "sample_count": count,
                    }
            
            return {
                "mean": 0.0,
                "sigma": 0.0,
                "sample_count": 0,
            }
        
        except Exception as e:
            print(f"[WARN] Failed to compute baseline stats: {e}")
            return {
                "mean": 0.0,
                "sigma": 0.0,
                "sample_count": 0,
            }
    
    def get_recent_transactions(
        self,
        user_id: str,
        jar_id: str,
        limit: int = 100,
    ) -> list[float]:
        """
        Retrieve recent transaction amounts for debugging/analysis.
        
        Args:
            user_id: User identifier
            jar_id: Jar name
            limit: Maximum transactions to retrieve
        
        Returns:
            List of amounts in chronological order
        """
        try:
            query = """
                SELECT amount
                FROM transactions
                WHERE user_id = %s AND jar_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            
            result = self.db.query(query, (user_id, jar_id, limit))
            
            if result:
                # Reverse to get chronological order
                return [float(row[0]) for row in reversed(result)]
            
            return []
        
        except Exception as e:
            print(f"[WARN] Failed to retrieve recent transactions: {e}")
            return []
    
    def get_monthly_spend(self, user_id: str, lookback_days: int = 30) -> float:
        """
        Tổng debit của user trong N ngày gần nhất, tính trên TẤT CẢ jar.
        Dùng ALL jar vì income là thu nhập chung, không gắn với jar cụ thể.

        Args:
            user_id: User identifier
            lookback_days: Số ngày nhìn lại (mặc định 30)

        Returns:
            Tổng số tiền đã chi (VND), trả về 0.0 nếu không có data
        """
        try:
            result = self.db.query(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE user_id = %s
                  AND direction = 'debit'
                  AND occurred_at >= NOW() - INTERVAL '%s days'
                """,
                (user_id, lookback_days),
            )
            return float(result[0][0]) if result else 0.0
        except Exception as e:
            print(f"[WARN] Failed to compute monthly_spend: {e}")
            return 0.0

    def cleanup_old_states(self, days_inactive: int = 90) -> int:
        """
        Remove CUSUM states that haven't been updated recently.
        
        Args:
            days_inactive: Remove states inactive for this many days
        
        Returns:
            Number of states removed
        """
        try:
            query = """
                DELETE FROM tier1_cusum_state
                WHERE last_updated_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
                RETURNING id
            """
            
            result = self.db.execute(query, (days_inactive,))
            # Most drivers return row count
            return result.rowcount if hasattr(result, 'rowcount') else 0
        
        except Exception as e:
            print(f"[WARN] Failed to cleanup old states: {e}")
            return 0


# Mock database connection for testing (no real DB required)
class MockDBConnection:
    """In-memory mock database for standalone testing."""
    
    def __init__(self):
        self.cusum_state_table: Dict[tuple, Dict[str, Any]] = {}
        self.transactions_table: list[Dict[str, Any]] = []
    
    def query(self, sql: str, params: tuple) -> list[Any]:
        """Mock query implementation."""
        if "cusum_state" in sql and "SELECT" in sql:
            key = (params[0], params[1])
            if key in self.cusum_state_table:
                row = self.cusum_state_table[key]
                return [(
                    row["cumsum_pos"],
                    row["cumsum_neg"],
                    row["reference_mean"],
                    row["reference_sigma"],
                    row["k_parameter"],
                    row["h_parameter"],
                    row["transaction_count"],
                    row["last_updated_at"],
                )]
            return []
        
        if "transactions" in sql and "AVG" in sql:
            # Filter transactions by user/jar
            filtered = [
                t for t in self.transactions_table
                if t["user_id"] == params[0] and t["jar_id"] == params[1]
            ]
            if filtered:
                amounts = [t["amount"] for t in filtered]
                n = len(amounts)
                mean = sum(amounts) / n
                variance = sum((x - mean) ** 2 for x in amounts) / max(n - 1, 1)
                sigma = variance ** 0.5
                return [(n, mean, sigma)]
            return [(0, 0.0, 0.0)]
        
        # Handle SELECT amount FROM transactions queries
        if "transactions" in sql and "SELECT" in sql and "amount" in sql:
            # Filter by user_id and jar_id
            if len(params) >= 2:
                user_id, jar_id = params[0], params[1]
                filtered = [
                    t for t in self.transactions_table
                    if t.get("user_id") == user_id and t.get("jar_id") == jar_id
                ]
                return [(t["amount"],) for t in filtered]
        
        return []
    
    def execute(self, sql: str, params: tuple) -> Any:
        """Mock execute implementation."""
        if "cusum_state" in sql and "INSERT" in sql:
            key = (params[0], params[1])
            self.cusum_state_table[key] = {
                "cumsum_pos": params[2],
                "cumsum_neg": params[3],
                "reference_mean": params[4],
                "reference_sigma": params[5],
                "k_parameter": params[6],
                "h_parameter": params[7],
                "transaction_count": params[10],
                "last_updated_at": datetime.now(timezone.utc).isoformat(),
            }
            return self
        
        return self
    
    @property
    def rowcount(self) -> int:
        return 1


if __name__ == "__main__":
    # Standalone test of state manager with mock DB
    print("=== CUSUM State Manager Demo ===\n")
    
    db = MockDBConnection()
    manager = CUSUMStateManager(db)
    
    # Add mock transaction data
    db.transactions_table = [
        {"user_id": "user1", "jar_id": "food", "amount": 100_000},
        {"user_id": "user1", "jar_id": "food", "amount": 110_000},
        {"user_id": "user1", "jar_id": "food", "amount": 95_000},
        {"user_id": "user1", "jar_id": "food", "amount": 105_000},
        {"user_id": "user1", "jar_id": "food", "amount": 102_000},
    ]
    
    # Load initial state (should be zeros - first time)
    state = manager.load_state("user1", "food")
    print(f"Initial state: {state}")
    
    # Compute baseline from history
    baseline = manager.get_baseline_stats("user1", "food", lookback_days=90)
    print(f"Baseline stats: {baseline}\n")
    
    # Save new state
    success = manager.save_state(
        "user1", "food",
        cumsum_pos=5_000,
        cumsum_neg=0.0,
        reference_mean=baseline["mean"],
        reference_sigma=baseline["sigma"],
        drift_detected=False,
        transaction_count=5,
    )
    print(f"Saved: {success}")
    
    # Load updated state
    updated = manager.load_state("user1", "food")
    print(f"Updated state: {updated}")
