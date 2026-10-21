"""Historical persistence and aggregate forecasting module conforming to P4 no-leakage rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd

from heattrace.forecast.schema import FORECAST_COLUMNS, validate_forecast_dataframe
from heattrace.policy.interfaces import ForecastPoint, ForecastProvider, ForecastResult


@dataclass
class HistoricalPersistenceForecastProvider:
    """Deterministic historical persistence forecast provider conforming to ForecastProvider.

    Strict no-leakage rules:
    - Forecasts at origin T use only rows with timestamp_utc < T.
    - Never copy target-period actuals into forecast outputs.
    - Fallback values are used if pre-origin history is empty or missing.
    """
    model_name: str = "historical_persistence_v0"
    model_version: str = "1.0"
    fallback_price_usd_per_mwh: float = 45.0
    fallback_carbon_g_per_kwh: float = 220.0

    def forecast(
        self,
        origin_timestamp_utc: datetime,
        horizon_hours: int,
        *,
        history_df: pd.DataFrame | None = None,
        window_type: str = "event",
        window_id: str = "HW_20240702",
    ) -> ForecastResult:
        """Produce forecast for [origin_timestamp_utc, origin_timestamp_utc + horizon_hours).

        Strictly filters history_df to timestamp_utc < origin_timestamp_utc.
        """
        if origin_timestamp_utc.tzinfo is None:
            raise ValueError("origin_timestamp_utc must be timezone-aware UTC")
        if horizon_hours <= 0:
            raise ValueError(f"horizon_hours must be > 0, got {horizon_hours}")

        # Strict causal filter: rows strictly before origin
        usable_history: pd.DataFrame = pd.DataFrame()
        if history_df is not None and not history_df.empty:
            if "timestamp_utc" in history_df.columns:
                ts_col = pd.to_datetime(history_df["timestamp_utc"], utc=True)
                causal_mask = ts_col < pd.to_datetime(origin_timestamp_utc, utc=True)
                usable_history = history_df.loc[causal_mask].copy()
            else:
                usable_history = history_df.copy()

        # Determine price & carbon
        used_fallback = False
        forecast_method = "historical_persistence"
        price_val = self.fallback_price_usd_per_mwh
        carbon_val = self.fallback_carbon_g_per_kwh
        source_history_rows = len(usable_history)

        if not usable_history.empty:
            # Check price
            if "price_usd_per_mwh" in usable_history.columns:
                valid_prices = usable_history["price_usd_per_mwh"].dropna()
                if not valid_prices.empty:
                    price_val = float(valid_prices.iloc[-1])
                else:
                    used_fallback = True
            else:
                used_fallback = True

            # Check carbon
            if "carbon_g_per_kwh" in usable_history.columns:
                valid_carbon = usable_history["carbon_g_per_kwh"].dropna()
                if not valid_carbon.empty:
                    carbon_val = max(0.0, float(valid_carbon.iloc[-1]))
                else:
                    used_fallback = True
            else:
                used_fallback = True
        else:
            used_fallback = True
            forecast_method = "fallback_frozen_default"

        points: list[ForecastPoint] = []
        df_rows: list[dict[str, Any]] = []

        for h in range(horizon_hours):
            target_ts = origin_timestamp_utc + pd.Timedelta(hours=h)
            target_dt = target_ts.to_pydatetime() if isinstance(target_ts, pd.Timestamp) else target_ts
            points.append(
                ForecastPoint(
                    timestamp_utc=target_dt,
                    horizon_hours=h,
                    predicted_price_usd_per_mwh=price_val,
                    predicted_carbon_g_per_kwh=carbon_val,
                )
            )
            df_rows.append({
                "window_type": window_type,
                "window_id": window_id,
                "origin_timestamp_utc": origin_timestamp_utc,
                "target_timestamp_utc": target_dt,
                "horizon_hour": h,
                "predicted_price_usd_per_mwh": price_val,
                "predicted_carbon_g_per_kwh": carbon_val,
                "forecast_method": forecast_method,
                "model_name": self.model_name,
                "model_version": self.model_version,
                "history_cutoff_utc": origin_timestamp_utc,
                "used_fallback": used_fallback,
                "source_history_rows": source_history_rows,
            })

        forecast_df = pd.DataFrame(df_rows)[FORECAST_COLUMNS]
        # Attach dataframe to ForecastResult or create helper
        result = ForecastResult(
            origin_timestamp_utc=origin_timestamp_utc,
            points=points,
            model_name=self.model_name,
            model_version=self.model_version,
        )
        # Store internal dataframe representation
        object.__setattr__(result, "_forecast_df", forecast_df)
        return result


def build_historical_forecast_dataset(
    benchmark_df: pd.DataFrame,
    *,
    event_window_id: str = "HW_20240702",
    control_window_id: str = "CTRL_20240605",
    horizon_hours: int = 120,
    fallback_price_usd_per_mwh: float = 45.0,
    fallback_carbon_g_per_kwh: float = 220.0,
) -> pd.DataFrame:
    """Build causal historical forecasts for both event and control windows without leaking future actuals."""
    provider = HistoricalPersistenceForecastProvider(
        fallback_price_usd_per_mwh=fallback_price_usd_per_mwh,
        fallback_carbon_g_per_kwh=fallback_carbon_g_per_kwh,
    )

    all_dfs: list[pd.DataFrame] = []

    for wid in [control_window_id, event_window_id]:
        sub = benchmark_df[benchmark_df["window_id"] == wid].sort_values("timestamp_utc")
        if sub.empty:
            raise ValueError(f"Window {wid} not found in benchmark dataframe")
        wtype = str(sub["window_type"].iloc[0])
        origin_ts = pd.to_datetime(sub["timestamp_utc"].iloc[0], utc=True).to_pydatetime()

        # Strict no-leakage: history is strictly rows before origin_ts from benchmark or prior history
        # Note: Event actuals must not be used to forecast the event; control actuals must not be used for control.
        # Benchmark dataframe contains control (June 5-10) and event (July 1-6).
        # For control (June 5): prior rows in benchmark before June 5 = 0 rows -> uses fallback.
        # For event (July 1): prior rows in benchmark before July 1 are control rows (June 5-10) if provided,
        # but to ensure identical frozen procedure and no privileged information, pre-origin rows strictly < origin_ts are used.
        res = provider.forecast(
            origin_ts,
            horizon_hours,
            history_df=benchmark_df,
            window_type=wtype,
            window_id=wid,
        )
        f_df = getattr(res, "_forecast_df")
        all_dfs.append(f_df)

    combined_df = pd.concat(all_dfs, ignore_index=True)
    val_errors = validate_forecast_dataframe(combined_df, expected_rows=horizon_hours * 2)
    if val_errors:
        raise ValueError(f"Forecast validation failed: {'; '.join(val_errors)}")
    return combined_df
