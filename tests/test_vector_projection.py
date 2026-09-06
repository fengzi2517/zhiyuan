import json
import math

from app.main import _project_vectors


def test_project_vectors_handles_empty_input():
    points, variance = _project_vectors([])
    assert points == []
    assert variance == []


def test_project_vectors_handles_single_vector():
    points, variance = _project_vectors([[1.0, 2.0]])
    assert points == [[0.0, 0.0]]
    assert variance == [0.0, 0.0]


def test_project_vectors_returns_finite_json_for_identical_vectors():
    points, variance = _project_vectors([[1.0, 2.0], [1.0, 2.0]])
    json.dumps({"points": points, "variance": variance}, allow_nan=False)
    assert all(math.isfinite(value) for point in points for value in point)
    assert variance == [0.0, 0.0]

