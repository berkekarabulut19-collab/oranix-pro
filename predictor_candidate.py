"""Experimental predictor that can only run behind the shadow rollout flag."""

from copy import deepcopy

from predictor_engine import PredictorEngine


class PredictorEngineVNext(PredictorEngine):
    """Conservative calibration candidate; never selected by default."""

    def __init__(self):
        super().__init__()
        self.version = "18000.0-SHADOW-CONSERVATIVE"

    def analyze_match(self, match):
        result = deepcopy(super().analyze_match(match))
        probs = result.get("probs", {})
        keys = ("home_win", "draw", "away_win")
        if not all(isinstance(probs.get(key), (int, float)) for key in keys):
            return result

        quality = result.get("model_meta", {}).get("input_quality", {}).get("score", 50)
        shrink = 0.08 if quality < 60 else 0.04
        values = [float(probs[key]) * (1.0 - shrink) + (100.0 / 3.0) * shrink for key in keys]
        rounded = [round(value, 1) for value in values]
        rounded[0] = round(rounded[0] + (100.0 - sum(rounded)), 1)
        result["probs"] = dict(zip(keys, rounded))
        result.setdefault("model_meta", {})["version"] = self.version
        result["model_meta"]["shadow_only"] = True
        result["model_meta"]["confidence_shrinkage"] = shrink
        return result
