import subprocess


def test_smoke_test():
    cmd = ["python", "-m", "swebench.harness.run_evaluation", "--help"]
    result = subprocess.run(cmd, capture_output=True, check=True)
    print(result.stdout.decode())
    print(result.stderr.decode())
    assert result.returncode == 0


def test_one_instance():
    cmd = [
        "python",
        "-m",
        "swebench.harness.run_evaluation",
        "--predictions_path",
        "gold",
        "--max_workers",
        "1",
        "--instance_ids",
        "sympy__sympetry-20590",
        "--run_id",
        "validate-gold",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    print(result.stdout.decode())
    print(result.stderr.decode())
    assert result.returncode == 0