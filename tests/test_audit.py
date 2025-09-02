import os
from pathlib import Path
from unittest.mock import patch
import pytest

import pandas as pd

from opgee.audit import AuditRow, _generate_field_audit_report, audit_field
from opgee.config import setParam, getConfig
from opgee.error import OpgeeException
from opgee.model_file import ModelFile
from tests.utils_for_tests import path_to_test_file


@pytest.fixture(scope="module")
def audit_model_file(configure_logging_for_tests):
    model_path = path_to_test_file("audit_model.xml")

    mf = ModelFile(model_path, use_default_model=True)

    yield mf


def find_audit_row(report_data: list[AuditRow], attr_name: str) -> AuditRow:
    for row in report_data:
        if row["attribute"] == attr_name:
            return row
    pytest.fail(f"Attribute '{attr_name} not found in audit report:  {report_data}")


def test_audit_source_input(audit_model_file: ModelFile):
    """Verify explicitly set attributes have source='input'."""

    model = audit_model_file.model
    field = model.get_field("audit-field")

    original_xml_root = audit_model_file.root
    original_field_elem_list = original_xml_root.xpath(
        f".//Field[@name='{field.name}']"
    )
    assert len(original_field_elem_list) == 1
    original_field_elem = original_field_elem_list[0]

    report_data = _generate_field_audit_report(field, original_field_elem)

    api_row = find_audit_row(report_data, "API")
    assert api_row["source"] == "input"
    # Consider approx for float comparison, handle units
    assert float(api_row["value"]) == pytest.approx(25.5, rel=0.0001)
    assert str(api_row["unit"]) == "degAPI"  # Check unit string

    gor_row = find_audit_row(report_data, "GOR")
    assert gor_row["source"] == "input"
    assert float(gor_row["value"]) == pytest.approx(1500.0, rel=0.0001)
    assert str(gor_row["unit"]) == "scf/bbl_oil"

    # Check 'depth' which should use its static default
    depth_row = find_audit_row(report_data, "depth")
    assert depth_row["source"] == "smart_default"
    assert float(depth_row["value"]) == pytest.approx(7122.0, 0.0001)
    # WOR should use smart default
    water_reinj_row = find_audit_row(report_data, "water_reinjection")
    assert water_reinj_row["source"] == "static_default"
    assert bool(water_reinj_row["value"])


# it should only write the pngs if AuditLevel == "processes"
def test_audit_field(audit_model_file: ModelFile, tmp_path):
    _ = getConfig()
    results_dir = Path(os.path.join(tmp_path, "audit_results"))
    results_dir.mkdir(exist_ok=True, parents=True)
    setParam("OPGEE.output_dir", str(results_dir))
    model = audit_model_file.model
    analysis = model.get_analysis("audit-analysis")
    field = model.get_field("audit-field")
    field.run(analysis)
    audit_data = audit_field(field, audit_model_file, "Processes")
    assert audit_data["field"] is None
    assert audit_data["proc_graph"] is not None

    audit_data = audit_field(field, audit_model_file, "Field")
    assert audit_data["proc_graph"] is None
    assert audit_data["field"] is not None

    audit_data = audit_field(field, audit_model_file, "All")
    assert audit_data["field"] is not None
    assert audit_data["proc_graph"] is not None

    audit_data = audit_field(field, audit_model_file)
    assert audit_data is None


def audit_setup_and_run(tmp_path: Path, opgee, audit_level: str | None = None):
    _ = getConfig(createDefault=True,reload=True)
    results_dir = Path(os.path.join(tmp_path, "audit_results"))
    results_dir.mkdir(exist_ok=True, parents=True)

    setParam("OPGEE.output_dir", str(results_dir))
    if audit_level:
        setParam("OPGEE.AuditLevel", str(audit_level))

    audit_xml_path = path_to_test_file("audit_model.xml")
    mf = ModelFile.from_xml_string(open(audit_xml_path).read())
    field = mf.model.get_field("audit-field")
    cmd = [
        "run",
        "-m", str(audit_xml_path),
        "-a", "audit-analysis",
        "-r", "detailed",
        "-o", str(results_dir)
    ]

    opgee.run(argList=cmd)
    return results_dir / "field_audit.csv", results_dir / "process_graphs" / f"{field.name}_process_graph.png"

def test_audit_save_results(tmp_path: Path, audit_model_file: ModelFile, opgee_main):
    audit_path, proc_graph_path = audit_setup_and_run(tmp_path, opgee_main, "Field")
    assert not proc_graph_path.exists()
    assert audit_path.exists()
    audit_df = pd.read_csv(audit_path)
    inputs = audit_df[audit_df['source'] == 'input']
    vals = inputs['value'].values
    assert len(vals == 2)
    assert vals[0] == '25.5'
    assert vals[1] == '1500.0'

def test_audit_save_procs(tmp_path: Path, opgee_main):
    audit_path, proc_graph_path = audit_setup_and_run(tmp_path, opgee_main, "Processes")
    assert proc_graph_path.exists()
    assert not audit_path.exists()

def test_audit_save_all(tmp_path: Path, opgee_main):
    audit_path, proc_graph_path = audit_setup_and_run(tmp_path, opgee_main, "All")
    assert proc_graph_path.exists() and audit_path.exists()

def test_audit_save_none(tmp_path: Path, opgee_main):
    audit_path, proc_graph_path = audit_setup_and_run(tmp_path, opgee_main)
    assert not (audit_path.exists() or proc_graph_path.exists())

# it should audit if Field.run fails
def test_audit_on_run_failure(tmp_path: Path, opgee_main):
    def mocked_field_run_processes(self, analysis):
        raise OpgeeException("Test exception")

    with patch("opgee.field.Field.run_processes", mocked_field_run_processes):
        audit_path, proc_graph_path = audit_setup_and_run(tmp_path, opgee_main, "Field")
        assert audit_path.exists()

