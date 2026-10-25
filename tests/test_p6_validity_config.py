"""Tests for P6 validity configuration contract and validation."""

from __future__ import annotations

import copy
from pathlib import Path
import pytest
import yaml

from heattrace.thermal.validation import (
    is_placeholder,
    is_unresolved_value,
    load_p6_validity_config,
    validate_p6_validity_config,
    validate_temperature_forecast_config,
)


CONFIG_PATH = Path("configs/p6_validity.yaml")


def test_frozen_validity_config_file_loads_and_validates():
    """configs/p6_validity.yaml loads successfully and validates as fully frozen without placeholders."""
    cfg = load_p6_validity_config(CONFIG_PATH)
    assert isinstance(cfg, dict)
    status = validate_p6_validity_config(cfg)
    assert status["valid"] is True
    assert status["has_placeholders"] is False
    assert status["is_frozen"] is True
    assert cfg["dimensions"]["seeds"] == [20261016, 20261017]


def test_is_placeholder_identification():
    """Placeholders and unresolved phrases are identified correctly."""
    assert is_placeholder("TBD") is True
    assert is_placeholder("tbd_seed_1") is True
    assert is_placeholder("REQUIRED") is True
    assert is_placeholder("TBD_DEV_TRIPLET") is True
    assert is_placeholder("unknown") is True
    assert is_placeholder(" UNKNOWN ") is True
    assert is_placeholder("pending") is True
    assert is_placeholder("pending citation") is True
    assert is_placeholder("deferred") is True
    assert is_placeholder("Deferred until Gate 3") is True
    assert is_placeholder("not yet selected") is True
    assert is_placeholder("to be determined later") is True
    assert is_placeholder("to be decided") is True
    assert is_placeholder("not available yet") is True
    assert is_placeholder("awaiting approval") is True
    assert is_placeholder("unresolved") is True
    assert is_placeholder("frozen_value") is False
    assert is_placeholder(123) is False
    assert is_placeholder(None) is False


def test_rejects_missing_top_level_keys():
    """Missing top-level keys raise ValueError."""
    cfg = load_p6_validity_config(CONFIG_PATH)
    del cfg["dimensions"]
    with pytest.raises(ValueError, match="Missing required top-level configuration keys"):
        validate_p6_validity_config(cfg)


def test_rejects_invalid_development_triplet():
    """Missing development triplet or required fields raises ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    del cfg["triplets"]["development"]
    with pytest.raises(ValueError, match="Missing 'development' triplet definition"):
        validate_p6_validity_config(cfg)

    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    del cfg["triplets"]["development"]["pair_id"]
    with pytest.raises(ValueError, match="triplets\\['development'\\] missing required fields"):
        validate_p6_validity_config(cfg)


def test_rejects_wrong_confirmatory_cardinality():
    """Confirmatory triplets must contain exact items matching design_mode."""
    # Test primary mode (requires 4)
    cfg_primary = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg_primary["design_mode"] = "primary"
    # Make sure it has 4 items to start
    while len(cfg_primary["triplets"]["confirmatory"]) < 4:
        cfg_primary["triplets"]["confirmatory"].append(copy.deepcopy(cfg_primary["triplets"]["confirmatory"][0]))
    cfg_primary["triplets"]["confirmatory"].pop()  # now 3
    with pytest.raises(ValueError, match="Confirmatory triplets must contain exactly 4 items"):
        validate_p6_validity_config(cfg_primary)

    # 5 items in primary
    cfg_primary["triplets"]["confirmatory"].append(copy.deepcopy(cfg_primary["triplets"]["confirmatory"][0]))
    cfg_primary["triplets"]["confirmatory"].append(copy.deepcopy(cfg_primary["triplets"]["confirmatory"][0]))
    with pytest.raises(ValueError, match="Confirmatory triplets must contain exactly 4 items"):
        validate_p6_validity_config(cfg_primary)

    # Test fallback mode (requires 3)
    cfg_fallback = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg_fallback["design_mode"] = "fallback"
    while len(cfg_fallback["triplets"]["confirmatory"]) > 3:
        cfg_fallback["triplets"]["confirmatory"].pop()
    cfg_fallback["triplets"]["confirmatory"].pop()  # now 2
    with pytest.raises(ValueError, match="Confirmatory triplets in fallback mode must contain exactly 3 items"):
        validate_p6_validity_config(cfg_fallback)

    # 4 items in fallback
    cfg_fallback["triplets"]["confirmatory"].append(copy.deepcopy(cfg_fallback["triplets"]["confirmatory"][0]))
    cfg_fallback["triplets"]["confirmatory"].append(copy.deepcopy(cfg_fallback["triplets"]["confirmatory"][0]))
    with pytest.raises(ValueError, match="Confirmatory triplets in fallback mode must contain exactly 3 items"):
        validate_p6_validity_config(cfg_fallback)


def test_rejects_invalid_design_mode():
    """Invalid design_mode raises ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["design_mode"] = "invalid_mode"
    with pytest.raises(ValueError, match="Invalid design_mode"):
        validate_p6_validity_config(cfg)


def test_rejects_duplicate_non_placeholder_pair_ids():
    """Duplicate concrete pair IDs raise ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["triplets"]["development"]["pair_id"] = "PAIR_01"
    cfg["triplets"]["confirmatory"][0]["pair_id"] = "PAIR_01"
    with pytest.raises(ValueError, match="Duplicate pair_ids found"):
        validate_p6_validity_config(cfg)


def test_rejects_unknown_context_enum():
    """Unknown context enum raises ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["dimensions"]["contexts"] = ["heatwave", "matched_control", "random_window"]
    with pytest.raises(ValueError, match="Unknown contexts"):
        validate_p6_validity_config(cfg)


def test_rejects_unknown_facility_model_enum():
    """Unknown facility model enum raises ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["dimensions"]["facility_models"] = ["energy_only", "liquid_submerged"]
    with pytest.raises(ValueError, match="Unknown facility_models"):
        validate_p6_validity_config(cfg)


def test_rejects_unknown_thermal_curves_enum():
    """Unknown thermal curves enum raises ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["dimensions"]["thermal_curves"] = ["low", "extreme"]
    with pytest.raises(ValueError, match="Unknown thermal_curves"):
        validate_p6_validity_config(cfg)


def test_rejects_invalid_workload_multipliers():
    """Workload multipliers must be exactly [1.0, 2.0, 3.0]."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["dimensions"]["workload_multipliers"] = [1.0, 2.0]
    with pytest.raises(ValueError, match="workload_multipliers must be \\[1.0, 2.0, 3.0\\]"):
        validate_p6_validity_config(cfg)


def test_rejects_wrong_seed_count_or_duplicate_concrete_seeds():
    """Seeds must contain exactly 2 items, and concrete seeds cannot be duplicate."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["dimensions"]["seeds"] = ["TBD_SEED_1"]
    with pytest.raises(ValueError, match="seeds must contain exactly 2 explicit seeds"):
        validate_p6_validity_config(cfg)

    cfg["dimensions"]["seeds"] = [42, 42]
    with pytest.raises(ValueError, match="Duplicate seeds found"):
        validate_p6_validity_config(cfg)


def test_rejects_unknown_objectives():
    """Unknown objective enum raises ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["dimensions"]["objectives"] = ["cost_first", "profit_first"]
    with pytest.raises(ValueError, match="Unknown objectives"):
        validate_p6_validity_config(cfg)


def test_rejects_oracle_marked_deployable():
    """Oracle marked deployable: true must raise ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["policies"]["reference"]["deployable"] = True
    with pytest.raises(ValueError, match="reference policy MUST have deployable: false"):
        validate_p6_validity_config(cfg)


def test_rejects_unknown_deployable_policy():
    """Unknown deployable policy raises ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["policies"]["deployable"].append("magic_oracle")
    with pytest.raises(ValueError, match="Unknown deployable policies"):
        validate_p6_validity_config(cfg)


def test_rejects_empty_collections():
    """Empty collections raise ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["dimensions"]["contexts"] = []
    with pytest.raises(ValueError, match="contexts must be a non-empty list"):
        validate_p6_validity_config(cfg)


def _make_fully_concrete_test_config() -> dict:
    """Helper to construct a fully concrete valid test configuration."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    design_mode = cfg.get("design_mode", "primary")
    conf_count = 3 if design_mode == "fallback" else 4

    cfg["triplets"]["development"]["pair_id"] = "PAIR_DEV"
    cfg["triplets"]["development"]["heatwave_window_id"] = "HW_DEV"
    cfg["triplets"]["development"]["matched_control_window_id"] = "CTRL_DEV"
    cfg["triplets"]["development"]["event_blind_window_id"] = "BLIND_DEV"

    for i in range(conf_count):
        cfg["triplets"]["confirmatory"][i]["pair_id"] = f"PAIR_CONF_{i+1}"
        cfg["triplets"]["confirmatory"][i]["heatwave_window_id"] = f"HW_CONF_{i+1}"
        cfg["triplets"]["confirmatory"][i]["matched_control_window_id"] = f"CTRL_CONF_{i+1}"
        cfg["triplets"]["confirmatory"][i]["event_blind_window_id"] = f"BLIND_CONF_{i+1}"

    cfg["dimensions"]["seeds"] = [1001, 1002]

    # Explicit scientific required fields
    cfg["deadline_regime"] = {
        "processing_requirement_unit": "hourly_discrete_slot",
        "arrival_semantics": "window_relative_hour_inclusive",
        "deadline_semantics": "window_relative_hour_exclusive",
        "slack_distribution": "synthetic_uniform_slack",
        "slack_bounds_hours": "slack_range_2_to_12_hours",
    }
    cfg["parameter_sources"] = {
        "low_curve_source": "synthetic_reference_model_low",
        "medium_curve_source": "synthetic_reference_model_medium",
        "base_pue_source": "synthetic_reference_facility_base",
        "facility_cap_interpretation_source": "synthetic_rule_nominal_times_base_pue",
    }
    cfg["primary_analysis"] = {
        "hypothesis": "H1",
        "facility_model": "power_capped",
        "policy": "static_unaware",
        "outcome": "grid_bounded_lambda_star",
        "thermal_curve_rule": "evaluate_medium_curve_primary",
        "objective_rule": "evaluate_carbon_first_primary",
        "seed_aggregation_rule": "aggregate_within_pair_context_configuration_before_contrast",
        "pair_contrast": "heatwave_minus_matched_control",
        "across_pair_support_rule": "require_at_least_two_confirmatory_pairs_negative_contrast",
    }
    cfg["temperature_forecast"] = {
        "splits": {
            "boundary_semantics": "half_open_start_inclusive_end_exclusive",
            "training": {
                "start_utc": "2022-01-01T00:00:00+00:00",
                "end_exclusive_utc": "2022-05-01T00:00:00+00:00",
            },
            "validation": {
                "start_utc": "2022-05-01T00:00:00+00:00",
                "end_exclusive_utc": "2022-06-01T00:00:00+00:00",
            },
            "calibration_reservation": {
                "start_utc": "2022-06-01T00:00:00+00:00",
                "end_exclusive_utc": "2022-06-16T00:00:00+00:00",
            },
        },
        "architecture": {
            "model": "TinyTemperatureLSTM",
            "input_size": 5,
            "hidden_size": 32,
            "num_layers": 1,
            "horizon": 24,
            "dropout": 0.1,
        },
        "training": {
            "device": "cpu",
            "seed": 20261016,
            "optimizer": "AdamW",
            "learning_rate": 0.001,
            "loss": "SmoothL1",
            "batch_size": 64,
            "max_epochs": 50,
            "early_stopping_patience": 5,
            "early_stopping_min_delta": 0.0001,
        },
        "baselines": {
            "methods": [
                "last_observation",
                "same_hour_previous_day",
                "ewma_0.20",
            ],
            "ewma_alpha": 0.20,
        },
        "extreme_temperature": {
            "threshold_rule": "training_p95_strictly",
        },
        "gate": {
            "rmse_improvement_threshold": 0.02,
            "extreme_improvement_threshold": 0.05,
            "extreme_rmse_slack": -0.02,
        },
    }
    return cfg


def test_concrete_configuration_identifies_as_frozen():
    """When all TBD fields are replaced with valid frozen values, is_frozen is True."""
    cfg = _make_fully_concrete_test_config()
    status = validate_p6_validity_config(cfg)
    assert status["valid"] is True
    assert status["is_frozen"] is True
    assert status["has_placeholders"] is False


def test_status_fields_alone_cannot_freeze_configuration():
    """Adding or modifying status: frozen cannot bypass actual unresolved fields."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    # Inject unresolved placeholder and status: frozen
    cfg["deadline_regime"]["slack_distribution"] = "TBD"
    cfg["deadline_regime"]["status"] = "frozen"
    cfg["parameter_sources"]["status"] = "frozen"
    status = validate_p6_validity_config(cfg)
    assert status["valid"] is True
    assert status["has_placeholders"] is True
    assert status["is_frozen"] is False


def test_concrete_triplets_and_seeds_with_unresolved_deadline_fields_remains_unfrozen():
    """Concrete triplets and seeds but unresolved deadline_regime fields remains unfrozen."""
    cfg = _make_fully_concrete_test_config()
    cfg["deadline_regime"]["slack_distribution"] = "TBD"
    status = validate_p6_validity_config(cfg)
    assert status["valid"] is True
    assert status["has_placeholders"] is True
    assert status["is_frozen"] is False


def test_concrete_triplets_and_seeds_with_unresolved_parameter_source_fields_remains_unfrozen():
    """Concrete triplets and seeds but unresolved parameter_sources fields remains unfrozen."""
    cfg = _make_fully_concrete_test_config()
    cfg["parameter_sources"]["low_curve_source"] = "REQUIRED"
    status = validate_p6_validity_config(cfg)
    assert status["valid"] is True
    assert status["has_placeholders"] is True
    assert status["is_frozen"] is False


def test_rejects_missing_required_deadline_or_parameter_fields():
    """Missing required deadline_regime or parameter_sources fields raise ValueError."""
    cfg = _make_fully_concrete_test_config()
    del cfg["deadline_regime"]["slack_bounds_hours"]
    with pytest.raises(ValueError, match="deadline_regime missing required fields"):
        validate_p6_validity_config(cfg)

    cfg = _make_fully_concrete_test_config()
    del cfg["parameter_sources"]["base_pue_source"]
    with pytest.raises(ValueError, match="parameter_sources missing required fields"):
        validate_p6_validity_config(cfg)


def test_primary_analysis_validation_rules():
    """Missing, invalid fixed, or unresolved primary_analysis fields are tested thoroughly."""
    cfg = _make_fully_concrete_test_config()
    del cfg["primary_analysis"]["thermal_curve_rule"]
    with pytest.raises(ValueError, match="primary_analysis missing required fields"):
        validate_p6_validity_config(cfg)

    # Wrong fixed field value
    cfg = _make_fully_concrete_test_config()
    cfg["primary_analysis"]["hypothesis"] = "H2"
    with pytest.raises(ValueError, match="primary_analysis.hypothesis must be exact fixed value 'H1'"):
        validate_p6_validity_config(cfg)

    cfg = _make_fully_concrete_test_config()
    cfg["primary_analysis"]["facility_model"] = "energy_only"
    with pytest.raises(ValueError, match="primary_analysis.facility_model must be exact fixed value 'power_capped'"):
        validate_p6_validity_config(cfg)

    cfg = _make_fully_concrete_test_config()
    cfg["primary_analysis"]["policy"] = "static"
    with pytest.raises(ValueError, match="primary_analysis.policy must be exact fixed value 'static_unaware'"):
        validate_p6_validity_config(cfg)

    cfg = _make_fully_concrete_test_config()
    cfg["primary_analysis"]["outcome"] = "continuous_capacity"
    with pytest.raises(ValueError, match="primary_analysis.outcome must be exact fixed value 'grid_bounded_lambda_star'"):
        validate_p6_validity_config(cfg)

    cfg = _make_fully_concrete_test_config()
    cfg["primary_analysis"]["pair_contrast"] = "heatwave_minus_event_blind"
    with pytest.raises(ValueError, match="primary_analysis.pair_contrast must be exact fixed value 'heatwave_minus_matched_control'"):
        validate_p6_validity_config(cfg)

    # Unresolved decisions prevent freezing
    for dec_field in ["thermal_curve_rule", "objective_rule", "across_pair_support_rule"]:
        for unres in ["TBD", "unknown", "pending approval", "deferred"]:
            cfg = _make_fully_concrete_test_config()
            cfg["primary_analysis"][dec_field] = unres
            st = validate_p6_validity_config(cfg)
            assert st["valid"] is True
            assert st["has_placeholders"] is True
            assert st["is_frozen"] is False


def test_unresolved_phrases_and_case_variants_prevent_freezing():
    """Every specified unresolved phrase prevents a configuration from becoming frozen."""
    phrases = [
        "unknown",
        " UNKNOWN ",
        "pending",
        "pending citation",
        "deferred",
        "Deferred until Gate 3",
        "not yet selected",
        "to be determined later",
        "to be decided",
        "not available yet",
        "awaiting approval",
        "unresolved",
    ]
    for p in phrases:
        cfg = _make_fully_concrete_test_config()
        cfg["parameter_sources"]["low_curve_source"] = p
        st = validate_p6_validity_config(cfg)
        assert st["valid"] is True
        assert st["has_placeholders"] is True
        assert st["is_frozen"] is False
        assert st["is_frozen"] == (not st["has_placeholders"])


def test_rejects_blank_none_or_malformed_deadline_or_parameter_values():
    """Blank, None, numbers, booleans, or lists in deadline/parameter fields raise error."""
    for bad_val in [None, "", "   ", 123, True, ["source1"]]:
        cfg = _make_fully_concrete_test_config()
        cfg["deadline_regime"]["arrival_semantics"] = bad_val
        with pytest.raises((ValueError, TypeError)):
            validate_p6_validity_config(cfg)

        cfg = _make_fully_concrete_test_config()
        cfg["parameter_sources"]["facility_cap_interpretation_source"] = bad_val
        with pytest.raises((ValueError, TypeError)):
            validate_p6_validity_config(cfg)


def test_canonical_deployable_policies():
    """Real configuration contains exactly static_unaware, capacity_aware, full_thermal_aware."""
    cfg = load_p6_validity_config(CONFIG_PATH)
    assert cfg["policies"]["deployable"] == [
        "static_unaware",
        "capacity_aware",
        "full_thermal_aware",
    ]


def test_rejects_legacy_static_policy_id():
    """Legacy 'static' policy ID is rejected in favor of 'static_unaware'."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["policies"]["deployable"] = ["static", "capacity_aware", "full_thermal_aware"]
    with pytest.raises(ValueError, match="Unknown deployable policies: \\['static'\\]"):
        validate_p6_validity_config(cfg)


# =========================================================================
# Additional Strict Invariant Tests for Corrective Pass
# =========================================================================

def test_concrete_pair_ids_with_tbd_window_ids_remains_unfrozen():
    """Concrete pair IDs with TBD window IDs must produce is_frozen: false, has_placeholders: true."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    design_mode = cfg.get("design_mode", "primary")
    conf_count = 3 if design_mode == "fallback" else 4
    cfg["triplets"]["development"]["pair_id"] = "PAIR_DEV"
    for i in range(conf_count):
        cfg["triplets"]["confirmatory"][i]["pair_id"] = f"PAIR_CONF_{i+1}"
    cfg["dimensions"]["seeds"] = [101, 102]
    # Set all window IDs as TBD
    cfg["triplets"]["development"]["heatwave_window_id"] = "TBD"
    cfg["triplets"]["development"]["matched_control_window_id"] = "TBD"
    cfg["triplets"]["development"]["event_blind_window_id"] = "TBD"
    for i in range(conf_count):
        cfg["triplets"]["confirmatory"][i]["heatwave_window_id"] = "TBD"
        cfg["triplets"]["confirmatory"][i]["matched_control_window_id"] = "TBD"
        cfg["triplets"]["confirmatory"][i]["event_blind_window_id"] = "TBD"
    status = validate_p6_validity_config(cfg)
    assert status["valid"] is True
    assert status["is_frozen"] is False
    assert status["has_placeholders"] is True


def test_one_remaining_tbd_in_five_triplets_remains_unfrozen():
    """Even if all other fields are concrete, a single remaining TBD window ID keeps is_frozen: false."""
    cfg = _make_fully_concrete_test_config()
    design_mode = cfg.get("design_mode", "primary")
    last_idx = 2 if design_mode == "fallback" else 3
    # Leave exactly one window ID as TBD
    cfg["triplets"]["confirmatory"][last_idx]["event_blind_window_id"] = "TBD_REMAINING"

    status = validate_p6_validity_config(cfg)
    assert status["valid"] is True
    assert status["is_frozen"] is False
    assert status["has_placeholders"] is True


def test_rejects_none_or_blank_or_whitespace_required_ids():
    """None, empty, or whitespace-only IDs must be rejected with ValueError or TypeError."""
    for bad_id in [None, "", "   ", "\t\n"]:
        cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
        cfg["triplets"]["development"]["pair_id"] = bad_id
        with pytest.raises((ValueError, TypeError)):
            validate_p6_validity_config(cfg)

        cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
        cfg["triplets"]["development"]["heatwave_window_id"] = bad_id
        with pytest.raises((ValueError, TypeError)):
            validate_p6_validity_config(cfg)

        cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
        cfg["triplets"]["confirmatory"][1]["matched_control_window_id"] = bad_id
        with pytest.raises((ValueError, TypeError)):
            validate_p6_validity_config(cfg)

        cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
        cfg["triplets"]["confirmatory"][2]["event_blind_window_id"] = bad_id
        with pytest.raises((ValueError, TypeError)):
            validate_p6_validity_config(cfg)


def test_rejects_invalid_durations():
    """Zero, negative, boolean, float, or string durations must raise TypeError or ValueError."""
    for bad_dur in [0, -1, -120]:
        cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
        cfg["triplets"]["development"]["duration_hours"] = bad_dur
        with pytest.raises(ValueError, match="duration_hours must be strictly positive"):
            validate_p6_validity_config(cfg)

    for bad_type_dur in [True, False, 120.0, "120"]:
        cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
        cfg["triplets"]["confirmatory"][0]["duration_hours"] = bad_type_dur
        with pytest.raises(TypeError, match="duration_hours must be a non-boolean positive integer"):
            validate_p6_validity_config(cfg)


def test_rejects_unequal_triplet_durations():
    """Unequal durations across any of the 5 triplets must raise ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["triplets"]["confirmatory"][2]["duration_hours"] = 96
    with pytest.raises(ValueError, match="All triplets must have equal duration_hours"):
        validate_p6_validity_config(cfg)


def test_rejects_duplicate_concrete_window_ids_within_same_category():
    """Concrete window IDs duplicated within the same category across triplets must raise ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["triplets"]["development"]["heatwave_window_id"] = "HW_DUP_01"
    cfg["triplets"]["confirmatory"][0]["heatwave_window_id"] = "HW_DUP_01"
    with pytest.raises(ValueError, match="Duplicate concrete heatwave_window_id 'HW_DUP_01'"):
        validate_p6_validity_config(cfg)

    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["triplets"]["confirmatory"][1]["matched_control_window_id"] = "CTRL_DUP_02"
    cfg["triplets"]["confirmatory"][2]["matched_control_window_id"] = "CTRL_DUP_02"
    with pytest.raises(ValueError, match="Duplicate concrete matched_control_window_id 'CTRL_DUP_02'"):
        validate_p6_validity_config(cfg)

    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    design_mode = cfg.get("design_mode", "primary")
    last_idx = 2 if design_mode == "fallback" else 3
    cfg["triplets"]["development"]["event_blind_window_id"] = "BLIND_DUP_03"
    cfg["triplets"]["confirmatory"][last_idx]["event_blind_window_id"] = "BLIND_DUP_03"
    with pytest.raises(ValueError, match="Duplicate concrete event_blind_window_id 'BLIND_DUP_03'"):
        validate_p6_validity_config(cfg)


def test_rejects_concrete_window_id_reused_across_different_categories():
    """The same concrete window ID reused across different categories must raise ValueError."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    # Reuse heatwave window ID as matched control
    cfg["triplets"]["development"]["heatwave_window_id"] = "WINDOW_CROSS_01"
    cfg["triplets"]["development"]["matched_control_window_id"] = "WINDOW_CROSS_01"
    with pytest.raises(ValueError, match="reused across categories or triplets"):
        validate_p6_validity_config(cfg)

    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    # Reuse event-blind window ID as heatwave
    cfg["triplets"]["confirmatory"][0]["event_blind_window_id"] = "WINDOW_CROSS_02"
    cfg["triplets"]["confirmatory"][1]["heatwave_window_id"] = "WINDOW_CROSS_02"
    with pytest.raises(ValueError, match="reused across categories or triplets"):
        validate_p6_validity_config(cfg)


def test_rejects_invalid_concrete_seeds():
    """Arbitrary non-placeholder strings, booleans, floats, and None must raise TypeError or ValueError."""
    for bad_seed in ["foo", "random_string", "seed_1"]:
        cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
        cfg["dimensions"]["seeds"] = [bad_seed, 2026]
        with pytest.raises(TypeError, match="must be a recognized placeholder string or a non-boolean integer"):
            validate_p6_validity_config(cfg)

    for bad_bool in [True, False]:
        cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
        cfg["dimensions"]["seeds"] = [bad_bool, 2026]
        with pytest.raises(TypeError, match="cannot be a boolean"):
            validate_p6_validity_config(cfg)

    for bad_float in [100.5, 2026.0]:
        cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
        cfg["dimensions"]["seeds"] = [bad_float, 2026]
        with pytest.raises(TypeError, match="must be a recognized placeholder string or a non-boolean integer"):
            validate_p6_validity_config(cfg)

    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["dimensions"]["seeds"] = [None, 2026]
    with pytest.raises(ValueError, match="Seed 0 cannot be None"):
        validate_p6_validity_config(cfg)


# =========================================================================
# Token-Boundary and Multiword Unresolved Placeholder Tests
# =========================================================================

@pytest.mark.parametrize(
    "val",
    [
        "TBD",
        "TBD.",
        "TBD/approval",
        "TBD: source required",
        "tbd_source",
        "tbd-source",
        "required",
        "required/source",
        "unknown",
        "unknown.",
        "unresolved",
        "pending",
        "pending citation",
        "pending/citation",
        "deferred-until-gate-3",
        "not yet selected",
        "not_yet_selected",
        "not-yet-selected",
        "to be determined later",
        "to_be_determined_later",
        "to-be-determined-later",
        "to be decided",
        "to_be_decided",
        "not available yet",
        "not_available_yet",
        "awaiting approval",
        "awaiting/approval",
    ],
)
def test_is_unresolved_value_positive_cases(val: str):
    """Confirm all required positive unresolved variants return True."""
    assert is_unresolved_value(val) is True
    assert is_placeholder(val) is True


@pytest.mark.parametrize(
    "val",
    [
        "approved",
        "frozen_value",
        "determined",
        "available",
        "notable",
        "pendington",
        "deferredness",
        "awaitingroom",
        "tbdx",
        "requiredness",
        "unknowns",
    ],
)
def test_is_unresolved_value_negative_cases(val: str):
    """Confirm words with similar prefixes or containing unresolved roots return False."""
    assert is_unresolved_value(val) is False
    assert is_placeholder(val) is False


@pytest.mark.parametrize(
    "bypass_val",
    [
        "TBD.",
        "TBD/approval",
        "pending/citation",
        "not_available_yet",
        "to_be_determined_later",
    ],
)
def test_punctuation_and_machine_style_placeholders_prevent_freezing(bypass_val: str):
    """Punctuation and underscore variants prevent configuration freezing."""
    # Test on parameter_sources
    cfg1 = _make_fully_concrete_test_config()
    cfg1["parameter_sources"]["low_curve_source"] = bypass_val
    st1 = validate_p6_validity_config(cfg1)
    assert st1["valid"] is True
    assert st1["has_placeholders"] is True
    assert st1["is_frozen"] is False
    assert st1["is_frozen"] == (not st1["has_placeholders"])

    # Test on primary_analysis
    cfg2 = _make_fully_concrete_test_config()
    cfg2["primary_analysis"]["thermal_curve_rule"] = bypass_val
    st2 = validate_p6_validity_config(cfg2)
    assert st2["valid"] is True
    assert st2["has_placeholders"] is True
    assert st2["is_frozen"] is False
    assert st2["is_frozen"] == (not st2["has_placeholders"])


# ---------------------------------------------------------------------------
# Phase 4 Temperature Forecast Configuration Tests
# ---------------------------------------------------------------------------

def test_temperature_forecast_config_valid_production_entry():
    """Verify configs/p6_validity.yaml loads and validates through validate_p6_validity_config."""
    cfg = load_p6_validity_config(CONFIG_PATH)
    status = validate_p6_validity_config(cfg)
    assert status["valid"] is True
    assert status["is_frozen"] is True
    assert status["has_placeholders"] is False


def test_temperature_forecast_rejects_missing_block():
    """Rejects missing temperature_forecast block through production validator."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    del cfg["temperature_forecast"]
    with pytest.raises(ValueError, match="Missing required top-level configuration keys.*temperature_forecast"):
        validate_p6_validity_config(cfg)


def test_temperature_forecast_rejects_old_ambiguous_end_utc():
    """Rejects old ambiguous end_utc field through production validator."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["splits"]["training"]["end_utc"] = "2022-04-30T23:00:00+00:00"
    with pytest.raises(ValueError, match="Ambiguous 'end_utc' found"):
        validate_p6_validity_config(cfg)


def test_temperature_forecast_rejects_missing_end_exclusive_utc():
    """Rejects missing end_exclusive_utc through production validator."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    del cfg["temperature_forecast"]["splits"]["training"]["end_exclusive_utc"]
    with pytest.raises(ValueError, match="Missing 'end_exclusive_utc'"):
        validate_p6_validity_config(cfg)


def test_temperature_forecast_rejects_unordered_or_overlapping_splits():
    """Rejects unordered or overlapping splits through production validator."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["splits"]["validation"]["start_utc"] = "2022-04-15T00:00:00+00:00"
    with pytest.raises(ValueError, match="Splits must be strictly chronological and disjoint"):
        validate_p6_validity_config(cfg)


def test_temperature_forecast_rejects_non_utc_timestamp():
    """Rejects non-UTC timestamp through production validator."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["splits"]["training"]["start_utc"] = "2022-01-01T00:00:00-08:00"
    with pytest.raises(ValueError, match="must be explicit UTC"):
        validate_p6_validity_config(cfg)


def test_temperature_forecast_rejects_invalid_architecture():
    """Rejects invalid architecture dimensions through production validator."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["architecture"]["input_size"] = 6
    with pytest.raises(ValueError, match="input_size.*must be 5"):
        validate_p6_validity_config(cfg)

    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["architecture"]["horizon"] = 48
    with pytest.raises(ValueError, match="horizon.*must be 24"):
        validate_p6_validity_config(cfg)


def test_temperature_forecast_rejects_non_cpu_device_or_invalid_seed():
    """Rejects non-CPU device or invalid seed through production validator."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["training"]["device"] = "cuda:0"
    with pytest.raises(ValueError, match="training.device must be 'cpu'"):
        validate_p6_validity_config(cfg)

    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["training"]["seed"] = 42
    with pytest.raises(ValueError, match="training.seed.*must be 20261016"):
        validate_p6_validity_config(cfg)


def test_temperature_forecast_rejects_invalid_alpha_or_gate_thresholds():
    """Rejects invalid EWMA alpha or gate thresholds through production validator."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["baselines"]["ewma_alpha"] = 0.35
    with pytest.raises(ValueError, match="baselines.ewma_alpha.*must be 0.2"):
        validate_p6_validity_config(cfg)

    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["gate"]["rmse_improvement_threshold"] = 0.10
    with pytest.raises(ValueError, match="gate.rmse_improvement_threshold.*must be 0.02"):
        validate_p6_validity_config(cfg)


def test_temperature_forecast_rejects_non_finite_or_boolean_numeric():
    """Rejects boolean or non-finite numeric parameters through production validator."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["training"]["learning_rate"] = float("nan")
    with pytest.raises(ValueError, match="training.learning_rate.*must be finite"):
        validate_p6_validity_config(cfg)

    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["architecture"]["input_size"] = True
    with pytest.raises(TypeError, match="architecture.input_size.*must be an integer"):
        validate_p6_validity_config(cfg)


def test_temperature_forecast_placeholder_prevents_freezing():
    """Placeholder in temperature_forecast prevents configuration freezing."""
    cfg = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg["temperature_forecast"]["training"]["optimizer"] = "TBD"
    # Even if optimizer is changed, placeholder detection flags it
    with pytest.raises(ValueError, match="training.optimizer must be 'AdamW'"):
        validate_p6_validity_config(cfg)

    # Place in a field that accepts string check or causes unfreezing
    cfg2 = copy.deepcopy(load_p6_validity_config(CONFIG_PATH))
    cfg2["temperature_forecast"]["splits"]["boundary_semantics"] = "TBD"
    with pytest.raises(ValueError, match="boundary_semantics must be"):
        validate_p6_validity_config(cfg2)




