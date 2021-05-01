# pkgutil doesn't provide a method to discover all the files in a package subdirectory
# so we identify the basenames of the files here and then extract them into a structure.
import os
import pandas as pd
from opgee.core import OpgeeObject
from opgee.error import OpgeeException
from opgee.pkg_utils import resourceStream

class TableDef(object):
    """
    Holds meta-data for built-in tables (CSV files loaded into `pandas.DataFrames`).
    """
    def __init__(self, basename, index_col=None, skiprows=0, units=None):
        self.basename = basename
        self.index_col = index_col
        self.skiprows = skiprows
        self.units = units

class TableManager(OpgeeObject):
    """
    The TableManager loads built-in CSV files into DataFrames and stores them in a dictionary keyed by the root name
    of the table. When adding CSV files to the opgee “tables” directory, a corresponding entry must be added in the
    TableManager class variable ``TableManager.table_defs``, which holds instances of `TableDef` class.

    Users can add external tables using the ``add_table`` method.
    """
    table_defs = [
        TableDef('constants', index_col='name'),
        TableDef('GWP', index_col=False),
        TableDef('bitumen-mining-energy-intensity', index_col=0),
        TableDef('transport-specific-EF', index_col=('Mode', 'Fuel'), skiprows=1, units='g/mmbtu'),
        TableDef('stationary-application-EF', index_col=('Fuel', 'Application'), skiprows=1, units='g/mmbtu'),
    ]

    def __init__(self):
        self.table_dict = table_dict = {}

        # TBD: load tables on demand
        for t in self.table_defs:
            relpath = f"tables/{t.basename}.csv"
            s = resourceStream(relpath, stream_type='text')
            df = pd.read_csv(s, index_col=t.index_col, skiprows=t.skiprows)
            table_dict[t.basename] = df

    def get_table(self, name):
        """
        Retrieve a dataframe representing CSV data loaded by the TableManager

        :param name: (str) the name of a table
        :return: (pandas.DataFrame) the corresponding data
        :raises: OpgeeException if the `name` is unknown.
        """
        try:
            return self.table_dict[name]
        except KeyError:
            raise OpgeeException(f"Failed to find table named {name}.")

    def add_table(self, pathname, index_col=None, skiprows=0): #  , units=None):
        """
        Add a CSV file external to OPGEE to the TableManager.

        :param pathname: (str) the pathname of a CSV file
        :param index_col: (str, int, iterable of str or int, False, or None) see doc
            for `pandas.read_csv()`
        :param skiprows: (int) the number of rows to skip before the table begins.
        :return: none
        """
        df = pd.read_csv(pathname, index_col=index_col, skiprows=skiprows)
        name = os.path.splitext(os.path.basename(pathname))[0]
        self.table_dict[name] = df