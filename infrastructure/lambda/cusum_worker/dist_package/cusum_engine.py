"""
CUSUM (Cumulative Sum Control Chart) Engine for Streaming Anomaly Detection

This module implements a custom CUSUM detector for real-time spending drift detection
in fintech applications. Unlike the Kats library (which has dependency conflicts),
this is a lightweight, deterministic implementation with no external dependencies
beyond standard library.

Algorithm Reference:
- CUSUM Control Charts: https://en.wikipedia.org/wiki/CUSUM
- Page, E. S. (1954): "Continuous inspection schemes"
- Lucas & Saccucci (1990): "Exponentially weighted moving average control schemes"

Use Case (Tier1):
- Detect spending pattern shifts per jar in real-time as transactions arrive
- Stream-based: process transactions one-at-a-time, maintain cumulative state
- Deterministic: no random seeds, reproducible results
- Auditable: parameters and thresholds clearly defined

Parameters:
- reference_mean (μ): baseline mean spending per jar (from historical data)
- reference_sigma (σ): variance estimate
- k (slack): allowance for variation = k_factor * σ (typically 0.5-1.0)
- h (threshold): alert threshold = h_factor * σ (typically 4-6 sigma)

State:
- CUSUM+ (S+): accumulates upward deviations (increases overspending detection)
- CUSUM- (S-): accumulates downward deviations (budget underspending detection)
- Reset to 0 when drift detected
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Tuple


@dataclass
class CUSUMState:
    """Current state of a CUSUM detector."""
    
    cumsum_pos: float = 0.0  # S+: upward drift accumulator
    cumsum_neg: float = 0.0  # S-: downward drift accumulator
    reference_mean: float = 0.0
    reference_sigma: float = 0.0
    k_parameter: float = 0.5
    h_parameter: float = 5.0
    
    drift_detected_up: bool = False
    drift_detected_down: bool = False
    spike_detected: bool = False
    
    transaction_count: int = 0
    last_update_ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def __repr__(self) -> str:
        return (
            f"CUSUMState(S+={self.cumsum_pos:.2f}, S-={self.cumsum_neg:.2f}, "
            f"drift_up={self.drift_detected_up}, drift_down={self.drift_detected_down}, "
            f"spike={self.spike_detected})"
        )


class CUSUMDetector:
    """
    Cumulative Sum Control Chart detector for streaming anomaly detection.
    
    Example:
        >>> detector = CUSUMDetector(reference_mean=100.0, sigma=20.0)
        >>> state, drift = detector.update(105.0)  # Normal transaction
        >>> print(drift)
        False
        >>> state, drift = detector.update(250.0)  # Spike
        >>> print(drift)
        True  # Drift detected!
    """
    
    def __init__(
        self,
        reference_mean: float,
        sigma: float,
        k_factor: float = 0.5,
        h_factor: float = 5.0,
        z_score_threshold: float = 4.0,
    ):
        """
        Initialize CUSUM detector.
        
        Args:
            reference_mean: Baseline mean (e.g., avg daily spending on jar)
            sigma: Standard deviation (spending variability)
            k_factor: Slack parameter multiplier (default 0.5 * sigma)
                      Smaller k → more sensitive to deviations
            h_factor: Threshold parameter multiplier (default 5.0 * sigma)
                      Smaller h → alert threshold closer, triggers faster
            z_score_threshold: Threshold to bypass CUSUM for extreme spikes (default 4.0).
                               Set to 0 to disable hybrid filtering.
        
        Typical configurations:
            - Sensitive (lower latency):   k_factor=0.25, h_factor=3.0
            - Balanced (default):           k_factor=0.50, h_factor=5.0
            - Conservative (fewer false positives): k_factor=1.0, h_factor=8.0
        """
        self.reference_mean = float(reference_mean)
        self.sigma = max(float(sigma), 0.01)  # Avoid division by zero
        self.k_factor = float(k_factor)
        self.h_factor = float(h_factor)
        self.z_score_threshold = float(z_score_threshold)
        
        # Compute actual parameters
        self.k = self.k_factor * self.sigma
        self.h = self.h_factor * self.sigma
        
        # State
        self.cumsum_pos = 0.0
        self.cumsum_neg = 0.0
        self.transaction_count = 0
    
    def update(self, value: float) -> Tuple[CUSUMState, bool]:
        """
        Process new transaction value and update CUSUM state.
        
        Args:
            value: Transaction amount (e.g., spending in VND)
        
        Returns:
            (state, drift_detected): Updated state and whether drift was detected
        
        Algorithm:
            deviation = value - reference_mean
            S+ = max(0, S+ + deviation - k)  # Upward drift
            S- = min(0, S- + deviation + k)  # Downward drift
            drift_detected = S+ > h OR S- < -h
            if drift_detected:
                reset S+, S- to 0
        """
        value = float(value)
        
        # Compute deviation from baseline
        deviation = value - self.reference_mean
        
        # Check Hybrid Spike Filter (Z-Score)
        is_spike = False
        drift_up = False
        drift_down = False
        drift_detected = False
        
        if self.z_score_threshold > 0 and abs(deviation) > self.z_score_threshold * self.sigma:
            is_spike = True
            # If it's a massive spike, we DO NOT update the CUSUM accumulators 
            # to avoid poisoning the baseline trend model. We still increment count.
        else:
            # Update CUSUM+ (detects sustained increase in spending)
            self.cumsum_pos = max(0.0, self.cumsum_pos + deviation - self.k)
            
            # Update CUSUM- (detects sustained decrease in spending)
            self.cumsum_neg = min(0.0, self.cumsum_neg + deviation + self.k)
            
            # Check for drift condition
            drift_up = self.cumsum_pos > self.h
            drift_down = self.cumsum_neg < -self.h
            drift_detected = drift_up or drift_down
            
            # Reset accumulators on detection (for next alarm)
            if drift_detected:
                self.cumsum_pos = 0.0
                self.cumsum_neg = 0.0
        
        # Increment transaction count
        self.transaction_count += 1
        
        # Build state object
        state = CUSUMState(
            cumsum_pos=self.cumsum_pos,
            cumsum_neg=self.cumsum_neg,
            reference_mean=self.reference_mean,
            reference_sigma=self.sigma,
            k_parameter=self.k_factor,
            h_parameter=self.h_factor,
            drift_detected_up=drift_up,
            drift_detected_down=drift_down,
            spike_detected=is_spike,
            transaction_count=self.transaction_count,
        )
        
        return state, drift_detected
    
    def get_state(self) -> CUSUMState:
        """Get current CUSUM state without processing new value."""
        return CUSUMState(
            cumsum_pos=self.cumsum_pos,
            cumsum_neg=self.cumsum_neg,
            reference_mean=self.reference_mean,
            reference_sigma=self.sigma,
            k_parameter=self.k_factor,
            h_parameter=self.h_factor,
            drift_detected_up=self.cumsum_pos > self.h,
            drift_detected_down=self.cumsum_neg < -self.h,
            transaction_count=self.transaction_count,
        )
    
    def batch_update(self, values: list[float]) -> tuple[CUSUMState, list[bool]]:
        """
        Process multiple transaction values sequentially.
        
        Args:
            values: List of transaction amounts
        
        Returns:
            (final_state, drift_flags): Final state and bool per value
        """
        drift_flags = []
        for value in values:
            _, drift = self.update(value)
            drift_flags.append(drift)
        
        return self.get_state(), drift_flags
    
    def reset(self) -> None:
        """Reset detector state (start fresh)."""
        self.cumsum_pos = 0.0
        self.cumsum_neg = 0.0
        self.transaction_count = 0


def estimate_baseline_stats(
    transactions: list[float],
    min_samples: int = 5,
) -> tuple[float, float]:
    """
    Estimate baseline mean and standard deviation from transaction history.
    
    Args:
        transactions: Historical transaction amounts
        min_samples: Minimum samples required (returns 0, 0 if insufficient)
    
    Returns:
        (mean, std_dev): Baseline statistics
    """
    if not transactions or len(transactions) < min_samples:
        return 0.0, 0.0
    
    values = [float(x) for x in transactions]
    
    # Mean
    mean = sum(values) / len(values)
    
    # Sample standard deviation (N-1)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    std_dev = variance ** 0.5
    
    return mean, std_dev


class CUSUMTimeSeriesDetector(CUSUMDetector):
    """
    Enhanced CUSUM for time-series anomaly detection.
    Operates on aggregated windows (like weekly rolling sum), tracking history.
    """
    
    def __init__(self, reference_mean: float, sigma: float, k_factor: float=0.5, h_factor: float=5.0, z_score_threshold: float=4.0):
        super().__init__(reference_mean, sigma, k_factor, h_factor, z_score_threshold)
        self.history: list[dict] = []
    
    def update_series(self, value: float, timestamp: str) -> tuple[CUSUMState, bool, dict]:
        """
        Process new aggregated value.
        
        Args:
            value: Aggregated value (e.g., daily total, 7-day rolling total)
            timestamp: ISO string for this data point
            
        Returns:
            (state, drift_detected, anomaly_info)
        """
        state, drift_detected = super().update(value)
        
        # If drift detected, cumsum_pos was >= h in the current step (before reset)
        if state.drift_detected_up or state.drift_detected_down:
            effective_cumsum = self.h * 1.5  # Proxy value guaranteed to be > h
        else:
            effective_cumsum = state.cumsum_pos if state.cumsum_pos > 0 else abs(state.cumsum_neg)
        
        # Calculate extended info
        confidence = min(1.0, effective_cumsum / (2 * self.h)) if self.h > 0 else 0.0
        
        anomaly_info = {
            "confidence": confidence,
            "severity": self._get_severity(effective_cumsum, state.spike_detected),
            "type": "sudden_spike" if state.spike_detected else self._get_drift_type(value, state),
            "recommendation": self._get_recommendation(effective_cumsum, state.spike_detected)
        }
        
        self.history.append({
            "timestamp": timestamp,
            "value": value,
            "cumsum_pos": state.cumsum_pos,
            "anomaly_info": anomaly_info
        })
        
        return state, drift_detected, anomaly_info
        
    def _get_severity(self, cumsum_value: float, is_spike: bool) -> str:
        if is_spike:
            return "critical"
        if cumsum_value < self.h * 0.5:
            return "low"
        elif cumsum_value < self.h * 0.8:
            return "medium"
        return "high"
        
    def _get_drift_type(self, value: float, state: CUSUMState) -> str:
        if state.drift_detected_up:
            return "gradual_increase"
        if state.drift_detected_down:
            return "gradual_decrease"
        return "stable"
        
    def _get_recommendation(self, cumsum_value: float, is_spike: bool) -> str:
        severity = self._get_severity(cumsum_value, is_spike)
        
        if is_spike:
            return "🚨 CRITICAL: Extraordinary extreme spending detected right now. Immediate review required."
        if severity == "high":
            return "⚠️ Budget adjustment strongly recommended. Your spending pattern has shifted."
        elif severity == "medium":
            return "Your spending shows an upward trend against budget. Consider reviewing."
        return "Minor variation detected. Keep monitoring."


if __name__ == "__main__":
    # Simple demonstration
    print("=== CUSUM Detector Demo ===\n")
    
    # Scenario: jar spending typically 100k ± 20k per day
    detector = CUSUMDetector(
        reference_mean=100_000,
        sigma=20_000,
        k_factor=0.5,
        h_factor=5.0,
    )
    
    print(f"Baseline: mean={detector.reference_mean:.0f}, sigma={detector.sigma:.0f}")
    print(f"Parameters: k={detector.k:.0f}, h={detector.h:.0f}\n")
    
    # Process transaction sequence
    transactions = [
        100_000,  # Normal
        109_000,  # Normal
        118_000,  # Normal
        127_000,  # Slightly elevated
        136_000,  # Still normal range
        145_000,  # Higher
        154_000,  # Even higher -> DRIFT!
    ]
    
    for txn in transactions:
        state, drift = detector.update(txn)
        status = "🔴 DRIFT DETECTED!" if drift else "✅ Normal"
        print(f"Txn: {txn/1000:.0f}k | S+: {state.cumsum_pos/1000:.1f}k | S-: {state.cumsum_neg/1000:.1f}k | {status}")
    
    print(f"\nTotal transactions: {detector.transaction_count}")
