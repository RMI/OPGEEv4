import pytest
import lxml.etree as ET
from unittest.mock import patch, MagicMock # Keep MagicMock for SmartDefault patch

# Keep existing imports for Field, generate_field_audit_report, A, SmartDefault
from opgee.field import Field
from opgee.audit import generate_field_audit_report
from opgee.core import A
from opgee.smart_defaults import SmartDefault

# Import model loading utilities
from opgee.model_file import ModelFile
from .utils_for_tests import path_to_test_file


def test_generate_field_audit_report(): # Use existing fixture
    """
    Test that generate_field_audit_report correctly identifies attribute sources
    using a real model loaded from XML.
    """
    # AttrDefs will be loaded automatically when ModelFile is instantiated.
    model_file_path = path_to_test_file('test_model.xml')
    mf = ModelFile(model_file_path, use_default_model=False) # use_default_model=False prevents merging default model XML

    # Get the Field object from the fixture-provided model
    model = mf.model # Model object from fixture
    field = model.get_field('test')

    # Get the original XML element for the specific field
    original_xml_root = mf.root
    original_field_elem_list = original_xml_root.xpath(f".//Field[@name='{field.name}']")
    assert original_field_elem_list, f"Field '{field.name}' not found in {model_file_path}"
    original_field_elem = original_field_elem_list[0]

    # --- Add a mock attribute to test the 'smart_default' path ---
    # Create a dummy attribute that wasn't in the input XML or static defaults
    #smart_attr_name = 'hypothetical_smart_attr'
    #field.attr_dict[smart_attr_name] = A(smart_attr_name, value=123.45, unit='kg')
    # Mock the SmartDefault registry just for this attribute
    #mock_smart_registry = {smart_attr_name: MagicMock()}
    # --- End of mock attribute setup ---

    # Patch the SmartDefault registry for the test duration
    #with patch('opgee.audit.SmartDefault.registry', mock_smart_registry):
        # Call the function under test
        #result = generate_field_audit_report(field, original_field_elem)

    result = generate_field_audit_report(field, original_field_elem_list)
    # Verify the results
    assert isinstance(result, list)
    assert len(result) > 0 # Ensure some results are returned

    # Create a dictionary for easy lookup
    sources = {row['attribute']: row['source'] for row in result}
    values = {row['attribute']: row['value'] for row in result}

    # --- Assertions ---
    # Attributes defined in test_model.xml -> 'input'
    assert sources.get('API') == 'input'
    assert sources.get('age') == 'input'
    assert sources.get('GOR') == 'input'
    assert sources.get('depth') == 'input'
    assert sources.get('country') == 'input'
    assert sources.get('offshore') == 'input'
    # Check a value to be sure it's reading correctly
    assert values.get('API') == 32.8

    # Attributes *not* in test_model.xml but with static defaults in attributes.xml -> 'default'
    # Check if the default value was actually assigned during Field init
    assert 'downhole_pump' in field.attr_dict
    assert field.attr_dict['downhole_pump'].value == 1 # Default is 1
    assert sources.get('downhole_pump') == 'default'

    assert 'water_reinjection' in field.attr_dict
    assert field.attr_dict['water_reinjection'].value == 1 # Default is 1
    assert sources.get('water_reinjection') == 'default'

    # Check the mocked smart default attribute
    assert sources.get(smart_attr_name) == 'smart_default'
    assert values.get(smart_attr_name) == 123.45

    # Example of an attribute with a default value of 0 that wasn't specified
    assert 'gas_lifting' in field.attr_dict
    assert field.attr_dict['gas_lifting'].value == 0 # Default is 0
    assert sources.get('gas_lifting') == 'default'
