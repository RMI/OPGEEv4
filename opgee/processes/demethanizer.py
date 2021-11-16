import pandas as pd

from ..log import getLogger
from ..process import Process
from ..stream import PHASE_LIQUID, PHASE_GAS
from ..process import run_corr_eqns
from opgee import ureg
from ..compressor import Compressor
from ..thermodynamics import component_MW
from ..energy import Energy, EN_NATURAL_GAS, EN_ELECTRICITY, EN_DIESEL
from ..emissions import Emissions, EM_COMBUSTION, EM_LAND_USE, EM_VENTING, EM_FLARING, EM_FUGITIVES

_logger = getLogger(__name__)


class Demethanizer(Process):
    def _after_init(self):
        super()._after_init()
        self.field = field = self.get_field()
        self.gas = field.gas
        self.std_temp = field.model.const("std-temperature")
        self.std_press = field.model.const("std-pressure")
        self.feed_press_demethanizer = self.attr("feed_press_demethanizer")
        self.colume_pressure = self.attr("colume_pressure")
        self.methane_to_NLG_ratio = self.attr("methane_to_NLG_ratio")
        self.demethanizer_tbl = field.model.demethanizer
        self.mol_per_scf = field.model.const("mol-per-scf")
        self.eta_reboiler_demethanizer = self.attr("eta_reboiler_demethanizer")
        self.air_cooler_speed_reducer_eff = self.attr("air_cooler_speed_reducer_eff")
        self.air_cooler_delta_T = self.attr("air_cooler_delta_T")
        self.air_cooler_fan_eff = self.attr("air_cooler_fan_eff")
        self.air_cooler_press_drop = self.attr("air_cooler_press_drop")
        self.water_press = field.water.density() * \
                           self.air_cooler_press_drop * \
                           field.model.const("gravitational-acceleration")
        self.eta_compressor = self.attr("eta_compressor")
        self.prime_mover_type = self.attr("prime_mover_type")

    def run(self, analysis):
        self.print_running_msg()

        # mass rate
        input = self.find_input_streams("gas for demethanizer", combine=True)

        loss_rate = self.venting_fugitive_rate()
        gas_fugitives_temp = self.set_gas_fugitives(input, loss_rate)
        gas_fugitives = self.find_output_stream("gas fugitives")
        gas_fugitives.copy_flow_rates_from(gas_fugitives_temp)
        gas_fugitives.set_temperature_and_pressure(self.std_temp, self.std_press)

        # Demethanizer modeling based on Aspen HYSYS
        feed_gas_press = min(max(self.feed_press_demethanizer.to("psia").m, 600.0), 1000.0)
        colume_press = min(max(self.colume_pressure.to("psia").m, 155.0), 325.0)
        methane_to_NGL_ratio = min(max(self.methane_to_NLG_ratio.to("frac").m, 0.01), 0.05)
        feed_gas_mol_fracs = self.gas.component_molar_fractions(input)
        mol_frac_C1 = min(max(feed_gas_mol_fracs["C1"].to("frac").m if "C1" in feed_gas_mol_fracs.index else 0, 0.5),
                          0.95)
        mol_frac_C2 = min(max(feed_gas_mol_fracs["C2"].to("frac").m if "C2" in feed_gas_mol_fracs.index else 0, 0.05),
                          0.95)

        gas_volume_rate = self.gas.tot_volume_flow_rate_STP(input)
        gas_multiplier = gas_volume_rate.to("mmscf/day").m / 99.8  # multiplier for gas load in correlation equation

        x1 = feed_gas_press
        x2 = colume_press
        x3 = methane_to_NGL_ratio
        x4 = mol_frac_C1
        x5 = mol_frac_C2
        corr_result_df = run_corr_eqns(x1, x2, x3, x4, x5, self.demethanizer_tbl)
        reboiler_heavy_duty = ureg.Quantity(max(0, corr_result_df.loc["Reboiler", :].sum() * gas_multiplier), "kW")
        cooler_thermal_load = ureg.Quantity(max(0, corr_result_df.loc["HEX", :].sum() * gas_multiplier), "kW")
        NGL_label = ["NGL C1", "NGL C2", "NGL C3", "NGL C4"]
        fuel_gas_label = ["fuel gas C1", "fuel gas C2", "fuel gas C3", "fuel gas C4"]
        hydrocarbon_label = ["C1", "C2", "C3", "C4"]
        NGL_frac = pd.Series({name: max(0, corr_result_df.loc[tbl_name, :].sum()) for name, tbl_name in
                              zip(hydrocarbon_label, NGL_label)},
                             dtype="pint[frac]")
        fuel_gas_frac = pd.Series({name: max(0, corr_result_df.loc[tbl_name, :].sum()) for name, tbl_name in
                                   zip(hydrocarbon_label, fuel_gas_label)},
                                  dtype="pint[frac]")

        hydrocarbon_frac = pd.Series({name: self.gas.molar_flow_rate(input, name) for name in hydrocarbon_label})

        fuel_gas_prod = (hydrocarbon_frac["C1"] - NGL_frac["C1"] * hydrocarbon_frac["C2"] / NGL_frac["C2"]) / \
                        (fuel_gas_frac["C1"] - NGL_frac["C1"] * fuel_gas_frac["C2"] / NGL_frac["C2"])
        reboiler_fuel_use = reboiler_heavy_duty * self.eta_reboiler_demethanizer
        cooler_energy_consumption = self.predict_blower_energy_use(cooler_thermal_load,
                                                                   self.air_cooler_delta_T,
                                                                   self.water_press,
                                                                   self.air_cooler_fan_eff,
                                                                   self.air_cooler_speed_reducer_eff)
        fuel_gas_mass = fuel_gas_prod * fuel_gas_frac * component_MW[fuel_gas_frac.index]

        gas_to_gather = self.find_output_stream("gas for gas partition")
        gas_to_gather.copy_flow_rates_from(input)
        gas_to_gather.subtract_gas_rates_from(gas_fugitives)
        gas_to_gather.set_rates_from_series(fuel_gas_mass, PHASE_GAS)
        gas_to_gather.set_temperature_and_pressure(input.temperature, input.pressure)

        gas_to_LNG = self.find_output_stream("gas for NGL")
        gas_to_LNG.copy_flow_rates_from(input)
        gas_to_LNG.subtract_gas_rates_from(gas_to_gather)
        gas_to_LNG.set_temperature_and_pressure(self.std_temp, input.pressure)
        C2_mass_rate = gas_to_LNG.gas_flow_rate("C2")
        gas_to_LNG.set_gas_flow_rate("C2", ureg.Quantity(0, "tonne/day"))

        # TODO: ethane to petrochemicals

        # inlet boosting compressor
        overall_compression_ratio = self.feed_press_demethanizer / input.pressure
        inlet_compressor_energy_consump = self.compressor_energy_consumption(overall_compression_ratio,
                                                                             input.temperature,
                                                                             input.pressure,
                                                                             gas_to_gather)

        # outlet compressor
        feed_gas_exit_press = ureg.Quantity(corr_result_df.loc["fuel gas pressure", :].sum(), "psia")
        overall_compression_ratio = input.pressure / feed_gas_exit_press
        outlet_compressor_energy_consump = self.compressor_energy_consumption(overall_compression_ratio,
                                                                              input.temperature,
                                                                              input.pressure,
                                                                              gas_to_gather)

        # energy-use
        energy_use = self.energy
        if self.prime_mover_type == "NG_engine" or "NG_turbine":
            energy_carrier = EN_NATURAL_GAS
        elif self.prime_mover_type == "Electric_motor":
            energy_carrier = EN_ELECTRICITY
        else:
            energy_carrier = EN_DIESEL
        energy_use.set_rate(energy_carrier, inlet_compressor_energy_consump + outlet_compressor_energy_consump)
        energy_use.add_rate(EN_NATURAL_GAS, reboiler_fuel_use)
        energy_use.set_rate(EN_ELECTRICITY, cooler_energy_consumption)

        # emissions
        emissions = self.emissions
        energy_for_combustion = energy_use.data.drop("Electricity")
        combustion_emission = (energy_for_combustion * self.process_EF).sum()
        emissions.add_rate(EM_COMBUSTION, "CO2", combustion_emission)

        emissions.add_from_stream(EM_FUGITIVES, gas_fugitives)

    def compressor_energy_consumption(self, overall_compression_ratio, inlet_temp, inlet_press, stream):
        compression_ratio = Compressor.get_compression_ratio(overall_compression_ratio)
        num_stages = Compressor.get_num_of_compression(overall_compression_ratio)
        total_work, _ = Compressor.get_compressor_work_temp(self.field,
                                                            inlet_temp,
                                                            inlet_press,
                                                            stream,
                                                            compression_ratio,
                                                            num_stages)
        volume_flow_rate_STP = self.gas.tot_volume_flow_rate_STP(stream)
        total_energy = total_work * volume_flow_rate_STP
        brake_horse_power = total_energy / self.eta_compressor
        energy_consumption = self.get_energy_consumption(self.prime_mover_type, brake_horse_power)

        return energy_consumption