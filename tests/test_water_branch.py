import pytest
from opgee import Process
from .utils_for_tests import load_test_model


class Before(Process):
    def run(self, analysis):
        pass

    def impute(self):
        pass


class After(Process):
    def run(self, analysis):
        pass

    def impute(self):
        pass


@pytest.fixture(scope="module")
def test_water_branch(configure_logging_for_tests):
    return load_test_model('test_water_branch.xml')


def test_steam(test_water_branch):
    analysis = test_water_branch.get_analysis('test_steam_generation')
    field = analysis.get_field('test_steam')
    field.run(analysis)


def test_water(test_water_branch):
    analysis = test_water_branch.get_analysis('test_water_injection')
    field = analysis.get_field('test_water')
    field.run(analysis)