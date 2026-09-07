"""CLI-level checks. Exit codes are the contract the run sequence depends on."""

import pytest

from kbqa.cli import main

STAGING = "_collect-widgets-staging.md"
CAPTURE = "_capture-widgets.raw.txt"


def test_unknown_gate_never_exits_2(capsys):
    """Exit 2 means DECLINED. A typo must never read as 'vendor closed'."""
    for typo in ("g0x", "g7", "nonsense", "g0 --host x"):
        assert main([typo]) == 1, f"{typo!r} must be a usage error, not a decision"
    capsys.readouterr()


def test_help_exits_zero(capsys):
    assert main([]) == 0
    assert "usage:" in capsys.readouterr().out


def test_manifest_prints_every_gate(capsys):
    assert main(["--manifest"]) == 0
    out = capsys.readouterr().out
    assert "manifest_sha256" in out
    for gate in ("g0_permission", "g1_capture", "g2_conformance", "g3_grounding",
                 "g4_completeness", "g5_bundles", "g6_integrity"):
        assert f"gates/{gate}.py" in out


def test_gate_run_is_side_effect_free_by_default(fx, tmp_path, capsys):
    """No --vendor-dir and no --log means nothing is written anywhere."""
    d = fx("good")
    before = {p.name for p in d.iterdir()}
    code = main(["g2", "--staging", str(d / "_collect-widgets-staging.md")])
    capsys.readouterr()
    assert code == 0
    assert {p.name for p in d.iterdir()} == before
    assert not (d / "_qa").exists()


def test_recording_writes_verdict_and_log(fx, tmp_path, capsys):
    d = fx("good")
    log = tmp_path / "_qa-log.jsonl"
    code = main([
        "g2", "--staging", str(d / "_collect-widgets-staging.md"),
        "--vendor-dir", str(d), "--batch", "widgets", "--vendor", "Acme",
        "--log", str(log),
    ])
    capsys.readouterr()
    assert code == 0
    assert (d / "_qa" / "widgets.g2_conformance.json").exists()
    assert log.exists()
    assert log.read_text().count("\n") == 1


def test_recording_flags_never_leak_into_gate_parsers():
    """Regression: argparse.parse_known_args mis-assigned values when unknown
    optionals preceded known ones, leaking --vendor-dir into every two-argument
    gate and breaking g1, g3 and g6."""
    from kbqa.cli import split_recording_args

    rec, gate_argv = split_recording_args([
        "--staging", "S", "--capture", "C",
        "--vendor-dir", "V", "--batch", "b", "--vendor", "Acme", "--log", "L",
    ])
    assert gate_argv == ["--staging", "S", "--capture", "C"]
    assert (rec.vendor_dir, rec.batch, rec.vendor, rec.log) == ("V", "b", "Acme", "L")


def test_recording_flags_accept_equals_form():
    from kbqa.cli import split_recording_args

    rec, gate_argv = split_recording_args(["--root", "R", "--batch=widgets"])
    assert gate_argv == ["--root", "R"]
    assert rec.batch == "widgets"


@pytest.mark.parametrize("gate,extra", [
    ("g1", ["--capture", CAPTURE]),
    ("g3", ["--capture", CAPTURE]),
    ("g2", []),
])
def test_two_argument_gates_accept_recording_flags(gate, extra, fx, tmp_path, capsys):
    d = fx("good")
    args = [gate, "--staging", str(d / STAGING)]
    args += [a if not a.startswith("_") else str(d / a) for a in extra]
    args += ["--vendor-dir", str(d), "--batch", "widgets", "--log", str(tmp_path / "log.jsonl")]
    code = main(args)
    capsys.readouterr()
    assert code == 0, f"{gate} rejected its recording flags"


def test_log_is_append_only(fx, tmp_path, capsys):
    d = fx("good")
    log = tmp_path / "_qa-log.jsonl"
    args = [
        "g2", "--staging", str(d / "_collect-widgets-staging.md"),
        "--batch", "widgets", "--vendor", "Acme", "--log", str(log),
    ]
    main(args)
    main(args)
    capsys.readouterr()
    assert log.read_text().count("\n") == 2, "a second run must append, not rewrite"
