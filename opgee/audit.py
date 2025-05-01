"""Provides functionality for auditing the source of field attribute values."""

from enum import Enum, Flag, auto
from pathlib import Path
from typing import Literal, TypeGuard, TypedDict

from lxml import etree
import pandas as pd
from pint import Quantity

from opgee.attributes import AttrDefs
from opgee.config import getParam
from opgee.core import A
from opgee.field import Field
from opgee.graph import write_process_diagram
from opgee.log import getLogger
from opgee.model_file import ModelFile
from opgee.smart_defaults import SmartDefault

_logger = getLogger(__name__)


class AuditRow(TypedDict):
    """Represents a single row in the field attribute audit report."""

    field: str
    attribute: str
    source: Literal["input", "static_default", "smart_default", "unknown"]
    value: str
    unit: str | None


class AuditFlag(Flag):
    NONE = 0
    FIELD = auto()
    PROCESSES = auto()
    ALL = FIELD | PROCESSES


AuditLevelStr = Literal["all", "field", "processes", "none"]

AUDIT_LEVELS: tuple[AuditLevelStr, ...] = ("field", "processes", "all", "none")


def audit_required(audit_level: str | None):
    if audit_level is None:
        return False

    _audit_level = audit_level.strip().lower()
    if not _is_audit_level_str(audit_level):
        _logger.warning(f"Invalid AuditLevel {audit_level}. Ignoring...")
        return False

    if _audit_level == "none":
        return False
    else:
        return True


def _is_audit_level_str(level: str) -> TypeGuard[AuditLevelStr]:
    return level.strip().lower() in AUDIT_LEVELS


def _translate_audit_level(
    level: AuditLevelStr | None,
) -> AuditFlag:
    _level = str(level).strip().lower()
    if _level == "all":
        return AuditFlag.ALL
    elif _level == "field":
        return AuditFlag.FIELD
    elif _level == "processes":
        return AuditFlag.PROCESSES
    else:
        return AuditFlag.NONE


def _generate_field_audit_report(
    field: Field, original_field_element: etree._Element
) -> list[AuditRow]:
    """
    Generate a report detailing the source of each field-level attribute's final value.

    :param field: The final Field object (after run attempt)
    :param original_field_element: The lxml.etree._Element representing the original <Field> definition from input XML
    :return: A list of dictionaries detailing attribute sources.
    """
    attr_defs = AttrDefs.get_instance()
    if not attr_defs:
        _logger.warning(
            "Attribute definitions (AttrDefs) not loaded. Source information will be incomplete."
        )
        return []

    class_attrs = attr_defs.class_attrs("Field", raiseError=False)
    if not class_attrs:
        _logger.warning(
            "ClassAttrs for 'Field' not found. Source information will be incomplete."
        )
        return []

    original_attrs: dict[str, str] = {
        a.get("name"): a.text
        for a in original_field_element.xpath("./A")
        if a.get("name")
    }

    report_rows: list[AuditRow] = []

    for attr_def in class_attrs.attr_dict.values():
        attr_name = attr_def.name
        param_obj = field.attr_dict.get(attr_name)

        if param_obj is None or not isinstance(param_obj, A):
            continue

        source: Literal["input", "static_default", "smart_default", "unknown"]
        static_default = attr_def.default

        if attr_name in original_attrs:
            source = "input"
        elif attr_name in SmartDefault.registry:
            source = "smart_default"
        elif static_default is not None:
            source = "static_default"
        else:
            source = "unknown"

        attr_value = param_obj.value
        if isinstance(attr_value, Quantity):
            attr_value = attr_value.m

        report_rows.append(
            AuditRow(
                field=field.name,
                attribute=attr_name,
                source=source,
                value=repr(attr_value),
                unit=str(param_obj.unit) if param_obj.unit else "",
            )
        )

    return report_rows


def audit_field(
    field: Field, mf: ModelFile, audit_level: str | None = None
) -> pd.DataFrame | None:
    """
    Control field auditing based on configuration settings.

    :param field: The Field object
    :param mf: The ModelFile object
    :param audit_level: The audit level string
    :return: A list of audit data dictionaries or None if auditing is disabled or fails.
    """
    if not (audit_level is None or _is_audit_level_str(audit_level)):
        raise ValueError(
            f'Invalid AuditLevel. Must be one of "all", "none", "field", or "processes" ({audit_level} provided)'
        )
    audit_flag = _translate_audit_level(audit_level)

    if audit_flag == AuditFlag.NONE:
        return None
    report_data: list[AuditRow] = []
    if audit_flag & AuditFlag.FIELD:
        root = mf.root
        elem_list = root.xpath(f".//Field[@name='{field.name}']")
        if not elem_list:
            _logger.error(
                f"Audit failed for field '{field.name}': Original field element not found in XML."
            )
            return None
        field_elem: etree._Element = elem_list[0]
        report_data = _generate_field_audit_report(field, field_elem)

    if audit_flag & AuditFlag.PROCESSES:
        out_dir = getParam("OPGEE.output_dir") or "results"
        final_path = Path(out_dir) / f"{field.name}_process_graph.png"
        write_process_diagram(field, final_path)

    return pd.DataFrame(report_data) if report_data else None
