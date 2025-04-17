"""Provides functionality for auditing the source of field attribute values."""

from typing import Literal, TypedDict

from lxml import etree
from pint import Quantity

from opgee.attributes import AttrDefs
from opgee.config import getParam
from opgee.core import A
from opgee.field import Field
from opgee.log import getLogger
from opgee.model_file import ModelFile
from opgee.smart_defaults import SmartDefault

_logger = getLogger(__name__)


class AuditRow(TypedDict):
    """Represents a single row in the field attribute audit report."""
    source: Literal["input", "static_default", "smart_default", "unknown"]
    attribute: str
    value: str | int | float | bool | Quantity
    unit: str | None


def _generate_field_audit_report(field: Field, original_field_element: etree._Element) -> list[AuditRow]:
    """
    Generate a report detailing the source of each field-level attribute's final value.

    :param field: The final Field object (after run attempt)
    :param original_field_element: The lxml.etree._Element representing the original <Field> definition from input XML
    :return: A list of dictionaries detailing attribute sources.
    """
    # Get the AttrDefs instance
    attr_defs = AttrDefs.get_instance()
    if not attr_defs:
        _logger.warning("Attribute definitions (AttrDefs) not loaded. Source information will be incomplete.")
        return []

    # Get the ClassAttrs for the "Field" class
    class_attrs = attr_defs.class_attrs("Field", raiseError=False)
    if not class_attrs:
        _logger.warning("ClassAttrs for 'Field' not found. Source information will be incomplete.")
        return []

    # Extract original attributes defined via <A> tags directly under original_field_element
    original_attrs: dict[str, str] = {
        a.get("name"): a.text for a in original_field_element.xpath("./A") if a.get("name")
    }

    # Initialize empty list for report rows
    report_rows: list[AuditRow] = []

    # Iterate through all AttrDef objects defined within the "Field" ClassAttrs
    for attr_def in class_attrs.attr_dict.values():
        attr_name = attr_def.name

        # Get the corresponding A object from the final field state
        param_obj = field.attr_dict.get(attr_name)

        # Skip if param_obj is None or not an instance of A
        if param_obj is None or not isinstance(param_obj, A):
            continue

        source: Literal["input", "static_default", "smart_default", "unknown"]
        static_default = attr_def.default
        # Determine the source label
        if attr_name in original_attrs:
            source = "input"
        elif attr_name in SmartDefault.registry:
            source = "smart_default"
        elif static_default is not None:
            source = "static_default"
        else:
            source = "unknown"

        report_rows.append(
            AuditRow(
                source=source,
                attribute=attr_name,
                value=param_obj.value,
                unit=str(param_obj.unit) if param_obj.unit else "",
            )
        )

    return report_rows


def audit_field(field: Field | None, mf: ModelFile | None) -> list[dict] | None:
    """
    Control field auditing based on configuration settings.

    :param field: The Field object (potentially None)
    :param mf: The ModelFile object (potentially None)
    :return: A list of audit data dictionaries or None if auditing is disabled or fails.
    """
    # Read configuration
    config_level = getParam("OPGEE.AuditLevel", raiseError=False)

    # If config_level is None, return None
    if config_level is None:
        return None

    # If field or mf is None, skip audit
    if field is None or mf is None:
        _logger.debug("Audit skipped: Field or ModelFile object is None.")
        return None

    # Check if field-level auditing is enabled
    if config_level in {"FieldLevel", "Full"}:
        # Get original root
        original_xml_root = mf.getroot()
        if original_xml_root is None:
            _logger.error(f"Audit failed for field '{field.name}': Could not get XML root from ModelFile.")
            return None

        # Find original field element
        original_field_elem_list = original_xml_root.xpath(f".//Field[@name='{field.name}']")
        if not original_field_elem_list:
            _logger.error(f"Audit failed for field '{field.name}': Original field element not found in XML.")
            return None

        original_field_elem = original_field_elem_list[0]

        # Call the report generator
        return _generate_field_audit_report(field, original_field_elem)

    # If config_level is Graph or other value, return None for now
    # Future implementation could add graph generation here
    return None
