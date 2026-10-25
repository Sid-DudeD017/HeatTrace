"""Lightweight TinyTemperatureLSTM architecture and causal forecast baselines for HeatTrace Phase 4."""

from __future__ import annotations

from typing import Any
import numpy as np

# Optional ML import
try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    torch = None
    nn = None


# ---------------------------------------------------------------------------
# Causal Baselines
# ---------------------------------------------------------------------------

def forecast_last_observation(X_raw_temp: np.ndarray, horizon: int = 24) -> np.ndarray:
    """Repeat observed temperature at t-1 for all 24 horizons.

    Parameters:
    - X_raw_temp: shape [N, 72] or [72] of unscaled historical temperatures.
                  The last element (index -1) corresponds to t-1.
    - horizon: number of forecast steps (default 24).

    Returns:
    - shape [N, 24] or [24]
    """
    arr = np.asarray(X_raw_temp, dtype=np.float32)
    if arr.ndim == 1:
        last_val = arr[-1]
        return np.full((horizon,), last_val, dtype=np.float32)
    elif arr.ndim == 2:
        last_vals = arr[:, -1:]  # shape [N, 1]
        return np.repeat(last_vals, horizon, axis=1)
    else:
        raise ValueError(f"Expected 1D or 2D array, got shape {arr.shape}")


def forecast_same_hour_previous_day(X_raw_temp: np.ndarray, horizon: int = 24) -> np.ndarray:
    """Forecast t+h from the observed temperature at t+h-24.

    All required values must be historical at origin t:
    For h = 0 .. 23:
      h=0  -> target t+0  -> lag is (t+0)-24 = t-24 -> historical index 72 - 24 = 48
      h=1  -> target t+1  -> lag is (t+1)-24 = t-23 -> historical index 72 - 23 = 49
      ...
      h=23 -> target t+23 -> lag is (t+23)-24 = t-1 -> historical index 72 - 1 = 71

    Notice that all 24 horizons map to historical indices 48 through 71 (t-24 through t-1).
    All required values are strictly historical before origin t.

    Parameters:
    - X_raw_temp: shape [N, 72] or [72] of unscaled historical temperatures.
    """
    arr = np.asarray(X_raw_temp, dtype=np.float32)
    if arr.ndim == 1:
        if len(arr) < 24:
            raise ValueError(f"Need at least 24 lookback steps, got {len(arr)}")
        return arr[-24:].copy()
    elif arr.ndim == 2:
        if arr.shape[1] < 24:
            raise ValueError(f"Need at least 24 lookback steps, got {arr.shape[1]}")
        return arr[:, -24:].copy()
    else:
        raise ValueError(f"Expected 1D or 2D array, got shape {arr.shape}")


def forecast_ewma(
    X_raw_temp: np.ndarray,
    alpha: float = 0.20,
    horizon: int = 24,
) -> np.ndarray:
    """Causal Exponentially Weighted Moving Average (EWMA) forecast with fixed alpha=0.20.

    Computes state from historical observations only:
      s_0 = x_0
      s_k = alpha * x_k + (1 - alpha) * s_{k-1}
    The causal forecast for all 24 horizons is the terminal state s_{lookback-1} (at t-1).

    Parameters:
    - X_raw_temp: shape [N, 72] or [72] of unscaled historical temperatures.
    - alpha: smoothing factor (fixed 0.20 per contract, not tuned).
    """
    arr = np.asarray(X_raw_temp, dtype=np.float32)

    def _single_ewma(series: np.ndarray) -> float:
        s = series[0]
        for val in series[1:]:
            s = alpha * val + (1.0 - alpha) * s
        return float(s)

    if arr.ndim == 1:
        final_s = _single_ewma(arr)
        return np.full((horizon,), final_s, dtype=np.float32)
    elif arr.ndim == 2:
        out = np.empty((arr.shape[0], horizon), dtype=np.float32)
        for i in range(arr.shape[0]):
            final_s = _single_ewma(arr[i])
            out[i, :] = final_s
        return out
    else:
        raise ValueError(f"Expected 1D or 2D array, got shape {arr.shape}")


# ---------------------------------------------------------------------------
# TinyTemperatureLSTM Model Architecture
# ---------------------------------------------------------------------------

if _TORCH_AVAILABLE:
    class TinyTemperatureLSTM(nn.Module):
        """Lightweight TinyLSTM temperature forecast backbone.

        Architecture:
          input [batch, 72, 5]
          -> one-layer unidirectional LSTM(input_size=5, hidden_size=32, batch_first=True)
          -> final hidden state h_n[-1] [batch, 32]
          -> Dropout(0.1)
          -> Linear(32, 24)
          -> output [batch, 24]
        """

        def __init__(
            self,
            input_size: int = 5,
            hidden_size: int = 32,
            num_layers: int = 1,
            horizon: int = 24,
            dropout: float = 0.1,
        ) -> None:
            super().__init__()
            self.input_size = input_size
            self.hidden_size = hidden_size
            self.num_layers = num_layers
            self.horizon = horizon
            self.dropout_rate = dropout

            self.lstm = nn.LSTM(
                input_size=input_size,
                hidden_size=hidden_size,
                num_layers=num_layers,
                batch_first=True,
            )
            self.dropout = nn.Dropout(dropout)
            self.linear = nn.Linear(hidden_size, horizon)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            """Forward pass.

            Args:
                x: torch.Tensor of shape [batch, lookback, 5]
            Returns:
                torch.Tensor of shape [batch, horizon] (standardized predictions)
            """
            # out: [batch, seq_len, hidden_size]
            # h_n: [num_layers, batch, hidden_size]
            out, (h_n, c_n) = self.lstm(x)
            final_h = h_n[-1]  # shape [batch, hidden_size]
            dropped = self.dropout(final_h)
            return self.linear(dropped)
else:
    class TinyTemperatureLSTM:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "PyTorch is not installed. TinyTemperatureLSTM requires PyTorch optional ML dependency."
            )
