from typing import TYPE_CHECKING, Any
import pytest

from opgee.audit import AuditRow, _generate_field_audit_report
from opgee.model_file import ModelFile
from opgee.field import Field
from opgee.units import ureg
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
    field = model.get_field("AuditTestField_Input")

    original_xml_root = audit_model_file.root
    original_field_elem_list = original_xml_root.xpath(f".//Field[@name='{field.name}']")
    assert len(original_field_elem_list) == 1
    original_field_elem = original_field_elem_list[0]

    report_data = _generate_field_audit_report(field, original_field_elem)

    api_row = find_audit_row(report_data, "API")
    assert api_row["source"] == "input"
    # Consider approx for float comparison, handle units
    assert float(api_row["value"]) == pytest.approx(ureg.Quantity(25.5, "degAPI").m)
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
    water_reinj_row =find_audit_row(report_data, "water_reinjection")
    assert water_reinj_row["source"] == "static_default"
    assert bool(water_reinj_row["value"])
