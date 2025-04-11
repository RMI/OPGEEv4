from typing import Optional
import lxml.etree as ET
from pathlib import Path

from opgee.field import Field
from opgee.model_file import ModelFile
from opgee.attributes import AttrDefs
from opgee.core import A
from opgee.xml_utils import field_to_xml


def create_audit_xml(field: Field, model_file: ModelFile, output_path: Optional[str] = None) -> str:
    """
    Create an XML audit file that captures the current state of a field model,
    annotating attribute sources (default, smart default).

    Args:
        field: The Field object to audit.
        model_file: The ModelFile object containing the original field definition.
        output_path: Optional path to save the XML file.

    Returns:
        The XML string representation of the audit.
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
