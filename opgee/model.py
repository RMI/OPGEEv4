"""
.. OPGEE Model and ModelFile classes

.. Copyright (c) 2021 Richard Plevin and Stanford University
   See the https://opensource.org/licenses/MIT for license details.
"""
from .analysis import Analysis
from .container import Container
from .core import instantiate_subelts, elt_name, ureg
from .config import getParam
from .emissions import Emissions
from .error import OpgeeException
from .log import getLogger
from .stream import Stream
from .table_manager import TableManager
from .utils import loadModuleFromPath, splitAndStrip
from .XMLFile import XMLFile

_logger = getLogger(__name__)

# TBD
# Create a directed graph in Network X to simplify do loop detection.
# Add “visited” flags to processes and technologies, and may be a list of visited nudes so they can be reset easily without searching.
# Support both max number of iterations, and designation of an output variable v and a value epsilon so the iteration stops when,
#    between iterations, %change < epsilon.
# How to handle multiple loops? Each may need a value to compare against to detect convergence.

class Model(Container):
    def __init__(self, name, analysis, attr_dict=None):
        super().__init__(name, attr_dict=attr_dict)

        self.analysis = analysis
        analysis.parent = self

        self.table_mgr = tbl_mgr = TableManager()

        # load all the GWP options
        df = tbl_mgr.get_table('GWP')
        self.gwp20  = df.query('Years ==  20').set_index('Gas', drop=True).drop('Years', axis='columns')
        self.gwp100 = df.query('Years == 100').set_index('Gas', drop=True).drop('Years', axis='columns')

        # This will be set to a pandas.Series holding the current values in use, indexed by gas name
        self.gwp = None

        # Use the GWP years and version specified in XML
        gwp_years   = self.attr('GWP_years')
        gwp_version = self.attr('GWP_version')
        self.use_GWP(gwp_years, gwp_version)

        # TBD: convert to dict mapping names to unitful values
        df = tbl_mgr.get_table('constants')
        self.constants = {name : ureg.Quantity(row.value, row.unit) for name, row in df.iterrows()}

    # TBD: how to pass args like fields to process?
    # TBD: also need to clear all prior data to avoid collecting stale data?
    def run(self):
        """
        Run all Analyses and collect emissions and energy use for all Containers and Processes.

        :return: None
        """
        for child in self.children():
            child.run() # TBD: args?

        # calculate and store results internally
        self.get_energy_rates()
        self.get_emission_rates()

    def use_GWP(self, gwp_years, gwp_version):
        """
        Set which GWP values to use for this model. Initially set from the XML model definition,
        but this function allows this choice to be changed after the model is loaded, e.g., by
        choosing different values in a GUI and rerunning the emissions summary.

        :param gwp_years: (int) the GWP time horizon; currently must 20 or 100.
        :param gwp_version: (str) the GWP version to use; must be one of 'AR4', 'AR5', 'AR5_CCF'
        :return: none
        """
        from pint import Quantity

        # TBD: validate these against options in attributes.xml rather than hardcoding here
        valid_years = (20, 100)
        valid_versions = ('AR4', 'AR5', 'AR5_CCF')

        if isinstance(gwp_years, Quantity):
            gwp_years = gwp_years.magnitude

        if gwp_years not in valid_years:
            raise OpgeeException(f"GWP years must be one of {valid_years}; value given was {gwp_years}")

        if gwp_version not in valid_versions:
            raise OpgeeException(f"GWP version must be one of {valid_versions}; value given was {gwp_version}")

        df = self.gwp20 if gwp_years == 20 else self.gwp100
        gwp = df[gwp_version]
        self.gwp = gwp.reindex(index=Emissions.emissions)  # keep them in the same order for consistency

    def GWP(self, gas):
        """
        Return the GWP for the given gas, using the model's settings for GWP time horizon and
        the version of GWPs to use.

        :param gas: (str) a gas for which a GWP has been defined. Current list is CO2, CO, CH4, N2O, and VOC.
        :return: (int) GWP value
        """
        return self.gwp[gas]

    def const(self, name):
        """
        Return the value of a constant declared in tables/constants.csv

        :param name: (str) name of constant
        :return: (float with unit) value of constant
        """
        try:
            return self.constants[name]
        except KeyError:
            raise OpgeeException(f"No known constant with name '{name}'")

    def _children(self, include_disabled=False):
        """
        Return a list of all children. External callers should use children() instead,
        as it respects the self.is_enabled() setting.
        """
        return [self.analysis]

    def summarize(self):
        """
        Return a summary of energy use and emissions, by Model, Field, Aggregator, and Process.

        :return: TBD: Unclear what the best structure for this is; it depends how it will be used.
        """
        pass

    def validate(self):

        # TBD: validate all attributes of classes Field, Process, etc.
        # attributes = AttributeDefs()
        # field_attrs = attributes.class_attrs('Field')
        # print(field_attrs.attribute('downhole_pump'))
        # print(field_attrs.attribute('ecosystem_richness'))
        # print(field_attrs.option('ecosystem_C_richness'))

        show_streams = False

        if show_streams:
            for field in self.analysis.children():
                print(f"Processes for field {field.name}")
                for proc in field.processes():
                    print(f"  {proc}")

                print(f"\nStreams for field {field.name}")
                for stream in field.streams():
                    print(f"  {stream}")

            print("")

    def report(self):
        pass

    @classmethod
    def from_xml(cls, elt):
        """
        Instantiate an instance from an XML element

        :param elt: (etree.Element) representing a <Model> element
        :return: (Model) instance populated from XML
        """
        analyses = instantiate_subelts(elt, Analysis)
        count = len(analyses)
        if count != 1:
            raise OpgeeException(f"Expected on <Analysis> element; got {count}")

        attr_dict = cls.instantiate_attrs(elt)

        obj = Model(elt_name(elt), analyses[0], attr_dict=attr_dict)
        return obj


# TBD: grab a path like OPGEE.UserClassPath, which defaults to OPGEE.ClassPath
# TBD: split these and load all *.py files in each directory (if a directory;
# TBD: allow specify specific files in path as well)
# TBD: import these into this module so they're found by class_from_str()?
# TBD: Alternatively, create dict of base classname and actual module it's in
# TBD: by looping over sys.modules[name]
class ModelFile(XMLFile):
    """
    Represents the overall parameters.xml file.
    """
    def __init__(self, filename, stream=None):
        import os
        from pathlib import Path

        extra_components = getParam('OPGEE.StreamComponents')
        if extra_components:
            names = splitAndStrip(extra_components, ',')
            Stream.extend_components(names)

        # We expect a single 'Analysis' element below Model
        _logger.debug("Loading model file: %s", filename)

        super().__init__(stream or filename, schemaPath='etc/opgee.xsd')

        class_path = getParam('OPGEE.ClassPath')
        paths = [Path(path) for path in class_path.split(os.path.pathsep) if path]
        for path in paths:
            if path.is_dir():
                for module_path in path.glob('*.py'):   # load all .py files found in directory
                    loadModuleFromPath(module_path)
            else:
                loadModuleFromPath(path)

        self.root = self.tree.getroot()
        self.model = Model.from_xml(self.root)