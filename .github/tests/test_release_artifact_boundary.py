"""The release consumes only an artifact from a fresh packaging job."""

import shlex
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"


def test_release_artifact_comes_from_the_isolated_package_job():
    ci = yaml.load((WORKFLOWS / "ci.yml").read_text(), Loader=yaml.BaseLoader)
    release = yaml.safe_load((WORKFLOWS / "release.yml").read_text())
    package = ci["jobs"]["package"]
    tests = ci["jobs"]["extension"]

    package_steps = package["steps"]
    assert all("pip install" not in step.get("run", "") for step in package_steps)
    assert all("upload-artifact@" not in step.get("uses", "") for step in tests["steps"])
    upload = next(step for step in package_steps if "upload-artifact@" in step.get("uses", ""))
    assert (
        package["outputs"]["archive-id"] == "${{ steps." + upload["id"] + ".outputs.artifact-id }}"
    )
    assert ci["on"]["workflow_call"]["outputs"]["archive-id"]["value"] == (
        "${{ jobs.package.outputs.archive-id }}"
    )
    download = next(
        step
        for step in release["jobs"]["release"]["steps"]
        if "download-artifact@" in step.get("uses", "")
    )
    assert download["with"]["artifact-ids"] == "${{ needs.ci.outputs.archive-id }}"


def test_catalog_job_installs_checker_dependency_before_using_it():
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    steps = ci["jobs"]["catalog"]["steps"]
    install = next(i for i, step in enumerate(steps) if "pip install" in step.get("run", ""))
    check = next(i for i, step in enumerate(steps) if "catalog_check.py" in step.get("run", ""))

    assert install < check
    command = shlex.split(steps[install]["run"])
    assert {"--no-deps", "--only-binary=:all:", "--require-hashes", "-r"} <= set(command)
    requirements = WORKFLOWS.parents[1] / command[command.index("-r") + 1]
    assert "PyYAML==" in requirements.read_text()
    assert "--hash=sha256:" in requirements.read_text()
