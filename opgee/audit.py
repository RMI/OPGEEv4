from typing import Optional, List, Dict
import lxml.etree as ET
from pathlib import Path
import logging

from opgee.field import Field
from opgee.model_file import ModelFile
from opgee.attributes import AttrDefs
from opgee.core import A
from opgee.smart_defaults import SmartDefault
from opgee.xml_utils import field_to_xml
from opgee.config import getParam
from opgee.log import getLogger

_logger = getLogger(__name__)


def create_audit_xml(field: Field, model_file: ModelFile, output_path: Optional[str] = None) -> str:
    """
    Create an XML audit file that captures the current state of a field model,
    annotating attribute sources (default, smart default).

    :param field: The Field object to audit.
    :param model_file: The ModelFile object containing the original field definition.
    :param output_path: Optional path to save the XML file.
    :return: The XML string representation of the audit.
    """
    # Get Attribute Definitions instance
    attr_defs = AttrDefs.get_instance()
    if not attr_defs:
        print("Warning: Attribute definitions (AttrDefs) not loaded. Source information will be incomplete.")
        # Depending on strictness, might raise an error here

    # Get the original XML tree root from the model file
    original_xml_root = model_file.getroot()
    if original_xml_root is None:
        raise ValueError(f"Could not get XML root from model file '{model_file.pathname}'.")

    # Generate the XML structure based on the current field state using field_to_xml
    # Pass the original root, as field_to_xml uses it to filter etc.
    generated_xml_root = field_to_xml(field, original_xml_root)

    # Find the generated Field element (should be the only one left)
    generated_field_elem = generated_xml_root.find('.//Field')
    if generated_field_elem is None:
         raise ValueError(f"Could not find generated Field element for '{field.name}'.")

    # Find the original Field element in the original XML
    original_field_elem_list = original_xml_root.xpath(f".//Field[@name='{field.name}']")
    if not original_field_elem_list:
        raise ValueError(f"Field '{field.name}' not found in the original model file '{model_file.pathname}'.")
    original_field_elem = original_field_elem_list[0]

    # --- Process Field-level Attributes ---
    original_field_attrs = {a.get('name'): a.text for a in original_field_elem.xpath('./A') if a.get('name')}

    # Use xpath to get direct children <A> elements
    for attr_elem in generated_field_elem.xpath('./A'):
        name = attr_elem.get('name')
        param_obj = field.attr_dict.get(name)

        if isinstance(param_obj, A) and name not in original_field_attrs and not param_obj.explicit:
            source_comment_text = None
            if attr_defs:
                class_attrs = attr_defs.class_attrs(field.__class__.__name__, raiseError=False)
                attr_def = class_attrs.attribute(name, raiseError=False) if class_attrs else None
                if attr_def and attr_def.default is not None:
                    try:
                        if param_obj.value == attr_def.default:
                            source_comment_text = "default"
                        else:
                            source_comment_text = "smart default"
                    except Exception: # Comparison might fail (e.g., units)
                        source_comment_text = "smart default"
                else: # No static default defined
                    source_comment_text = "smart default"

            if source_comment_text:
                comment = ET.Comment(f" {source_comment_text} ")
                generated_field_elem.insert(generated_field_elem.index(attr_elem), comment)


    # --- Process Process-level Attributes ---
    # Iterate through generated Process elements
    for process_elem in generated_field_elem.xpath('.//Process'):
        process_instance_name = process_elem.get('name')
        process_class_name = process_elem.get('class')

        if not process_instance_name:
            print(f"Warning: Process element found without a 'name' attribute in generated XML (class: {process_class_name}). Skipping attribute source check.")
            continue

        process = field.find_process(process_instance_name, raiseError=False)
        if not process:
            print(f"Warning: Could not find process object for instance '{process_instance_name}'. Skipping attribute source check.")
            continue

        # Find the corresponding original process element (simplistic match by name)
        # This might need refinement if process names aren't unique across aggregators
        original_process_elem_list = original_field_elem.xpath(f".//Process[@name='{process_instance_name}']")
        original_process_attrs = {}
        if original_process_elem_list:
            original_process_elem = original_process_elem_list[0]
            original_process_attrs = {a.get('name'): a.text for a in original_process_elem.xpath('./A') if a.get('name')}

        # Iterate through attributes in the generated process element
        for attr_elem in process_elem.xpath('./A'):
            name = attr_elem.get('name')
            param_obj = process.attr_dict.get(name)

            if isinstance(param_obj, A) and name not in original_process_attrs and not param_obj.explicit:
                source_comment_text = None
                if attr_defs:
                    # Check specific class, then base Process class
                    class_attrs = attr_defs.class_attrs(process_class_name, raiseError=False)
                    attr_def = class_attrs.attribute(name, raiseError=False) if class_attrs else None
                    if not attr_def:
                        process_base_attrs = attr_defs.class_attrs('Process', raiseError=False)
                        attr_def = process_base_attrs.attribute(name, raiseError=False) if process_base_attrs else None

                    if attr_def and attr_def.default is not None:
                        try:
                            if param_obj.value == attr_def.default:
                                source_comment_text = "default"
                            else:
                                source_comment_text = "smart default"
                        except Exception:
                            source_comment_text = "smart default"
                    else: # No static default defined
                        source_comment_text = "smart default"

                if source_comment_text:
                    comment = ET.Comment(f" {source_comment_text} ")
                    process_elem.insert(process_elem.index(attr_elem), comment)


    # Convert final XML tree to string
    # Use generated_xml_root which now contains the comments
    xml_str = ET.tostring(generated_xml_root, encoding='unicode', pretty_print=True, method='xml')

    # Save to file if path provided
    if output_path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(xml_str)

    return xml_str


def generate_field_audit_report(field: Field, original_field_element: ET._Element) -> List[Dict]:
    """
    Generate a report detailing the source of each field-level attribute's final value.
    
    :param field: The final Field object (after run attempt)
    :param original_field_element: The lxml.etree._Element representing the original <Field> definition from input XML
    :return: List of dictionaries, each containing information about an attribute:
             {
                 'attribute': attribute name,
                 'value': attribute value,
                 'unit': attribute unit (if applicable),
                 'source': source of the value ('input', 'default', 'smart_default', or 'unknown')
             }
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
    original_attrs = {a.get('name'): a.text for a in original_field_element.xpath('./A') if a.get('name')}
    
    # Initialize empty list for report rows
    report_rows = []
    
    # Iterate through all AttrDef objects defined within the "Field" ClassAttrs
    for attr_def in class_attrs.attr_defs:
        attr_name = attr_def.name
        
        # Get the corresponding A object from the final field state
        param_obj = field.attr_dict.get(attr_name)
        
        # Skip if param_obj is None or not an instance of A
        if param_obj is None or not isinstance(param_obj, A):
            continue
        
        # Determine the source label
        if attr_name in original_attrs:
            source = "input"
        else:
            # Not in original input, check if it matches the static default
            static_default = attr_def.default
            if static_default is not None:
                try:
                    if param_obj.value == static_default:
                        source = "default"
                    else:
                        # Doesn't match static default, check SmartDefault
                        if attr_name in SmartDefault.registry:
                            source = "smart_default"
                        else:
                            source = "unknown"
                except Exception:
                    # Comparison issues (e.g., units), check SmartDefault
                    if attr_name in SmartDefault.registry:
                        source = "smart_default"
                    else:
                        source = "unknown"
            else:
                # No static default, check SmartDefault
                if attr_name in SmartDefault.registry:
                    source = "smart_default"
                else:
                    source = "unknown"
        
        # Create a dictionary for the row
        row = {
            'attribute': attr_name,
            'value': param_obj.value,  # Consider converting pint Quantities to magnitude for CSV
            'unit': str(param_obj.unit) if param_obj.unit else '',
            'source': source
        }
        
        # Append row to report_rows
        report_rows.append(row)
    
    return report_rows


def audit_field(field: Optional[Field], mf: Optional[ModelFile]) -> Optional[List[Dict]]:
    """
    Controller function for field auditing based on configuration settings.
    
    :param field: The Field object (potentially None)
    :param mf: The ModelFile object (potentially None)
    :return: A list of audit data dictionaries or None if auditing is disabled or fails
    """
    # Read configuration
    config_level = getParam('OPGEE.AuditLevel', raiseError=False)
    
    # If config_level is None, return None
    if config_level is None:
        return None
    
    # If field or mf is None, skip audit
    if field is None or mf is None:
        _logger.debug("Audit skipped: Field or ModelFile object is None.")
        return None
    
    # Check if field-level auditing is enabled
    if config_level in ["FieldLevel", "Full"]:
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
        report_data = generate_field_audit_report(field, original_field_elem)
        return report_data
    
    # If config_level is Graph or other value, return None for now
    # Future implementation could add graph generation here
    return None
